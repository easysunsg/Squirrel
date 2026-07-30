"""Squirrel 库存助手的 LangGraph 工作流。

架构说明：
- 当前拓扑由输入、控制、规划、执行、校验、恢复和输出等节点组成
- 保留 run_squirrel_graph 签名不变，外部使用者（ai.py / test_graph.py）无需改动
- 内部使用 ExtendedGraphState 流转，输出前通过 extended_to_old_dict 适配回旧格式
- 所有路径收敛到 post_process，消灭直通 END 的叶子节点
"""

import json
import logging
import re
from datetime import date, datetime

from pydantic import ValidationError

from app.core.constants import (
    EXPIRE_WARNING_DAYS,
    FUZZY_LOCATION_CHARS,
    MIN_PARTIAL_MATCH_LENGTH,
    NO_EXPIRE_SORT_KEY,
    VALID_INVENTORY_CATEGORIES,
)
from app.models.extraction import SearchConstraints
from app.models.schemas import Item
from app.services.llm import llm_service
from app.services.spatial_service import spatial_service
from app.services.temperature import _check_temperature_zone
from app.services.vector_store import vector_store

logger = logging.getLogger(__name__)

VALID_SEARCH_CATEGORIES = frozenset({
    "", "beverage", *VALID_INVENTORY_CATEGORIES,
})
BEVERAGE_TERMS = (
    "牛奶", "酸奶", "豆奶", "奶茶", "果汁", "蔬菜汁", "橙汁", "苹果汁", "葡萄汁",
    "可乐", "雪碧", "汽水", "矿泉水", "苏打水", "巴黎水", "饮料", "啤酒", "红酒",
    "白酒", "咖啡", "茶", "椰子水", "气泡水", "功能饮料", "乳酸菌",
)


# ==============================
# 共享工具函数（移植自旧图）
# ==============================


def summarize_titles(items: list[Item], limit: int = 6) -> str:
    return "、".join(item.title for item in items[:limit])


def _is_pronoun_or_garbage_target(target: str) -> bool:
    """检测 LLM 提取的 target 是否为代词或垃圾短语，需回退到上下文。"""
    pronouns = {"这个", "那个", "这些", "那些", "它", "它们", "这东西", "那东西",
                "这些东西", "那些东西", "这", "那", "该物品", "刚才说的", "上回说的"}
    if target in pronouns:
        return True
    # 以常见中文代词开头的短语 → 也是指代
    if any(target.startswith(p) for p in ("这个", "那个", "这些", "那些", "它", "它们", "这东西", "那东西", "该物品")):
        return True
    # 包含"处理过的/已处理的/吃过的/用过的"等说明性后缀 → 用户是在解释原因
    if re.search(r"已?[处理吃用]\s*过\s*的", target):
        return True
    # 纯说明性短语 / 垃圾值——以动词/形容词开头且长度超过 3 个字
    garbage_prefixes = ("已处理", "处理过", "吃过", "用过", "刚刚", "刚才", "那个", "已经")
    if any(target.startswith(p) for p in garbage_prefixes) and len(target) > 3:
        return True
    return False


def match_search_items(
    text: str,
    inventory: list[Item],
    *,
    exclude_item_id: str | None = None,
    exclude_title: str | None = None,
    extracted_constraints: SearchConstraints | dict | None = None,
    **kwargs,
) -> list[Item]:
    """Apply hard search constraints synchronously, then use semantic search for ranking.

    LangGraph currently invokes its nodes synchronously.  Keeping this helper synchronous is
    important: returning an awaitable here makes query_handler_node try to slice a coroutine.
    """
    if kwargs:
        logger.debug("Unused search arguments: %s", sorted(kwargs))
    if isinstance(extracted_constraints, SearchConstraints):
        constraints = extracted_constraints
    elif isinstance(extracted_constraints, dict):
        try:
            constraints = SearchConstraints.model_validate(extracted_constraints)
        except ValidationError:
            logger.warning("Upstream search constraints were invalid; extracting again")
            constraints = extract_search_constraints(text)
    else:
        constraints = extract_search_constraints(text)

    def within_constraints(item: Item) -> bool:
        if exclude_item_id and item.id == exclude_item_id:
            return False
        if exclude_title and item.title == exclude_title:
            return False
        if constraints.exclude:
            exclude_haystack = (
                f"{item.title} {item.location} {item.spaceName} "
                f"{item.remark or ''} {' '.join(item.tags)}"
            )
            if any(name in exclude_haystack for name in constraints.exclude):
                return False
        # Location constraints are mandatory; semantic resolution supplements text matching.
        if constraints.location_hint:
            location_text = f"{item.spaceName} {item.location}"
            hint = constraints.location_hint
            slot_ids = spatial_service.resolve_location_to_slots(hint)
            textual_match = hint in location_text or location_text.strip() in hint or any(
                hint in {char, f"{char}子"} and char in location_text
                for char in FUZZY_LOCATION_CHARS
            )
            slot_match = bool(item.belongsToSlotId and item.belongsToSlotId in slot_ids)
            if not textual_match and not slot_match:
                return False
        # The persisted category enum has no beverage value, so beverages need title/tag matching.
        if constraints.category == "beverage":
            haystack = f"{item.title} {' '.join(item.tags)} {item.remark or ''}"
            if not any(name in haystack for name in BEVERAGE_TERMS):
                return False
        elif constraints.category and constraints.category != "other":
            if item.category != constraints.category:
                return False
        # 温区
        if constraints.temperature_zone != "any":
            if not _check_temperature_zone(item, constraints.temperature_zone):
                return False
        # 属性：tags + remark 模糊匹配
        if constraints.attributes:
            haystack = f"{item.title} {item.unit} {item.remark or ''} {' '.join(item.tags)}"
            if not all(attr in haystack for attr in constraints.attributes):
                return False
        return True

    filtered = [item for item in inventory if within_constraints(item)]
    if not constraints.keyword:
        return filtered[:8]
    ranked = vector_store.search(constraints.keyword, filtered)
    return (ranked or filtered)[:8]

SEARCH_CONSTRAINTS_PROMPT = """你是家庭库存搜索约束提取器。请从用户话语中提取搜索条件。

只返回一个 JSON 对象，字段必须符合以下定义：
- keyword: 真正要搜索的具体物品名；如果用户只问类别，必须留空字符串
- location_hint: 原文中的位置描述，例如“冰箱冷藏层”“柜子”；没有则为空字符串
- category: food、beverage、medicine、electronics、cosmetics、book、other 之一；无法判断则为空字符串
- temperature_zone: cold、frozen、room、any 之一
- attributes: 其他必须满足的属性，例如“盘装”“大瓶”“快过期”
- exclude: 用户明确要求排除的物品名称；没有则为空数组

不要放宽用户明确提出的位置、类别和属性条件。

用户话语：{text}
"""


def _extract_search_constraints_fallback(text: str) -> SearchConstraints:
    """Deterministic fallback used when the configured model cannot extract constraints."""
    location = next(
        (term for term in ("冷藏层", "冷冻层", "冰箱上层", "冰箱下层", "冰箱中层", "柜子") if term in text),
        "",
    )
    temperature = "any"
    if "冷藏" in text:
        temperature = "cold"
    elif "冷冻" in text:
        temperature = "frozen"

    category = ""
    keyword = ""
    if "饮料" in text:
        category = "beverage"
    elif "生鲜" in text:
        category = "food"

    attributes = [attribute for attribute in ("盘装",) if attribute in text]
    return SearchConstraints(
        keyword=keyword,
        location_hint=location,
        category=category,
        temperature_zone=temperature,
        attributes=attributes,
    )


def extract_search_constraints(text: str) -> SearchConstraints:
    """Use the configured LLM first, with deterministic parsing as a safe fallback."""
    if not llm_service.enabled:
        return _extract_search_constraints_fallback(text)

    raw = ""
    payload: object = {}
    try:
        raw = llm_service.extract_raw_json(
            [{"role": "user", "content": SEARCH_CONSTRAINTS_PROMPT.format(text=text)}],
            response_format={"type": "json_object"},
        )
        payload = json.loads(raw)
        constraints = SearchConstraints.model_validate(payload)
    except json.JSONDecodeError:
        logger.warning("LLM returned non-JSON search constraints: %.100s", raw)
        return _extract_search_constraints_fallback(text)
    except ValidationError as exc:
        logger.warning("LLM search constraint schema mismatch: %s", exc)
        return _extract_search_constraints_fallback(text)
    except Exception:
        logger.exception("Unexpected LLM search constraint extraction error; using fallback")
        return _extract_search_constraints_fallback(text)

    if constraints.temperature_zone not in {"cold", "frozen", "room", "any"}:
        constraints.temperature_zone = "any"
    if constraints.category not in VALID_SEARCH_CATEGORIES:
        constraints.category = ""
    if constraints.category == "beverage" and constraints.keyword in {"饮料", "饮品", "beverage"}:
        constraints.keyword = ""
    return constraints


def _match_items_3tier(inventory: list[Item], target: str | None) -> list[Item]:
    """3-tier matching: exact → substring → spatial path → location/space fallback."""
    if not target:
        return []
    exact = [item for item in inventory if item.title == target]
    if exact:
        return exact
    partial = [
        item for item in inventory
        if (len(target) >= MIN_PARTIAL_MATCH_LENGTH and target in item.title)
        or (len(item.title) >= MIN_PARTIAL_MATCH_LENGTH and item.title in target)
    ]
    if partial:
        partial.sort(key=lambda item: (target not in item.title, -len(item.title)))
        return partial
    slot_ids = spatial_service.resolve_location_to_slots(target)
    if slot_ids:
        results = [item for item in inventory if item.belongsToSlotId in slot_ids]
        if results:
            return results
    return [item for item in inventory if target in item.location or target in item.spaceName]


def _build_candidate_entries(candidates: list[Item]) -> list[dict]:
    entries = []
    for item in candidates:
        entries.append({
            "id": item.id, "title": item.title, "spaceName": item.spaceName,
            "location": item.location, "count": item.count, "unit": item.unit,
            "remainingPct": item.remainingPct, "consumeAll": False,
            "expire_date": item.expireDate or "",
            "expire_days": _calc_expire_days(item),
        })
    return entries


def _build_candidate_lines(candidates: list[Item], target: str | None = None) -> list[str]:
    noun = target or "物品"
    lines = [f"找到 {len(candidates)} 个匹配的「{noun}」，请回复序号选择（支持多选，如「1,2」「全部」）："]
    for i, item in enumerate(candidates, 1):
        unit_part = f"{item.count}{item.unit}" if item.count else ""
        days = _calc_expire_days(item)
        if days is not None:
            expire_str = f"{item.expireDate}到期（剩余{days}天"
            warning_days = EXPIRE_WARNING_DAYS.get(item.category, EXPIRE_WARNING_DAYS["default"])
            if days <= warning_days:
                expire_str += " ⚠️即将过期"
            expire_str += "）"
        else:
            expire_str = "无过期信息"
        lines.append(f"{i}. {item.title} — {item.spaceName}/{item.location} ({unit_part}，{expire_str})")
    return lines


def _build_context_item(item: Item) -> dict:
    return {"id": item.id, "title": item.title, "location": item.location,
            "spaceName": item.spaceName, "count": item.count, "unit": item.unit}


def _calc_expire_days(item: Item) -> int | None:
    if not item.expireDate:
        return None
    try:
        expiry = datetime.strptime(item.expireDate, "%Y-%m-%d").date()
        delta = (expiry - date.today()).days
        return delta
    except (ValueError, TypeError):
        return None


def _build_multi_consume_allocation(selected_items: list[dict], total_deduct: int | None) -> dict[str, int]:
    sorted_items = sorted(
        selected_items,
        key=lambda item: (
            item.get("expire_days") if item.get("expire_days") is not None else NO_EXPIRE_SORT_KEY,
            -item.get("count", 0),
        ),
    )
    allocation: dict[str, int] = {}
    remaining = total_deduct
    for item in sorted_items:
        item_id = item.get("id")
        count = item.get("count", 0)
        if not item_id:
            continue
        if remaining is not None:
            deduct = min(remaining, count)
            remaining -= deduct
            if deduct > 0:
                allocation[item_id] = deduct
        else:
            if count > 0:
                allocation[item_id] = 1
    return allocation


def _build_multi_consume_reply(selected_items: list[dict], allocation: dict[str, int]) -> str:
    parts = []
    unit_totals: dict[str, int] = {}
    for item in selected_items:
        item_id = item.get("id")
        title = item.get("title", "?")
        count = item.get("count", 0)
        unit = item.get("unit", "个")
        location = item.get("location", "?")
        space = item.get("spaceName", "")
        deduct = allocation.get(item_id, 0)
        if deduct > 0:
            unit_totals[unit] = unit_totals.get(unit, 0) + deduct
            if deduct >= count:
                parts.append(f"{space}/{location}的「{title}」：消耗{deduct}{unit}，已用完")
            else:
                new_count = count - deduct
                parts.append(f"{space}/{location}的「{title}」：消耗{deduct}{unit}，剩余{new_count}{unit}")
        else:
            parts.append(f"{space}/{location}的「{title}」：未操作（剩余{count}{unit}）")
    if unit_totals:
        summary = "、".join(f"{total}{unit}" for unit, total in unit_totals.items())
        parts.append(f"总共消耗{summary}")
    return "\n".join(parts)


def _build_multi_remove_reply(selected_items: list[dict]) -> str:
    locations = []
    for item in selected_items:
        loc = item.get("location", "?")
        space = item.get("spaceName", "")
        title = item.get("title", "?")
        locations.append(f"{space}/{loc}的「{title}」")
    return f"已移除 {len(selected_items)} 个位置的物品：{'、'.join(locations)}"


def _build_multi_update_reply(selected_items: list[dict], op_type: str, patch: dict) -> str:
    titles = [item.get("title", "?") for item in selected_items]
    if op_type == "update_location":
        loc = patch.get("location", "")
        return f"已将 {len(selected_items)} 件物品移动到{loc}：{'、'.join(titles)}"
    return f"已更新 {len(selected_items)} 件物品：{'、'.join(titles)}"

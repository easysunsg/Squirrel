"""Squirrel 库存助手的 LangGraph 工作流。

架构说明：
- 当前拓扑由输入、控制、规划、执行、校验、恢复和输出等节点组成
- 保留 run_squirrel_graph 签名不变，外部使用者（ai.py / test_graph.py）无需改动
- 内部使用 ExtendedGraphState 流转，输出前通过 extended_to_old_dict 适配回旧格式
- 所有路径收敛到 post_process，消灭直通 END 的叶子节点
"""

import logging
from datetime import date, datetime
from typing import Any, Dict, List, Literal, Optional
from uuid import uuid4

from app.db.sqlite import get_active_snapshot, save_snapshot, save_checkpoint, get_checkpoint
from app.models.schemas import ChatOperation, ChatResult, Item, RecipeRequest
from app.models.state import (
    ActionStatus,
    AgentAction,
    ExtendedGraphState,
    PendingOperation,
    UserContext,
    EventType, SystemEvent, generate_idempotency_key, mutation_log_to_event,
    merge_audit_logs,
    version_conflict_check,
)
from app.services.planner import plan_actions
from app.services.capabilities import CapabilityRegistry
from app.services.idempotency import idempotency_service
from app.services.event_bus import event_bus
from app.services.cache import get_recipe_cache, set_recipe_cache
from app.services.llm import llm_service
from app.services.markdown import item_status
from app.services.parser import (
    build_chat_result,
    days_from_now,
    extract_expire_patch,
    extract_location_update,
    extract_target_title,
    extract_remaining_patch,
    extract_search_keyword,
    infer_search_terms,
    parse_lightning_text,
    parse_multi_selection,
)
from app.services.spatial_service import spatial_service
from app.services.vector_store import vector_store

logger = logging.getLogger(__name__)

# ==============================
# 共享工具函数（移植自旧图）
# ==============================


def summarize_titles(items: list[Item], limit: int = 6) -> str:
    return "、".join(item.title for item in items[:limit])


def _is_pronoun_or_garbage_target(target: str) -> bool:
    """检测 LLM 提取的 target 是否为代词或垃圾短语，需回退到上下文。"""
    import re as re_mod
    pronouns = {"这个", "那个", "这些", "那些", "它", "它们", "这东西", "那东西",
                "这些东西", "那些东西", "这", "那", "该物品", "刚才说的", "上回说的"}
    if target in pronouns:
        return True
    # 以常见中文代词开头的短语 → 也是指代
    if any(target.startswith(p) for p in ("这个", "那个", "这些", "那些", "它", "它们", "这东西", "那东西", "该物品")):
        return True
    # 包含"处理过的/已处理的/吃过的/用过的"等说明性后缀 → 用户是在解释原因
    if re_mod.search(r"已?[处理吃用]\s*过\s*的", target):
        return True
    # 纯说明性短语 / 垃圾值——以动词/形容词开头且长度超过 3 个字
    garbage_prefixes = ("已处理", "处理过", "吃过", "用过", "刚刚", "刚才", "那个", "已经")
    if any(target.startswith(p) for p in garbage_prefixes) and len(target) > 3:
        return True
    return False


def match_search_items(
    text: str,
    inventory: list[Item],
    exclude_item_id: str | None = None,
    exclude_title: str | None = None,
) -> list[Item]:
    location_terms = [term for term in ("冷藏层", "冷冻层", "冰箱上层", "冰箱下层", "冰箱中层") if term in text]
    requires_food = any(term in text for term in ("生鲜", "食材", "食品", "水果", "蔬菜"))
    requires_plated = "盘装" in text

    def within_constraints(item: Item) -> bool:
        if exclude_item_id and item.id == exclude_item_id:
            return False
        if exclude_title and item.title == exclude_title:
            return False
        if location_terms and not any(term in item.location for term in location_terms):
            return False
        if requires_food and item.category != "food":
            return False
        plated_haystack = " ".join([item.title, item.unit, item.remark or "", *item.tags])
        if requires_plated and "盘" not in plated_haystack:
            return False
        return True

    query = extract_search_keyword(text)
    constrained_inventory = [item for item in inventory if within_constraints(item)]
    results = vector_store.search(query, constrained_inventory)
    if results:
        return [item for item in results if within_constraints(item)][:8]
    terms = infer_search_terms(text)
    if not terms:
        return constrained_inventory[:8]
    matched: list[Item] = []
    for item in constrained_inventory:
        haystacks = [item.title, item.location, item.spaceName, item.remark or ""]
        if any(term and any(term in value for value in haystacks) for term in terms):
            matched.append(item)
    if not matched and (location_terms or requires_food):
        return constrained_inventory[:8]
    return matched[:8]


def _match_items_3tier(inventory: list[Item], target: str | None) -> list[Item]:
    """3-tier matching: exact → substring → spatial path → location/space fallback."""
    if not target:
        return []
    exact = [item for item in inventory if item.title == target]
    if exact:
        return exact
    partial = [item for item in inventory if target in item.title or item.title in target]
    if partial:
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
            if days <= 3:
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
            item.get("expire_days") if item.get("expire_days") is not None else 9999,
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
    total_deducted = 0
    unit_str = "个"
    for item in selected_items:
        item_id = item.get("id")
        title = item.get("title", "?")
        count = item.get("count", 0)
        unit = item.get("unit", "个")
        location = item.get("location", "?")
        space = item.get("spaceName", "")
        deduct = allocation.get(item_id, 0)
        unit_str = unit
        if deduct > 0:
            total_deducted += deduct
            if deduct >= count:
                parts.append(f"{space}/{location}的「{title}」：消耗{deduct}{unit}，已用完")
            else:
                new_count = count - deduct
                parts.append(f"{space}/{location}的「{title}」：消耗{deduct}{unit}，剩余{new_count}{unit}")
        else:
            parts.append(f"{space}/{location}的「{title}」：未操作（剩余{count}{unit}）")
    if total_deducted > 0:
        parts.append(f"总共消耗{total_deducted}{unit_str}")
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



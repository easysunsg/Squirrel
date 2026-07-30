import json
import logging
import re
from datetime import date, timedelta
from typing import Literal, Optional

from app.core.constants import (
    DEFAULT_REMAINING_PCT,
    TAG_LOW_THRESHOLD,
    TAG_URGENT_THRESHOLD,
    VALID_INVENTORY_CATEGORIES,
    VALID_ITEM_ICONS,
)
from app.models.extraction import BatchAddExtraction, IntentExtractionResult
from app.models.schemas import ChatOperation, ChatResult, InventoryCategory, Item

logger = logging.getLogger(__name__)


CATEGORY_KEYWORDS = {
    "蔬菜": ["菜", "生菜", "菠菜", "青菜", "油麦菜", "西红柿", "黄瓜", "土豆"],
    "水果": ["果", "香蕉", "苹果", "橘子", "西瓜", "葡萄"],
    "药品": ["药", "感冒", "维C", "维生素", "止痛", "胶囊"],
    "洗浴": ["沐浴", "洗澡", "洗发", "香皂", "洁面"],
}


def days_from_now(days: int) -> str:
    return (date.today() + timedelta(days=days)).isoformat()


def guess_space(text: str) -> tuple[str, str]:
    if re.search(r"冰箱|冷藏|冷冻|厨房|灶台", text):
        return "kitchen", "主厨房"
    if re.search(r"车库|工具|螺丝|扳手|锤", text):
        return "garage", "车库工具"
    if re.search(r"储藏|客厅|箱|柜|药|卫生间|镜柜", text):
        return "storage", "储藏间"
    return "kitchen", "主厨房"


def guess_category(title: str) -> InventoryCategory:
    """Conservative category fallback used only when extraction omitted a category."""
    cosmetics_terms = (
        "洗面奶", "沐浴露", "洗发水", "洁面", "香皂", "牙膏", "牙刷",
        "护肤", "化妆品", "精华液", "防晒", "面膜", "乳液", "洗手液",
    )
    medicine_terms = (
        "感冒药", "维生素", "维C", "消炎药", "止痛药", "胶囊", "药片",
        "创可贴", "碘伏", "酒精棉", "眼药水", "退烧药",
    )
    food_terms = (
        "鸡蛋", "牛奶", "酸奶", "猪肉", "牛肉", "鸡肉", "蔬菜", "水果",
        "面包", "吐司", "大米", "面条", "饮料", "果汁", "啤酒", "红酒",
        "白酒", "咖啡", "茶叶", "豆腐", "酱油", "食醋", "食用油", "橄榄油",
        "白糖", "面粉", "调料", "草莓", "香蕉", "苹果", "葡萄", "西瓜", "橘子", "油麦菜",
    )
    if any(term in title for term in cosmetics_terms):
        return "cosmetics"
    if any(term in title for term in medicine_terms):
        return "medicine"
    if any(term in title for term in food_terms):
        return "food"
    if any(term in title for term in ("书籍", "杂志", "字典", "笔记本")):
        return "book"
    if any(term in title for term in ("充电器", "电池", "数据线", "适配器", "台灯", "插头")):
        return "electronics"
    return "other"


def guess_icon(title: str, space_name: str) -> str:
    if space_name == "车库工具":
        return "construction"
    if re.search(r"药|维|感冒", title):
        return "medication"
    if re.search(r"面包|吐司|蛋", title):
        return "bakery_dining"
    if re.search(r"咖啡", title):
        return "local_cafe"
    if re.search(r"奶|牛奶|酸奶", title):
        return "local_drink"
    if re.search(r"肉|鸡肉|猪肉|牛肉", title):
        return "restaurant"
    if re.search(r"蔬|菜|果|水果|苹果|香蕉", title):
        return "spa"
    if re.search(r"洗洁|沐浴|清洁", title):
        return "cleaning_services"
    if re.search(r"水|饮料|果汁|酒|茶", title):
        return "water_drop"
    if re.search(r"米|面|粉|粮|螺蛳粉", title):
        return "grain"
    return "package_2"


def guess_expire_date(title: str, category: str | None = None) -> str | None:
    """Return a date only for a very small set of high-confidence fresh foods."""
    if re.search(r"鲜奶|鲜牛奶|生牛奶", title):
        return days_from_now(7)
    if re.search(r"绿叶菜|生菜|菠菜|青菜", title):
        return days_from_now(3)
    return None


def normalize_tag(remaining: int) -> str:
    if remaining < TAG_URGENT_THRESHOLD:
        return "告急"
    if remaining < TAG_LOW_THRESHOLD:
        return "较低"
    return "充足"


CHINESE_NUMERALS: dict[str, int] = {
    "一": 1, "二": 2, "两": 2, "三": 3, "四": 4,
    "五": 5, "六": 6, "七": 7, "八": 8, "九": 9,
}


def chinese_numeral_to_int(text: str) -> tuple[int, str] | None:
    """Convert a Chinese numeral prefix to an integer and return the remaining text.

    Supports single digits (一~九, 两) and compound forms (十~十九, 二十~九十).
    Returns (count, remainder) or None if no Chinese numeral is found.
    """
    if not text or text[0] not in CHINESE_NUMERALS and text[0] != "十":
        return None

    count = 0

    # Two-character compound: 二十, 三十, ..., 九十
    if len(text) >= 2 and text[0] in {"二", "三", "四", "五", "六", "七", "八", "九"} and text[1] == "十":
        tens = CHINESE_NUMERALS[text[0]]
        count = tens * 10
        text = text[2:]
        # Optional trailing digit: 二十一, 三十二, etc.
        if text and text[0] in CHINESE_NUMERALS:
            count += CHINESE_NUMERALS[text[0]]
            text = text[1:]
        return count, text

    # 十 ~ 十九
    if text[0] == "十":
        count = 10
        text = text[1:]
        if text and text[0] in CHINESE_NUMERALS:
            count += CHINESE_NUMERALS[text[0]]
            text = text[1:]
        return count, text

    # Single digit
    if text[0] in CHINESE_NUMERALS:
        count = CHINESE_NUMERALS[text[0]]
        text = text[1:]
        return count, text

    return None


def extract_target_title(text: str) -> str | None:
    cleaned = text.strip(" ，,。！？?；;")
    patterns = [
        r"把(.+?)(?:吃完|用完|扔掉|扔了|打碎|摔碎|坏了|喝了一半|用了\d+个|用了\d+瓶|用了|换到|移到|挪到|放到|放进|放在|搁到|搁在|塞进|摆到|摆在)",
        r"(.+?)(?:吃完了|用完了|扔掉了|打碎了|摔碎了|坏了，?扔掉|坏了|喝了一半|用了\d+个|用了\d+瓶|用了|换到|移到|挪到|放到|放进|放在|搁到|搁在|塞进|摆到|摆在)",
        r"(.+?)保质期(?:再)?延\s*(\d+)\s*天",
        r"(.+?)(?:的)?保质期(?:一般是|是|为)\s*\d+\s*天",
        r"(.+?)(?:洗|准备吃|下午吃)\s*(?:一盒|一份|一个|一些)?",
    ]
    for pattern in patterns:
        match = re.search(pattern, cleaned)
        if match:
            title = match.group(1).strip(" 把刚才我今天将，,。")
            title = re.sub(r"^(?:知道了[，,]?|好的[，,]?|那就)", "", title).strip()
            title = re.sub(
                r"^(?:刚买的|买的|刚入库的|新买的)?(?:那|这)?(?:一)?(?:瓶|盒|袋|包|个|件)",
                "",
                title,
            ).strip()
            return title or None
    return None


def extract_location_update(text: str) -> str | None:
    match = re.search(r"(?:换到|移到|挪到|放到|放进|放在|搁到|搁在|塞进|摆到|摆在)(.+)$", text)
    if not match:
        return None
    return match.group(1).strip(" ，,。里中") or None


def extract_expire_patch(text: str) -> dict[str, str] | None:
    days_match = re.search(r"保质期(?:再)?延\s*(\d+)\s*天", text)
    if days_match:
        return {"expireDate": days_from_now(int(days_match.group(1)))}
    duration_match = re.search(r"保质期(?:一般是|是|为)\s*(\d+)\s*天", text)
    if duration_match:
        return {"expireDate": days_from_now(int(duration_match.group(1)))}
    date_match = re.search(r"(?:到期|保质期)(?:改到|改成|设为)?\s*(\d{4}-\d{2}-\d{2})", text)
    if date_match:
        return {"expireDate": date_match.group(1)}
    if "明天过期" in text:
        return {"expireDate": days_from_now(1)}
    return None


def extract_remaining_patch(text: str, item: Item | None = None) -> dict[str, int] | None:
    if re.search(r"吃完|用完", text):
        return {"remainingPct": 0, "count": 0}
    if re.search(r"一半|半", text):
        count = max(0, (item.count // 2) if item else 0)
        return {"remainingPct": 50, "count": count}
    percent_match = re.search(r"还剩\s*(\d{1,3})%", text)
    if percent_match:
        remaining = max(0, min(100, int(percent_match.group(1))))
        return {"remainingPct": remaining}
    count_match = re.search(r"用了\s*(\d+)\s*(个|瓶|袋|盒|包|件|把|颗)?", text)
    if count_match and item:
        used = int(count_match.group(1))
        remaining_count = max(0, item.count - used)
        remaining_pct = 0 if item.count <= 0 else max(0, round(remaining_count / item.count * 100))
        return {"count": remaining_count, "remainingPct": remaining_pct}
    return None


def is_query_total(text: str) -> bool:
    """检测是否为库存总量查询意图（最高优先级）。

    触发词：多少、总数、一共、合计、存量、清点、统计、有几瓶、有几个、全部库存
    语义特征：用户仅询问物品数量、分布，无任何修改物品存放位置/消耗/新增的动作动词
    """
    QUERY_TOTAL_KEYWORDS = [
        "一共有", "总共有", "全部有多少", "全部几个", "总存量",
        "清点库存", "清点一下", "统计库存", "统计一下",
        "合计多少", "库存总数", "一共多少", "总共多少",
    ]
    for kw in QUERY_TOTAL_KEYWORDS:
        if kw in text:
            return True

    # "清点/统计/盘点" + "库存/物品" 组合
    if re.search(r"(清点|统计|盘点)", text) and re.search(r"(库存|物品|全部|所有)", text):
        return True

    return False


def grouped_inventory_summary(items: list) -> str:
    """按存放空间+位置分组汇总库存统计文案。"""
    from collections import defaultdict

    groups: dict[tuple[str, str], list] = defaultdict(list)
    for item in items:
        key = (item.spaceName or "未分类", item.location or "默认层架")
        groups[key].append(item)

    sorted_keys = sorted(groups.keys(), key=lambda k: (k[0], k[1]))

    lines = ["【松鼠库存统计汇总】"]
    total_by_unit: dict[str, int] = {}

    for idx, (space, loc) in enumerate(sorted_keys, 1):
        group_items = groups[(space, loc)]
        group_items.sort(key=lambda it: it.title)

        item_parts = []
        group_by_unit: dict[str, int] = {}

        for item in group_items:
            count = item.count or 1
            unit = item.unit or "个"
            group_by_unit[unit] = group_by_unit.get(unit, 0) + count
            total_by_unit[unit] = total_by_unit.get(unit, 0) + count
            item_parts.append(f"{item.title}×{count}{unit}")

        items_str = "、".join(item_parts)
        subtotal = "、".join(f"{count}{unit}" for unit, count in group_by_unit.items())
        lines.append(f"{idx}. {space}/{loc}：{items_str} → 小计{subtotal}")

    total_summary = "、".join(f"{count}{unit}" for unit, count in total_by_unit.items()) or "0个"
    lines.append(f"✅ 全部库存总存量：{total_summary}")
    lines.append("")
    lines.append("如需调整物品存放位置/消耗，可以告诉我目标操作。")

    return "\n".join(lines)


def parse_multi_selection(text: str, max_index: int) -> list[int] | Literal["all", "cancel"] | None:
    """Parse user input in item selection mode to determine which items are selected.

    All-rule-based implementation for 100% accuracy. Never calls LLM.

    Args:
        text: Raw user input.
        max_index: Number of available candidates (1-based max).

    Returns:
        list[int]: 0-based valid indices (caller must validate range).
        "all":     User wants all items (全部/所有/全选/都要).
        "cancel":  User wants to cancel (取消/退出/不选了).
        None:      Unparseable input.

    Supported formats:
        - Single: "3" -> [2]
        - Comma/space: "1,3,5" / "1 3 5" -> [0,2,4]
        - Chinese comma: "1、3、5" -> [0,2,4]
        - Range: "1-3" / "1~3" / "1到3" -> [0,1,2]
        - Mixed: "1-3,5,7-9" -> [0,1,2,4,6,7,8]
        - Chinese: "1和3" / "第1个和第3个" -> [0,2]
        - Chinese numerals: "一,三" -> [0,2]
    """
    t = text.strip()
    if not t:
        return None

    # === Cancel keywords ===
    if t in ("取消", "退出", "不选了"):
        return "cancel"

    # === All-keywords ===
    if t in ("全部", "所有", "全选", "都要"):
        return "all"

    # === Normalize Chinese punctuation ===
    t = t.replace("、", ",")
    t = t.replace("和", ",")
    t = t.replace("~", "-")
    # 到 -> range separator (but only between digits: "1到3")
    t = re.sub(r"(\d)\s*到\s*(\d)", r"\1-\2", t)

    # Strip ordinal markers: 第1个, 第3个 -> 1, 3
    t = re.sub(r"第(\d+)个", r"\1", t)

    # Replace Chinese numerals (一~九) with Arabic digits
    for cn, ar in CHINESE_NUMERALS.items():
        t = t.replace(cn, str(ar))
    t = re.sub(r"\s+", "", t)  # remove all whitespace after numeral replacement

    # Split by comma
    segments = [s.strip() for s in t.split(",") if s.strip()]
    indices: set[int] = set()

    for seg in segments:
        # Range: X-Y
        range_match = re.match(r"^(\d+)\s*-\s*(\d+)$", seg)
        if range_match:
            start, end = int(range_match.group(1)), int(range_match.group(2))
            for i in range(start, end + 1):
                indices.add(i - 1)  # convert to 0-based
            continue
        # Single number
        num_match = re.match(r"^(\d+)$", seg)
        if num_match:
            indices.add(int(num_match.group(1)) - 1)  # 0-based
            continue
        # Unparseable segment -> skip

    if not indices:
        return None

    return sorted(indices)


def extract_search_keyword(text: str) -> str:
    cleaned = re.sub(r"我家里|家里|还有什么|有什么|我的|放在哪了|放哪了|在哪|哪里|念一遍", "", text)
    return cleaned.strip(" ，,。！？?；;") or text.strip()


def infer_search_terms(text: str) -> list[str]:
    for label, keywords in CATEGORY_KEYWORDS.items():
        if label in text:
            return keywords
    keyword = extract_search_keyword(text)
    return [keyword] if keyword else []


def parse_lightning_text(text: str) -> list[Item]:
    # Remove conversational purchase context once, then parse each comma-delimited clause.
    item_text = re.sub(r"^.*?(?:买了|购入|新增|存入|录入|添加)了?", "", text, count=1).strip() or text
    clauses = [part.strip() for part in re.split(r"[，,；;]", item_text) if part.strip()]

    global_location = ""
    item_clauses: list[tuple[str, str]] = []
    for clause in clauses:
        global_match = re.match(r"^(?:都)?(?:放|搁|塞|存|摆|丢进)(?:在|进|到)?了?(.+?)(?:里|中)?[了吧呢]?$", clause)
        if global_match:
            global_location = global_match.group(1).strip(" ，,。")
            continue

        location_match = re.match(r"^(.+?)\s*(?:放|搁|塞|存|摆|丢进)(?:在|进|到)?了?(.+?)(?:里|中)?[了吧呢]?$", clause)
        if location_match:
            item_clauses.append((location_match.group(1).strip(), location_match.group(2).strip(" ，,。")))
        else:
            item_clauses.append((clause, ""))

    parts: list[tuple[str, str]] = []
    for clause, clause_location in item_clauses:
        for part in re.split(r"[、和]", clause):
            if part.strip():
                parts.append((part.strip(), clause_location or global_location or "默认层架"))

    remaining = DEFAULT_REMAINING_PCT

    items: list[Item] = []
    for part, location in parts:
        space_id, space_name = guess_space(location)
        unit_pattern = r"(袋|瓶|盒|个|件|包|罐|本|条|把|颗|斤|克|g|kg)"
        match = re.match(rf"^(\d+)\s*{unit_pattern}?\s*(.+)$", part, re.I)

        if match:
            count = int(match.group(1))
            unit = match.group(2) if match.group(2) else ("件" if space_name == "车库工具" else "个")
            title = match.group(3).strip()
        else:
            # Try Chinese numeral prefix: "两盒牛奶", "五袋大米"
            cn_result = chinese_numeral_to_int(part)
            if cn_result:
                count, remainder = cn_result
                unit_match = re.match(rf"^\s*{unit_pattern}?\s*(.+)$", remainder, re.I)
                unit = unit_match.group(1) if unit_match and unit_match.group(1) else ("件" if space_name == "车库工具" else "个")
                title = unit_match.group(2).strip() if unit_match and unit_match.group(2) else remainder.strip()
            else:
                count = 1
                unit = "件" if space_name == "车库工具" else "个"
                title = part.strip()

        # Remove trailing location/noise after punctuation
        title = re.sub(r"[，,。．、]+.*$", "", title).strip()
        if not title:
            title = part.strip()
        tag = normalize_tag(remaining)
        category = guess_category(title)
        items.append(
            Item(
                title=title,
                category=category,
                spaceId=space_id,
                spaceName=space_name,
                location=location,
                remainingPct=remaining,
                expireDate=guess_expire_date(title, category),
                tag=tag,
                count=count,
                unit=unit,
                icon=guess_icon(title, space_name),
                remark=f"由自然语言解析：“{text}”。",
            )
        )
    return items


BATCH_ADD_PROMPT = """你是家庭库存批量入库信息提取器。把用户话语中的每件物品分别提取出来。

只返回 JSON：
{{
  "items": [
    {{"title": "物品核心名称", "count": 1, "unit": "个", "location": "该物品的位置",
      "category": "food|medicine|electronics|cosmetics|book|other 或空字符串",
      "space_hint": "用户明确提到的空间名称或空字符串",
      "expire_hint": "YYYY-MM-DD、+Nd、+N天或空字符串",
      "icon_hint": "合法图标名或空字符串"}}
  ],
  "confidence": 0.0
}}

规则：
- 一句话有多件物品时，items 必须有多条，每件物品绑定自己的数量、单位和位置。
- “刚去超市”“大采购回来”“买了”等是场景或动作，不是物品名。
- location 只能包含当前物品的位置，不能包含下一件物品。
- “都放冰箱”表示此前未单独指定位置的物品都在冰箱。
- 无法确定位置时 location 留空，不得继承其他物品的独立位置。
- category 只能使用给定枚举；不能确定时留空，禁止编造类别。
- expire_hint 只提取用户明确说出的日期或期限；未提及时必须留空。
- icon_hint 不能确定时留空。

示例输入：刚去超市大采购回来，买了3包吐司放面包机旁，5瓶可乐放冰箱
示例输出：{{"items":[{{"title":"吐司","count":3,"unit":"包","location":"面包机旁","category":"food","space_hint":"","expire_hint":"","icon_hint":"bakery_dining"}},{{"title":"可乐","count":5,"unit":"瓶","location":"冰箱","category":"food","space_hint":"主厨房","expire_hint":"","icon_hint":"local_drink"}}],"confidence":0.98}}

用户话语：{text}
"""


_ADD_TITLE_NOISE = ("超市", "采购", "回来", "买了", "购入", "新增", "录入", "添加")
_QUANTITY_UNIT_PATTERN = re.compile(r"(?:\d+|[一二两三四五六七八九十]+)\s*(?:袋|瓶|盒|个|件|包|罐|本|条|把|颗|斤|克|g|kg)", re.I)


def _validate_batch_add_extraction(result: BatchAddExtraction, text: str) -> bool:
    if not result.items or result.confidence < 0.6:
        return False
    expected_count = len(_QUANTITY_UNIT_PATTERN.findall(text))
    if expected_count > 1 and len(result.items) < expected_count:
        return False
    for item in result.items:
        if not item.title.strip() or any(noise in item.title for noise in _ADD_TITLE_NOISE):
            return False
        if "放" in item.location or _QUANTITY_UNIT_PATTERN.search(item.location):
            return False
        if item.category and item.category not in VALID_INVENTORY_CATEGORIES:
            return False
        if item.icon_hint and item.icon_hint not in VALID_ITEM_ICONS:
            return False
    return True


def _resolve_expire_hint(expire_hint: str) -> str | None:
    hint = expire_hint.strip()
    if not hint:
        return None
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", hint):
        try:
            date.fromisoformat(hint)
            return hint
        except ValueError:
            return None
    relative = re.fullmatch(r"\+?(\d+)\s*(?:d|天)", hint, re.I)
    if relative:
        return days_from_now(int(relative.group(1)))
    return None


def _items_from_batch_extraction(result: BatchAddExtraction, source_text: str) -> list[Item]:
    items: list[Item] = []
    for entity in result.items:
        location = entity.location.strip() or "默认层架"
        space_id, space_name = guess_space(entity.space_hint.strip() or location)
        category: InventoryCategory = (
            entity.category if entity.category in VALID_INVENTORY_CATEGORIES else guess_category(entity.title)
        )
        expire_date = _resolve_expire_hint(entity.expire_hint)
        if not expire_date:
            expire_date = guess_expire_date(entity.title, category)
        icon = entity.icon_hint if entity.icon_hint in VALID_ITEM_ICONS else guess_icon(entity.title, space_name)
        items.append(Item(
            title=entity.title.strip(),
            category=category,
            spaceId=space_id,
            spaceName=space_name,
            location=location,
            remainingPct=100,
            expireDate=expire_date,
            tag=normalize_tag(100),
            count=entity.count,
            unit=entity.unit.strip() or "个",
            icon=icon,
            remark=f"由自然语言解析：“{source_text}”。",
        ))
    return items


def parse_add_items(text: str) -> list[Item]:
    """Extract one or more add items with the LLM first and deterministic parsing as fallback."""
    try:
        from app.services.llm import llm_service

        if llm_service.enabled:
            response = llm_service.extract_raw_json(
                [{"role": "user", "content": BATCH_ADD_PROMPT.format(text=text)}],
                response_format={"type": "json_object"},
            )
            result = BatchAddExtraction.model_validate_json(response)
            if _validate_batch_add_extraction(result, text):
                return _items_from_batch_extraction(result, text)
            logger.warning("LLM batch add extraction failed validation; using rule fallback")
    except Exception:
        logger.warning("LLM batch add extraction failed; using rule fallback", exc_info=True)
    return parse_lightning_text(text)


# ---------------------------------------------------------------------------
# LLM-based intent extraction
# ---------------------------------------------------------------------------


INTENT_EXTRACT_PROMPT = """## 角色定位
你是家庭物品管理系统的专属意图识别与实体提取助手。你的唯一任务是从用户输入中精准识别用户意图、提取结构化实体参数，严格按照指定JSON格式输出结果，禁止输出任何解释、说明、markdown格式、代码块等额外内容，只输出纯JSON。

## 输出Schema（必须严格遵守，字段不可新增、不可删减、不可修改枚举值）
```json
{{
    "intent": "字符串，必填，只能从【意图枚举列表】中选择，不可自创",
    "item_name": "字符串，必填，提取到的物品核心名称，提取不到则为空字符串",
    "quantity": "整数/Null，必填，提取到的物品数量，纯数字；提取不到、数量模糊（如"一些""少许"）则为null",
    "location": "字符串，必填，提取到的存放位置，包含层级描述；提取不到则为空字符串",
    "expire_date": "字符串，必填，保质期/过期时间；绝对日期用YYYY-MM-DD格式（如2025-12-31）；相对天数用+Nd格式（如+7d表示7天后、+30d表示30天后）；提取不到则为空字符串",
    "remaining_pct": "整数/Null，必填，消耗后剩余百分比（0-100）；'吃完/用完'→0，'用了一半/吃了一半'→50，'还剩30%'→30；与消耗无关或提取不到则为null",
    "target_is_valid": "布尔值，必填；item_name 是具体物品名时为true，代词、场景描述或无效目标时为false",
    "confidence": "浮点数，必填，0-1之间的识别置信度，保留2位小数"
}}
```

## 意图枚举列表（必须严格从以下列表选择，按优先级判定）
| 意图枚举值 | 意图定义 | 核心语义特征 |
|---|---|---|
| shopping_add | 添加商品到采购/购物清单，不代表已经拥有库存 | 包含加入采购清单、加入购物清单、采购清单加上等语义；优先级高于add |
| add | 新增/购买/录入已经拥有的物品到库存 | 包含买回来、购入、存入、录入、囤货等新增库存的语义；明确提到采购清单时不得使用add |
| consume | 消耗/使用/吃掉/喝掉物品，扣减库存数量 | 包含吃完、用完、用了、吃了、吃掉、喝了、消耗、用掉等使用消耗的语义，仅扣减数量，不删除整条记录 |
| remove | 丢弃/清除/扔掉物品，删除整条库存记录 | 包含扔掉、扔了、丢弃、丢掉、清掉、删除、坏了扔掉、过期扔掉等移除整条记录的语义 |
| update_location | 修改/移动物品的存放位置 | 包含换到、移到、挪到、放到、放进、放在、挪去、移去、转移到等修改位置的语义，无新增/购买语义 |
| update_expiry | 修改物品的保质期/过期时间 | 包含修改保质期、更新过期时间、设置有效期等语义 |
| quantity_query | 查询物品的剩余数量/库存 | 包含还剩、还有几个、还有多少、有多少、几个、多少、库存多少等查询数量的语义 |
| location_query | 查询物品的存放位置 | 包含在哪、哪里、放哪、位置、放在哪、放在哪里等查询位置的语义 |
| expiry_query | 查询临期/即将过期/已过期的物品 | 包含过期、快坏、临期、告急、快过期、要过期了等查询临期物品的语义 |
| idle_query | 查询长期闲置/放了很久的物品 | 包含放了很久、很久没动、闲置、很久没用等查询闲置物品的语义 |
| recipe | 查询菜谱/做饭建议/食材搭配 | 包含吃什么、做什么、菜谱、做饭、能做什么菜等语义 |
| search_query | 模糊搜索某类/某个物品是否存在 | 包含还有什么、什么菜、有什么、有没有XX等泛化搜索的语义 |
| chat | 无关闲聊/无法识别的无效请求 | 与家庭物品管理完全无关的内容，或语义极度模糊无法识别 |

## 实体提取详细规则
1. item_name（物品名称）：提取核心物品名称，可保留必要的属性修饰词（如"常温牛奶""脱脂牛奶"视为不同物品）；用户使用代词（它、这个、那个）时留空；提取不到时留空字符串
2. quantity（数量）：只提取纯数字整数，自动转换口语化：俩=2、仨=3、一打=12、半打=6；模糊数量（一些、少许、很多）为null；未提及也为null
3. location（位置）：提取完整位置层级描述（如"冰箱中层""车库A4搁板"）；只提取目标位置，不提取来源位置；提取不到时留空
4. expire_date（保质期）：仅在update_expiry意图中提取；用户说"延长N天"→+Nd格式；用户说具体日期→YYYY-MM-DD；"明天过期"→+1d；"下周过期"→+7d；提取不到时留空字符串
5. remaining_pct（剩余百分比）：仅在consume意图中提取；"吃完/用完/吃掉了"→0；"一半/半"→50；"还剩30%"→30；与消耗无关时为null
6. target_is_valid：item_name 为“这个、那个、它、刚才说的”等指代或场景描述时必须为false；具体物品名为true

## 置信度评分标准
- 0.90~1.00：意图100%明确，物品名称、关键参数清晰无歧义
- 0.70~0.89：意图基本明确，核心物品名称清晰，少量参数模糊
- 0.50~0.69：意图有歧义，或关键实体缺失
- 0.00~0.49：完全无法识别意图，或与物品管理场景完全无关

## 歧义场景优先级判定
- 新增vs修改位置：同时出现"购买"和"位置"语义，优先判定为add，位置填入location字段
- 消耗vs删除："扔掉、丢弃"判定为remove；"吃了、用了"判定为consume
- 数量查询vs通用搜索：明确出现"多少、几个"判定为quantity_query；泛泛问"有什么"判定为search_query

## 参考示例
输入：买了两个玉米放厨房
输出：{{"intent":"add","item_name":"玉米","quantity":2,"location":"厨房","expire_date":"","remaining_pct":null,"confidence":0.95}}

输入：把牛奶换到冰箱中层
输出：{{"intent":"update_location","item_name":"牛奶","quantity":null,"location":"冰箱中层","expire_date":"","remaining_pct":null,"confidence":0.92}}

输入：我还有几个鸡蛋
输出：{{"intent":"quantity_query","item_name":"鸡蛋","quantity":null,"location":"","expire_date":"","remaining_pct":null,"confidence":0.90}}

输入：刚刚吃掉了两个
输出：{{"intent":"consume","item_name":"","quantity":2,"location":"","expire_date":"","remaining_pct":null,"confidence":0.60}}

输入：把面包吃完了
输出：{{"intent":"consume","item_name":"面包","quantity":null,"location":"","expire_date":"","remaining_pct":0,"confidence":0.92}}

输入：牛奶用了一半
输出：{{"intent":"consume","item_name":"牛奶","quantity":null,"location":"","expire_date":"","remaining_pct":50,"confidence":0.88}}

输入：土豆保质期再延7天
输出：{{"intent":"update_expiry","item_name":"土豆","quantity":null,"location":"","expire_date":"+7d","remaining_pct":null,"confidence":0.93}}

输入：鸡蛋明天过期
输出：{{"intent":"update_expiry","item_name":"鸡蛋","quantity":null,"location":"","expire_date":"+1d","remaining_pct":null,"confidence":0.85}}

输入：今天天气真好
输出：{{"intent":"chat","item_name":"","quantity":null,"location":"","expire_date":"","remaining_pct":null,"confidence":0.20}}

## 最终禁令
绝对禁止输出JSON以外的任何内容
绝对禁止自创枚举列表以外的意图值
绝对禁止编造物品名称、数量、位置，提取不到就留空/null
绝对禁止修改输出Schema的字段名、字段类型

现在处理用户输入：{user_text}"""


def extract_intent_with_llm(text: str) -> IntentExtractionResult | None:
    """Call LLM to extract intent and entities. Returns None on any failure."""
    try:
        from app.services.llm import llm_service

        if not llm_service.enabled:
            return None

        prompt = INTENT_EXTRACT_PROMPT.format(user_text=text)
        messages = [{"role": "user", "content": prompt}]

        response_text = llm_service.extract_raw_json(
            messages,
            response_format={"type": "json_object"},
        )

        result_json = json.loads(response_text)
        return IntentExtractionResult(**result_json)
    except Exception:
        logger.warning("LLM intent extraction failed, will fall back to rules", exc_info=True)
        return None


# ---------------------------------------------------------------------------
# Rule-based fallback (original logic)
# ---------------------------------------------------------------------------


def build_chat_result_by_rules(text: str) -> ChatResult:
    """Rule-based intent matching — the original deterministic fallback."""
    if any(term in text for term in ("采购清单", "购物清单", "待购清单")) and any(
        term in text for term in ("加入", "加到", "加上", "添加")
    ):
        title_match = re.search(r"把\s*(.+?)\s*(?:加入|加到|添加到)", text)
        if not title_match:
            title_match = re.search(r"(?:加上|添加)\s*[\"“]?(.+?)[\"”]?(?:。|$)", text)
        title = title_match.group(1).strip(" \"“”。，,") if title_match else ""
        list_match = re.search(r"((?:未来|周末|家庭|我们的)?(?:采购|购物|待购)清单)", text)
        list_name = list_match.group(1) if list_match else "采购清单"
        list_name = list_name.removeprefix("我们的")
        return ChatResult(
            intent="shopping_add",
            replyText=f"正在将「{title}」加入{list_name}。",
            operations=[
                ChatOperation(
                    type="add",
                    target=title or None,
                    patch={"listName": list_name, "count": 1, "unit": "个"},
                )
            ],
        )

    if any(word in text for word in ["买了", "购入", "新增", "存入", "录入", "添加"]):
        parsed = parse_add_items(text)
        if not parsed:
            return ChatResult(replyText="我没有识别出明确物品，可以换一种说法再试一次。")
        return ChatResult(
            intent="add",
            replyText=f"已识别出 {len(parsed)} 件物品，准备入库。",
            operations=[ChatOperation(type="add", item=item) for item in parsed],
        )

    if any(word in text for word in ["扔掉", "扔了", "打碎", "摔碎", "坏了", "清掉", "丢了吧", "丢了", "丢掉"]):
        target = extract_target_title(text)
        return ChatResult(
            intent="remove",
            replyText="我会尝试将对应物品移出库存。",
            operations=[ChatOperation(type="remove", target=target, removeReason="discarded")],
        )

    if any(word in text for word in ["吃完", "用完", "用了", "吃了", "吃掉", "喝了一半", "一半", "洗一盒", "洗一份", "准备吃", "下午吃"]):
        target = extract_target_title(text)
        patch = {"deductCount": 1} if re.search(r"洗一盒|洗一份|准备吃|下午吃", text) else None
        return ChatResult(
            intent="consume",
            replyText="我会尝试更新该物品的消耗情况。",
            operations=[ChatOperation(type="consume", target=target, patch=patch)],
        )

    remark_match = re.search(r"(?:把|给)?(.+?)(?:的)?备注(?:加上|补上|写上|改成|设置为)?\s*[:：]?\s*(.+)$", text)
    if remark_match:
        target = remark_match.group(1).strip(" ，,。") or None
        remark = remark_match.group(2).strip(" ，,。")
        if remark:
            return ChatResult(
                intent="update_remark",
                replyText="我会把这段内容追加到物品备注。",
                operations=[ChatOperation(type="update", target=target, patch={"remarkAppend": remark})],
            )

    if any(word in text for word in ["换到", "移到", "挪到", "放到", "放进", "放在", "搁到", "搁在", "塞进", "摆到", "摆在"]):
        target = extract_target_title(text)
        location = extract_location_update(text)
        if target and location and not any(word in text for word in ["买了", "新增", "录入", "添加"]):
            return ChatResult(
                intent="update_location",
                replyText="我会尝试更新该物品的位置。",
                operations=[ChatOperation(type="update", target=target, patch={"location": location})],
            )

    expire_patch = extract_expire_patch(text)
    if expire_patch:
        target = extract_target_title(text)
        return ChatResult(
            intent="update_expiry",
            replyText="我会尝试更新该物品的保质期。",
            operations=[ChatOperation(type="update", target=target, patch=expire_patch)],
        )

    if any(word in text for word in ["过期", "快坏", "临期", "告急"]):
        return ChatResult(intent="expiry_query", replyText="正在查询临期物品。")

    if any(word in text for word in ["在哪", "哪里", "放哪", "位置"]):
        return ChatResult(intent="location_query", replyText="正在查询物品位置。")

    # === 库存总量查询（最高优先级，在 quantity_query 之前） ===
    if is_query_total(text):
        return ChatResult(intent="query_total", replyText="正在统计全部库存。")

    if any(word in text for word in ["还剩", "还有几个", "还有多少", "有多少", "几个", "多少"]):
        return ChatResult(
            intent="quantity_query",
            replyText="正在查询物品数量。",
        )

    if any(word in text for word in ["放了很久", "很久没动", "闲置"]):
        return ChatResult(intent="idle_query", replyText="正在查询可能长期闲置的物品。")

    if any(word in text for word in ["吃什么", "做什么", "菜谱", "做饭"]):
        return ChatResult(intent="recipe", replyText="正在整理可用食材并生成建议。")

    if any(word in text for word in ["还有什么", "什么菜", "感冒药", "洗澡用", "有什么"]):
        return ChatResult(intent="search_query", replyText="正在帮你搜索相关库存。")

    return ChatResult(intent="chat", replyText="我查到当前库存了，你可以让我录入、查位置、列临期或更新物品。")


# ---------------------------------------------------------------------------
# Main entry: LLM-first with rule-based fallback
# ---------------------------------------------------------------------------

_INTENT_REPLY_MAP: dict[str, str] = {
    "add": "已识别出物品，准备入库。",
    "shopping_add": "正在加入采购清单。",
    "consume": "我会尝试更新该物品的消耗情况。",
    "remove": "我会尝试将对应物品移出库存。",
    "update_location": "我会尝试更新该物品的位置。",
    "update_expiry": "我会尝试更新该物品的保质期。",
    "quantity_query": "正在查询物品数量。",
    "query_total": "正在统计全部库存。",
    "location_query": "正在查询物品位置。",
    "expiry_query": "正在查询临期物品。",
    "idle_query": "正在查询可能长期闲置的物品。",
    "recipe": "正在整理可用食材并生成建议。",
    "search_query": "正在帮你搜索相关库存。",
    "chat": "我查到当前库存了，你可以让我录入、查位置、列临期或更新物品。",
}


def _build_operations_from_llm(result: IntentExtractionResult, text: str) -> list[ChatOperation]:
    """Build ChatOperation list from LLM extraction result.

    LLM-extracted entities are used as the primary source.
    Regex-based helpers are only used as a last resort when the LLM didn't extract the entity.
    """
    intent = result.intent
    item_name = result.item_name if result.target_is_valid else ""
    quantity = result.quantity
    location = result.location
    expire_date = result.expire_date
    remaining_pct = result.remaining_pct

    if intent == "add":
        # For add, use the full parser to get complete Item objects (handles batch "鸡蛋、香蕉、猪肉")
        parsed = parse_add_items(text)
        if parsed:
            return [ChatOperation(type="add", item=item) for item in parsed]
        # Fallback: build a minimal item from LLM-extracted entities
        if item_name:
            item = Item(
                title=item_name,
                count=quantity or 1,
                location=location or "默认层架",
            )
            return [ChatOperation(type="add", item=item)]
        return []

    if intent == "shopping_add":
        target = item_name or extract_target_title(text) or None
        list_match = re.search(r"((?:未来|周末|家庭|我们的)?(?:采购|购物|待购)清单)", text)
        list_name = list_match.group(1) if list_match else "采购清单"
        list_name = list_name.removeprefix("我们的")
        if target:
            return [
                ChatOperation(
                    type="add",
                    target=target,
                    patch={"listName": list_name, "count": quantity or 1, "unit": "个"},
                )
            ]
        return []

    if intent == "consume":
        # LLM entity first, regex fallback last
        target = item_name or extract_target_title(text) or None
        patch = None
        if remaining_pct is not None or quantity is not None:
            patch = {}
            if remaining_pct is not None:
                patch["remainingPct"] = remaining_pct
            if quantity is not None:
                patch["deductCount"] = quantity
        return [ChatOperation(type="consume", target=target or text, patch=patch)]

    if intent == "remove":
        target = item_name or extract_target_title(text) or None
        return [ChatOperation(type="remove", target=target, removeReason="discarded")]

    if intent == "update_location":
        target = item_name or extract_target_title(text) or None
        # LLM entity first, regex fallback last
        loc = location or extract_location_update(text) or None
        if target and loc:
            return [ChatOperation(type="update", target=target, patch={"location": loc})]
        # Target known but location missing → return target for follow-up question
        if target:
            return [ChatOperation(type="update", target=target)]

    if intent == "update_expiry":
        target = item_name or extract_target_title(text) or None
        patch = _build_expire_patch(expire_date, text)
        if target and patch:
            return [ChatOperation(type="update", target=target, patch=patch)]
        # Target known but expire info missing → return target for follow-up
        if target:
            return [ChatOperation(type="update", target=target)]

    if intent == "quantity_query":
        # Queries are read-only and must never be represented as consume operations.
        return []

    # expiry_query, location_query, idle_query, recipe, search_query, chat → no operations
    return []


def _build_expire_patch(expire_date: str, text: str) -> dict[str, str] | None:
    """Build expireDate patch from LLM-extracted expire_date or regex fallback.

    Supports:
    - Relative: "+7d" → 7 days from now
    - Absolute: "2025-12-31" → use directly
    - Regex fallback for legacy patterns like "保质期再延N天", "明天过期"
    """
    if expire_date:
        if expire_date.startswith("+") and expire_date.endswith("d"):
            try:
                days = int(expire_date[1:-1])
                return {"expireDate": days_from_now(days)}
            except ValueError:
                pass
        elif re.match(r"\d{4}-\d{2}-\d{2}", expire_date):
            return {"expireDate": expire_date}

    # Regex fallback for patterns the LLM might not have structured
    return extract_expire_patch(text)


def build_chat_result(text: str) -> ChatResult:
    """Build ChatResult using LLM intent extraction with rule-based fallback.

    Flow:
    1. Call LLM to extract intent + entities.
    2. If LLM succeeds with confidence >= 0.6, build result from LLM output.
    3. If confidence is between 0.5-0.6, could prompt for confirmation (future).
    4. If LLM fails or confidence < 0.5, fall back to rule-based matching.
    """
    # Step 1: Try LLM extraction
    llm_result = extract_intent_with_llm(text)

    # Step 2: High confidence → use LLM result directly
    if llm_result and llm_result.confidence >= 0.6:
        intent = llm_result.intent
        reply_text = _INTENT_REPLY_MAP.get(intent, "操作已接收")
        operations = _build_operations_from_llm(llm_result, text)

        # For add intent, override reply with actual parsed count
        if intent == "add" and operations:
            reply_text = f"已识别出 {len(operations)} 件物品，准备入库。"
        elif intent == "add" and not operations:
            reply_text = "我没有识别出明确物品，可以换一种说法再试一次。"

        logger.info(
            "LLM intent extraction succeeded: intent=%s confidence=%.2f item=%r",
            intent,
            llm_result.confidence,
            llm_result.item_name,
        )
        return ChatResult(
            intent=intent,
            replyText=reply_text,
            operations=operations,
        )

    # Step 3: Medium confidence (0.5-0.6) — still use LLM but log a warning
    if llm_result and 0.5 <= llm_result.confidence < 0.6:
        intent = llm_result.intent
        reply_text = _INTENT_REPLY_MAP.get(intent, "操作已接收")
        operations = _build_operations_from_llm(llm_result, text)

        if intent == "add" and operations:
            reply_text = f"已识别出 {len(operations)} 件物品，准备入库。"
        elif intent == "add" and not operations:
            reply_text = "我没有识别出明确物品，可以换一种说法再试一次。"

        logger.info(
            "LLM intent extraction with medium confidence: intent=%s confidence=%.2f",
            intent,
            llm_result.confidence,
        )
        return ChatResult(
            intent=intent,
            replyText=reply_text,
            operations=operations,
        )

    # Step 4: Low confidence or LLM failure → fall back to rules
    logger.info("Falling back to rule-based intent matching for text=%r", text)
    return build_chat_result_by_rules(text)

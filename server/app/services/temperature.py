# app/services/temperature.py

import logging
from typing import Optional

from app.models.schemas import Item
from app.services.spatial_service import spatial_service

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────
# 温区配置（集中管理，可迁移到 YAML / DB）
# ──────────────────────────────────────────────

# 标准温区枚举
ZONE_COLD = "cold"        # 冷藏 0~8°C
ZONE_FROZEN = "frozen"    # 冷冻 <0°C
ZONE_ROOM = "room"        # 常温
ZONE_ANY = "any"          # 不限

# 各温区的位置关键词（执行层匹配，非理解层）
# 注意：这里只放"标准词"，同义词归一化由 LLM / 本体层完成
_ZONE_LOCATION_KEYWORDS: dict[str, list[str]] = {
    ZONE_COLD: [
        "冷藏", "保鲜", "蔬果层", "蔬果抽屉",
        "冰箱中层", "冰箱下层", "cooling", "fridge",
    ],
    ZONE_FROZEN: [
        "冷冻", "急冻", "冰柜", "冻层",
        "冰箱上层", "freezer", "frozen",
    ],
    ZONE_ROOM: [
        "常温", "储物柜", "橱柜", "台面", "货架",
        "pantry", "shelf", "counter", "room",
    ],
}

# 显式标签映射（用户在 item.tags 中打的标签）
_ZONE_TAG_MAP: dict[str, str] = {
    "冷藏": ZONE_COLD,
    "cold": ZONE_COLD,
    "冷冻": ZONE_FROZEN,
    "frozen": ZONE_FROZEN,
    "常温": ZONE_ROOM,
    "room": ZONE_ROOM,
}


# ──────────────────────────────────────────────
# 核心函数
# ──────────────────────────────────────────────

def _check_temperature_zone(item: Item, zone: str) -> bool:
    """
    判断 item 是否属于指定温区。

    Parameters
    ----------
    item : Item
        库存物品，包含 location / spaceName / tags / remark 等字段。
    zone : str
        归一化后的温区标识：cold / frozen / room / any。

    Returns
    -------
    bool
        True 表示物品满足温区约束（或无法判断时按默认策略放行）。
    """

    # ── 0. any → 不过滤 ──
    if zone == ZONE_ANY or not zone:
        return True

    # ── 1. 显式标签（最高优先级）──
    tag_zone = _infer_zone_from_tags(item)
    if tag_zone is not None:
        return tag_zone == zone

    # ── 2. 空间元数据（spatial_service 中可能存储了温区属性）──
    meta_zone = _infer_zone_from_spatial_meta(item)
    if meta_zone is not None:
        return meta_zone == zone

    # ── 3. 位置 / 空间名文本推断 ──
    text_zone = _infer_zone_from_text(item)
    if text_zone is not None:
        return text_zone == zone

    # ── 4. 默认策略：无法判断时的兜底 ──
    return _default_zone_fallback(item, zone)


# ──────────────────────────────────────────────
# 内部推断函数
# ──────────────────────────────────────────────

def _infer_zone_from_tags(item: Item) -> Optional[str]:
    """从 item.tags 中查找显式温区标签。"""
    for tag in item.tags:
        normalized = tag.strip().lower()
        if normalized in _ZONE_TAG_MAP:
            return _ZONE_TAG_MAP[normalized]
    return None


def _infer_zone_from_spatial_meta(item: Item) -> Optional[str]:
    """
    尝试从 spatial_service 获取该物品所在槽位的温区元数据。
    如果空间服务中为每个 slot 配置了 temperature_zone 属性，
    则直接读取，避免文本猜测。
    """
    try:
        if not item.belongsToSlotId:
            return None
        slot_meta = spatial_service.get_slot_metadata(item.belongsToSlotId)
        if slot_meta and "temperature_zone" in slot_meta:
            tz = slot_meta["temperature_zone"]
            if tz in (ZONE_COLD, ZONE_FROZEN, ZONE_ROOM):
                return tz
    except Exception as exc:
        logger.debug("spatial meta lookup failed for slot %s: %s",
                      item.belongsToSlotId, exc)
    return None


def _infer_zone_from_text(item: Item) -> Optional[str]:
    """
    从 location + spaceName + remark 文本中推断温区。
    这是最后的文本兜底，关键词集合集中维护在 _ZONE_LOCATION_KEYWORDS。
    """
    haystack = " ".join(filter(None, [
        item.location,
        item.spaceName,
        item.remark,
    ])).lower()

    if not haystack.strip():
        return None

    # 按 frozen → cold → room 顺序检测
    # （frozen 优先是因为"冷冻"包含"冷"字，避免误判为 cold）
    for zone_key in (ZONE_FROZEN, ZONE_COLD, ZONE_ROOM):
        keywords = _ZONE_LOCATION_KEYWORDS.get(zone_key, [])
        if any(kw in haystack for kw in keywords):
            return zone_key

    return None


def _default_zone_fallback(item: Item, requested_zone: str) -> bool:
    """
    所有推断手段都无法确定温区时的兜底策略。

    策略：
    - 请求 room（常温）→ 放行（大多数未标注物品默认常温存放）
    - 请求 cold / frozen → 拒绝（避免把常温物品错误推荐给冷藏查询）
    - 但如果 item 的 spaceName 包含"冰箱"，说明大概率是冷藏/冷冻，
      此时对 cold 放行（冰箱内未明确标注冷冻的，大概率是冷藏）
    """
    if requested_zone == ZONE_ROOM:
        return True

    # 冰箱内的物品：未标注冷冻 → 大概率冷藏
    space_lower = (item.spaceName or "").lower()
    if "冰箱" in space_lower or "fridge" in space_lower:
        if requested_zone == ZONE_COLD:
            return True
        # 请求 frozen 但无法确认 → 保守拒绝
        return False

    # 非冰箱空间 + 请求 cold/frozen → 拒绝
    return False
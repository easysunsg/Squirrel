"""Shared inventory parsing and presentation constants."""

EXPIRE_WARNING_DAYS: dict[str, int] = {
    "food": 3,
    "medicine": 30,
    "cosmetics": 30,
    "default": 7,
}

TAG_URGENT_THRESHOLD = 20
TAG_LOW_THRESHOLD = 50
NO_EXPIRE_SORT_KEY = float("inf")
FUZZY_LOCATION_CHARS = frozenset({"柜", "架", "层", "门", "抽屉"})
MIN_PARTIAL_MATCH_LENGTH = 2
DEFAULT_REMAINING_PCT = 100

VALID_INVENTORY_CATEGORIES = frozenset({
    "food", "medicine", "electronics", "cosmetics", "book", "other",
})

VALID_ITEM_ICONS = frozenset({
    "package_2", "construction", "medication", "bakery_dining", "local_cafe",
    "local_drink", "restaurant", "spa", "cleaning_services", "water_drop", "grain",
})

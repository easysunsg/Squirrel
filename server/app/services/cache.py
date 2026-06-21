"""Lightweight in-memory cache for recipe results."""

import hashlib
import json
import logging
import time
from typing import Any

logger = logging.getLogger(__name__)

CACHE_TTL_SECONDS = 82800  # 23 hours

# key -> (expiry_timestamp, data)
_cache: dict[str, tuple[float, Any]] = {}


def _make_key(expiring_food_list: list[dict], user_preference: str, reminder_time: str = "") -> str:
    """Generate a deterministic cache key from input parameters."""
    raw = json.dumps({"food": expiring_food_list, "preference": user_preference, "reminder_time": reminder_time}, sort_keys=True, ensure_ascii=False)
    return hashlib.md5(raw.encode("utf-8")).hexdigest()


def get_recipe_cache(expiring_food_list: list[dict], user_preference: str, reminder_time: str = "") -> dict | None:
    """Return cached recipe data if fresh, or None."""
    key = _make_key(expiring_food_list, user_preference, reminder_time)
    entry = _cache.get(key)
    if entry is None:
        return None
    expires_at, data = entry
    if time.time() > expires_at:
        del _cache[key]
        logger.info("Recipe cache expired for key=%s", key[:8])
        return None
    logger.info("Recipe cache hit for key=%s", key[:8])
    return data


def set_recipe_cache(expiring_food_list: list[dict], user_preference: str, data: dict, reminder_time: str = "") -> None:
    """Store recipe data in cache with TTL."""
    key = _make_key(expiring_food_list, user_preference, reminder_time)
    _cache[key] = (time.time() + CACHE_TTL_SECONDS, data)
    logger.info("Recipe cache set for key=%s ttl=%ds", key[:8], CACHE_TTL_SECONDS)


def clear_recipe_cache() -> None:
    """Clear all cached recipe results."""
    _cache.clear()
    logger.info("Recipe cache cleared")
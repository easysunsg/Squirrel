"""规划引擎 — 将 Intent 分解为可执行的 Action 队列。"""

from __future__ import annotations

import logging
from typing import Any, Dict, List

from app.models.state import (
    ActionStatus,
    AgentAction,
    generate_idempotency_key,
)

logger = logging.getLogger(__name__)


def plan_actions(
    intent: str,
    entities: Dict[str, Any],
    session_id: str = "default_session",
    graph_version: int = 0,
) -> List[AgentAction]:
    """将意图和实体分解为 AgentAction 列表。"""
    capability = _intent_to_capability(intent)
    if not capability:
        logger.info("[Planner] 无法映射意图: %s -> 跳过", intent)
        return []

    target = entities.get("target", "")
    tool_name = f"{capability}_{intent}"

    action = AgentAction(
        idempotency_key=generate_idempotency_key(
            session_id=session_id,
            graph_version=graph_version,
            tool_name=tool_name,
            arguments={"target": target, "intent": intent},
        ),
        capability=capability,
        tool_name=tool_name,
        arguments={
            "target": target,
            "intent": intent,
            "extracted_entities": entities,
        },
        status=ActionStatus.PENDING,
    )

    logger.info("[Planner] 规划: %s/%s target=%s", capability, tool_name, target)
    return [action]


def _intent_to_capability(intent: str) -> str | None:
    mapping = {
        "add": "inventory",
        "shopping_add": "shopping",
        "consume": "inventory",
        "remove": "inventory",
        "update_location": "inventory",
        "update_expiry": "inventory",
        "update_remark": "inventory",
        "update_remaining": "inventory",
        "expiry_query": "expiration",
        "location_query": "inventory",
        "quantity_query": "inventory",
        "search_query": "inventory",
        "idle_query": "inventory",
        "recipe": "recommendation",
        "chat": "chat",
    }
    return mapping.get(intent)

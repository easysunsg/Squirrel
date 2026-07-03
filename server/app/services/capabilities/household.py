"""HouseholdCapability — 家庭管理与多用户协作。"""

import logging
from typing import Any, Dict, List

from app.models.state import ActionStatus, AgentAction
from app.services.capabilities import BaseCapability, CapabilityRegistry

logger = logging.getLogger(__name__)


class HouseholdCapability(BaseCapability):
    """家庭管理能力域 — 多用户协作、家庭配置管理。"""

    name = "household"
    description = "家庭管理：多用户协作、家庭配置"

    def can_handle(self, action: AgentAction) -> bool:
        return action.capability == "household"

    def execute(self, action: AgentAction, context: Dict[str, Any]) -> Dict[str, Any]:
        intent = action.arguments.get("intent", "")

        if intent == "chat":
            return {
                "result": None,
                "mutation_logs": [],
                "reply_text": "家庭管理功能开发中，敬请期待！",
            }

        return {
            "result": None,
            "mutation_logs": [],
            "reply_text": f"不支持的家庭管理操作: {intent}",
        }


# 注册
CapabilityRegistry.register(HouseholdCapability())
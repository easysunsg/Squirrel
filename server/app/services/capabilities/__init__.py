"""能力域统一注册接口与基类。

每个 Capability 继承 BaseCapability，实现 execute() 和 validate() 方法。
通过 CapabilityRegistry 统一注册和发现。
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

from app.models.state import AgentAction


class BaseCapability(ABC):
    """能力域基类。"""

    name: str = ""
    description: str = ""

    @abstractmethod
    def execute(self, action: AgentAction, context: Dict[str, Any]) -> Dict[str, Any]:
        """执行能力域动作。

        Args:
            action: 要执行的 AgentAction
            context: 执行上下文（包含 inventory, user 等）

        Returns:
            执行结果 dict，包含 result, mutation_logs, reply_text 等
        """
        ...

    def validate(self, action: AgentAction, context: Dict[str, Any]) -> List[str]:
        """校验动作参数合法性。

        Returns:
            错误信息列表，空列表表示校验通过
        """
        return []

    def can_handle(self, action: AgentAction) -> bool:
        """判断是否能处理该动作。"""
        return False


class CapabilityRegistry:
    """能力域注册表。"""

    _capabilities: Dict[str, BaseCapability] = {}

    @classmethod
    def register(cls, capability: BaseCapability) -> None:
        cls._capabilities[capability.name] = capability

    @classmethod
    def get(cls, name: str) -> Optional[BaseCapability]:
        return cls._capabilities.get(name)

    @classmethod
    def get_for_action(cls, action: AgentAction) -> Optional[BaseCapability]:
        """根据 AgentAction 的 capability 字段查找对应的能力域。"""
        return cls._capabilities.get(action.capability)

    @classmethod
    def all(cls) -> List[BaseCapability]:
        return list(cls._capabilities.values())

    @classmethod
    def can_handle(cls, action: AgentAction) -> bool:
        cap = cls.get_for_action(action)
        return cap is not None and cap.can_handle(action)


# 导入所有 Capability（触发注册）
import app.services.capabilities.inventory  # noqa: F401, E402
import app.services.capabilities.expiration  # noqa: F401, E402
import app.services.capabilities.recommendation  # noqa: F401, E402
import app.services.capabilities.batch  # noqa: F401, E402
import app.services.capabilities.household  # noqa: F401, E402
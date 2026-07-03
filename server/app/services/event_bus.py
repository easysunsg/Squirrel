"""同步事件总线 — 基于 Topic + Scope 的精准事件分发。

模块级单例 `event_bus` 提供统一的发布/订阅接口。
EventRouter 按 event_type + scope 过滤订阅者，实现精准路由。
SubscriptionManager 管理消费者生命周期的注册与注销。

使用方式:
    from app.services.event_bus import event_bus

    def my_handler(event: SystemEvent) -> None:
        print(f"收到事件: {event.event_type}")

    cid = event_bus.subscribe("InventoryChanged", "SESSION", my_handler)
    event_bus.publish(some_event)
    event_bus.unsubscribe(cid)
"""

from __future__ import annotations

import logging
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Callable, Dict, List

from app.models.state import SystemEvent

logger = logging.getLogger(__name__)

# 消费者回调签名: (SystemEvent) -> None
EventCallback = Callable[[SystemEvent], None]

# Scope 级联表: 发布 scope → 应通知的 scope 集合
SCOPE_CASCADE: Dict[str, List[str]] = {
    "LOCAL": ["LOCAL", "SESSION", "GLOBAL"],
    "SESSION": ["SESSION", "GLOBAL"],
    "GLOBAL": ["GLOBAL"],
}


@dataclass
class Subscription:
    """订阅记录，描述一个消费者对特定事件类型和 scope 的订阅。"""
    callback_id: str = field(default_factory=lambda: f"sub_{uuid.uuid4().hex[:12]}")
    event_type: str = ""
    scope: str = "SESSION"
    callback: EventCallback = field(default=lambda _: None)


# ==========================================
# SubscriptionManager — 订阅生命周期管理
# ==========================================


class SubscriptionManager:
    """细粒度订阅管理器。

    内部索引结构:
        _subscriptions: event_type -> scope -> [Subscription]

    支持按 event_type + scope 精确查找订阅者集合。
    """

    def __init__(self) -> None:
        # event_type -> scope -> [Subscription]
        self._subscriptions: Dict[str, Dict[str, List[Subscription]]] = defaultdict(
            lambda: defaultdict(list)
        )
        # callback_id -> Subscription（快速注销查找）
        self._by_id: Dict[str, Subscription] = {}

    def add(self, event_type: str, scope: str, callback: EventCallback) -> str:
        """注册订阅，返回 callback_id。"""
        sub = Subscription(event_type=event_type, scope=scope, callback=callback)
        self._subscriptions[event_type][scope].append(sub)
        self._by_id[sub.callback_id] = sub
        logger.debug(
            "[SubscriptionManager] +订阅 %s: type=%s scope=%s",
            sub.callback_id, event_type, scope,
        )
        return sub.callback_id

    def remove(self, callback_id: str) -> bool:
        """注销订阅。返回 True 表示成功找到并移除。"""
        sub = self._by_id.pop(callback_id, None)
        if sub is None:
            logger.warning("[SubscriptionManager] 注销失败: callback_id=%s 不存在", callback_id)
            return False
        scope_list = self._subscriptions[sub.event_type][sub.scope]
        try:
            scope_list.remove(sub)
        except ValueError:
            pass
        # 清理空容器
        if not scope_list:
            del self._subscriptions[sub.event_type][sub.scope]
        if not self._subscriptions[sub.event_type]:
            del self._subscriptions[sub.event_type]
        logger.debug("[SubscriptionManager] -订阅 %s", callback_id)
        return True

    def get_subscribers(self, event_type: str, publish_scope: str) -> List[Subscription]:
        """按事件类型和发布 scope 级联规则获取匹配的订阅者列表。"""
        target_scopes = SCOPE_CASCADE.get(publish_scope, [publish_scope])
        result: List[Subscription] = []
        type_subs = self._subscriptions.get(event_type, {})
        for scope in target_scopes:
            result.extend(type_subs.get(scope, []))
        return result

    def clear(self) -> None:
        """清空所有订阅（用于测试重置）。"""
        self._subscriptions.clear()
        self._by_id.clear()


# ==========================================
# EventRouter — Topic + Scope 精准路由
# ==========================================


class EventRouter:
    """基于 Topic 和 Scope 的事件路由器。

    使用 SubscriptionManager 查找匹配的订阅者，
    按优先级（priority 数值小的先执行）排序后依次调用。
    """

    def __init__(self, manager: SubscriptionManager) -> None:
        self._manager = manager

    def route(self, event: SystemEvent) -> List[EventCallback]:
        """返回按优先级排序的匹配回调列表。"""
        subs = self._manager.get_subscribers(event.event_type, event.scope)
        # 按 priority 升序（数值越小优先级越高）
        subs.sort(key=lambda s: event.priority)
        return [s.callback for s in subs]


# ==========================================
# EventBus — 统一发布接口（模块单例）
# ==========================================


class EventBus:
    """同步事件总线。

    提供统一的事件发布与消费者订阅接口。
    publish() 同步遍历所有匹配订阅者并执行回调。
    """

    def __init__(self) -> None:
        self._manager = SubscriptionManager()
        self._router = EventRouter(self._manager)

    def publish(self, event: SystemEvent) -> None:
        """发布事件，同步分发给所有匹配的订阅者。

        每个回调被独立调用；单个回调异常不影响其他订阅者。
        """
        callbacks = self._router.route(event)
        logger.info(
            "[EventBus] 发布 %s (scope=%s) -> %d 订阅者",
            event.event_type, event.scope, len(callbacks),
        )
        for cb in callbacks:
            try:
                cb(event)
            except Exception:
                logger.exception(
                    "[EventBus] 回调异常: event=%s callback=%s",
                    event.event_type, cb.__name__,
                )

    def subscribe(self, event_type: str, scope: str, callback: EventCallback) -> str:
        """注册事件消费者，返回 callback_id 用于后续注销。"""
        return self._manager.add(event_type, scope, callback)

    def unsubscribe(self, callback_id: str) -> bool:
        """注销事件消费者。"""
        return self._manager.remove(callback_id)

    def reset(self) -> None:
        """重置所有订阅（用于测试隔离）。"""
        self._manager.clear()


# 模块级单例
event_bus = EventBus()

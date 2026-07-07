"""Tests for Phase 5: Event Bus & Precise Routing.

Tests cover:
1. EventBus publish/subscribe/unsubscribe
2. Scope cascading rules (LOCAL → LOCAL+SESSION+GLOBAL, etc.)
3. Exception isolation (one failing subscriber doesn't block others)
4. mutation_log_to_event conversion
5. state_updater_node event publishing
6. Full graph smoke test (no crash during event publish)
"""

import pytest

from app.models.state import (
    EventType,
    SystemEvent,
    mutation_log_to_event,
)
from app.services.event_bus import event_bus, SubscriptionManager
from app.services.graph import state_updater_node


# ====================================================================
# Fixtures
# ====================================================================

_SAMPLE_EVENT = SystemEvent(
    event_id="evt_test_001",
    event_type=EventType.INVENTORY_CHANGED,
    scope="SESSION",
    source_node="test",
    priority=1,
    payload={"op_type": "add", "sku_title": "牛奶", "delta": 2},
)


@pytest.fixture(autouse=True)
def _reset_event_bus():
    """每次测试前重置 EventBus，确保测试隔离。"""
    event_bus.reset()
    yield


# ====================================================================
# EventBus Unit Tests
# ====================================================================


class TestEventBusPublishSubscribe:
    def test_publish_invokes_subscriber(self):
        """订阅后发布事件，回调应被正确调用。"""
        received = []

        def handler(event: SystemEvent) -> None:
            received.append(event)

        cid = event_bus.subscribe(EventType.INVENTORY_CHANGED, "SESSION", handler)
        event_bus.publish(_SAMPLE_EVENT)

        assert len(received) == 1
        assert received[0].event_type == EventType.INVENTORY_CHANGED
        assert received[0].payload["sku_title"] == "牛奶"
        event_bus.unsubscribe(cid)

    def test_publish_no_subscriber_no_error(self):
        """发布没有订阅者的事件不应抛出异常。"""
        # INVENTORY_CHANGED 没有订阅者
        event_bus.publish(_SAMPLE_EVENT)  # 不应抛出异常

    def test_publish_multiple_subscribers(self):
        """多个订阅者都能收到事件。"""
        received = []

        def handler1(event: SystemEvent) -> None:
            received.append("h1")

        def handler2(event: SystemEvent) -> None:
            received.append("h2")

        cid1 = event_bus.subscribe(EventType.INVENTORY_CHANGED, "SESSION", handler1)
        cid2 = event_bus.subscribe(EventType.INVENTORY_CHANGED, "SESSION", handler2)
        event_bus.publish(_SAMPLE_EVENT)

        assert len(received) == 2
        assert "h1" in received
        assert "h2" in received
        event_bus.unsubscribe(cid1)
        event_bus.unsubscribe(cid2)

    def test_unsubscribe_removes_callback(self):
        """取消订阅后，回调不再被调用。"""
        received = []

        def handler(event: SystemEvent) -> None:
            received.append(event)

        cid = event_bus.subscribe(EventType.INVENTORY_CHANGED, "SESSION", handler)
        event_bus.publish(_SAMPLE_EVENT)
        assert len(received) == 1

        event_bus.unsubscribe(cid)
        event_bus.publish(_SAMPLE_EVENT)
        assert len(received) == 1  # 取消后不应再增加

    def test_subscriber_exception_isolation(self):
        """一个回调抛出异常不应阻止其他回调被调用。"""
        received = []

        def failing_handler(event: SystemEvent) -> None:
            raise ValueError("模拟异常")

        def normal_handler(event: SystemEvent) -> None:
            received.append("ok")

        cid1 = event_bus.subscribe(EventType.INVENTORY_CHANGED, "SESSION", failing_handler)
        cid2 = event_bus.subscribe(EventType.INVENTORY_CHANGED, "SESSION", normal_handler)

        # 即使 failing_handler 抛出异常，normal_handler 也应被调用
        event_bus.publish(_SAMPLE_EVENT)
        assert len(received) == 1
        assert received[0] == "ok"

        event_bus.unsubscribe(cid1)
        event_bus.unsubscribe(cid2)

    def test_unsubscribe_nonexistent_returns_false(self):
        """取消一个不存在的订阅应返回 False。"""
        result = event_bus.unsubscribe("nonexistent_id")
        assert result is False


class TestEventTypeFiltering:
    """验证事件类型过滤：只通知匹配类型的事件订阅者。"""

    def test_different_event_type_not_delivered(self):
        """订阅 INVENTORY_CHANGED 不应收到 EXECUTION_COMPLETED。"""
        received = []

        def handler(event: SystemEvent) -> None:
            received.append(event)

        cid = event_bus.subscribe(EventType.INVENTORY_CHANGED, "SESSION", handler)
        other_event = SystemEvent(
            event_id="evt_002",
            event_type=EventType.EXECUTION_COMPLETED,
            scope="SESSION",
            source_node="test",
        )
        event_bus.publish(other_event)
        assert len(received) == 0
        event_bus.unsubscribe(cid)


class TestScopeCascade:
    """验证作用域级联规则。"""

    SCOPE_EVENT = SystemEvent(
        event_id="evt_scope",
        event_type=EventType.SESSION_STATE_UPDATED,
        scope="SESSION",
        source_node="test",
    )

    def test_session_cascade_to_session_and_global(self):
        """SESSION 作用域的事件应通知 SESSION 和 GLOBAL 订阅者。"""
        session_received = []
        global_received = []

        def session_handler(e: SystemEvent) -> None:
            session_received.append(e)

        def global_handler(e: SystemEvent) -> None:
            global_received.append(e)

        cid1 = event_bus.subscribe(EventType.SESSION_STATE_UPDATED, "SESSION", session_handler)
        cid2 = event_bus.subscribe(EventType.SESSION_STATE_UPDATED, "GLOBAL", global_handler)
        event_bus.publish(self.SCOPE_EVENT)

        assert len(session_received) == 1
        assert len(global_received) == 1
        event_bus.unsubscribe(cid1)
        event_bus.unsubscribe(cid2)

    def test_global_does_not_cascade_to_session(self):
        """GLOBAL 作用域的事件不应通知 SESSION 订阅者。"""
        session_received = []

        def session_handler(e: SystemEvent) -> None:
            session_received.append(e)

        cid = event_bus.subscribe(EventType.SESSION_STATE_UPDATED, "SESSION", session_handler)
        global_event = SystemEvent(
            event_id="evt_global",
            event_type=EventType.SESSION_STATE_UPDATED,
            scope="GLOBAL",
            source_node="test",
        )
        event_bus.publish(global_event)

        assert len(session_received) == 0
        event_bus.unsubscribe(cid)

    def test_local_cascade_to_all(self):
        """LOCAL 作用域的事件应通知 LOCAL + SESSION + GLOBAL 订阅者。"""
        all_received = []

        def handler(e: SystemEvent) -> None:
            all_received.append(e)

        cid1 = event_bus.subscribe(EventType.SESSION_STATE_UPDATED, "LOCAL", handler)
        cid2 = event_bus.subscribe(EventType.SESSION_STATE_UPDATED, "SESSION", handler)
        cid3 = event_bus.subscribe(EventType.SESSION_STATE_UPDATED, "GLOBAL", handler)
        local_event = SystemEvent(
            event_id="evt_local",
            event_type=EventType.SESSION_STATE_UPDATED,
            scope="LOCAL",
            source_node="test",
        )
        event_bus.publish(local_event)

        assert len(all_received) == 3
        event_bus.unsubscribe(cid1)
        event_bus.unsubscribe(cid2)
        event_bus.unsubscribe(cid3)


# ====================================================================
# mutation_log_to_event Tests
# ====================================================================


class TestMutationLogToEvent:
    def test_basic_mapping(self):
        """验证 mutation_log dict → SystemEvent 的正确映射。"""
        log = {
            "event_id": "evt_original_001",
            "op_type": "add",
            "target_instance_id": "item_new_001",
            "sku_title": "牛奶",
            "delta": 2,
            "patch": None,
        }
        event = mutation_log_to_event(log, "test_node")

        assert event.event_type == EventType.INVENTORY_CHANGED
        assert event.scope == "SESSION"
        assert event.source_node == "test_node"
        assert event.payload["op_type"] == "add"
        assert event.payload["sku_title"] == "牛奶"
        assert event.payload["delta"] == 2
        assert event.payload["target_instance_id"] == "item_new_001"
        assert event.payload["original_event_id"] == "evt_original_001"

    def test_consume_log(self):
        """验证 consume 类型的 mutation_log 映射。"""
        log = {
            "event_id": "evt_002",
            "op_type": "consume",
            "target_instance_id": "item_001",
            "sku_title": "全麦面包",
            "delta": -1,
        }
        event = mutation_log_to_event(log, "executor")

        assert event.event_type == EventType.INVENTORY_CHANGED
        assert event.payload["op_type"] == "consume"
        assert event.payload["delta"] == -1

    def test_minimal_log(self):
        """验证最小化 mutation_log（无 event_id）也能正常映射。"""
        log = {
            "op_type": "remove",
            "target_instance_id": "item_002",
            "sku_title": "过期牛奶",
            "delta": -3,
        }
        event = mutation_log_to_event(log, "executor")

        assert event.event_type == EventType.INVENTORY_CHANGED
        assert event.payload["op_type"] == "remove"
        assert event.payload["original_event_id"] is None  # 原 log 无 event_id


# ====================================================================
# StateUpdater Event Publishing Tests
# ====================================================================


class TestStateUpdaterEvents:
    def test_state_updater_publishes_inventory_changed(self):
        """调用 state_updater_node 时应为每个 mutation_log 发布 INVENTORY_CHANGED。"""
        received = []

        def spy(event: SystemEvent) -> None:
            received.append(event)

        cid = event_bus.subscribe(EventType.INVENTORY_CHANGED, "SESSION", spy)

        state = {
            "mutation_logs": [
                {
                    "event_id": "e1", "op_type": "add",
                    "target_instance_id": "new_1", "sku_title": "牛奶", "delta": 2,
                },
                {
                    "event_id": "e2", "op_type": "consume",
                    "target_instance_id": "item_1", "sku_title": "面包", "delta": -1,
                },
            ],
            "graph_version": 0,
            "intent": "add",
        }
        result = state_updater_node(state)

        # 验证 publish 了 2 个 INVENTORY_CHANGED
        inventory_events = [e for e in received if e.event_type == EventType.INVENTORY_CHANGED]
        assert len(inventory_events) == 2
        assert inventory_events[0].payload["sku_title"] == "牛奶"
        assert inventory_events[1].payload["sku_title"] == "面包"

        # 验证 graph_version 递增
        assert result["graph_version"] == 1
        event_bus.unsubscribe(cid)

    def test_state_updater_publishes_execution_completed(self):
        """调用 state_updater_node 时应发布 EXECUTION_COMPLETED 事件。"""
        received = []

        def spy(event: SystemEvent) -> None:
            received.append(event)

        cid = event_bus.subscribe(EventType.EXECUTION_COMPLETED, "SESSION", spy)

        state = {
            "mutation_logs": [
                {"event_id": "e1", "op_type": "add", "target_instance_id": "new_1",
                 "sku_title": "牛奶", "delta": 2},
            ],
            "graph_version": 0,
            "intent": "add",
        }
        state_updater_node(state)

        assert len(received) == 1
        assert received[0].event_type == EventType.EXECUTION_COMPLETED
        assert received[0].payload["mutation_count"] == 1
        assert received[0].payload["intent"] == "add"
        event_bus.unsubscribe(cid)

    def test_state_updater_publishes_session_updated(self):
        """调用 state_updater_node 时应发布 SESSION_STATE_UPDATED 事件。"""
        received = []

        def spy(event: SystemEvent) -> None:
            received.append(event)

        cid = event_bus.subscribe(EventType.SESSION_STATE_UPDATED, "SESSION", spy)

        state = {
            "mutation_logs": [],
            "graph_version": 1,
            "intent": "chat",
        }
        result = state_updater_node(state)

        assert len(received) == 1
        assert received[0].event_type == EventType.SESSION_STATE_UPDATED
        assert received[0].payload["graph_version"] == 2  # 递增后
        assert received[0].payload["mutation_count"] == 0
        assert result["graph_version"] == 2
        event_bus.unsubscribe(cid)

    def test_state_updater_no_mutation_logs(self):
        """没有 mutation_logs 时也应发布 SESSION_STATE_UPDATED。"""
        received = []

        def spy(event: SystemEvent) -> None:
            received.append(event)

        cid1 = event_bus.subscribe(EventType.INVENTORY_CHANGED, "SESSION", spy)
        cid2 = event_bus.subscribe(EventType.EXECUTION_COMPLETED, "SESSION", spy)
        cid3 = event_bus.subscribe(EventType.SESSION_STATE_UPDATED, "SESSION", spy)

        state = {
            "mutation_logs": [],
            "graph_version": 0,
            "intent": "chat",
        }
        state_updater_node(state)

        # 不应有 INVENTORY_CHANGED（无日志）
        inventory_events = [e for e in received if e.event_type == EventType.INVENTORY_CHANGED]
        assert len(inventory_events) == 0

        # 应有 EXECUTION_COMPLETED（mutation_count=0）
        exec_events = [e for e in received if e.event_type == EventType.EXECUTION_COMPLETED]
        assert len(exec_events) == 1

        # 应有 SESSION_STATE_UPDATED
        session_events = [e for e in received if e.event_type == EventType.SESSION_STATE_UPDATED]
        assert len(session_events) == 1

        event_bus.unsubscribe(cid1)
        event_bus.unsubscribe(cid2)
        event_bus.unsubscribe(cid3)


# ====================================================================
# SubscriptionManager Unit Tests
# ====================================================================


class TestSubscriptionManager:
    def test_add_and_get_subscribers(self):
        manager = SubscriptionManager()
        cid = manager.add(EventType.INVENTORY_CHANGED, "SESSION", lambda e: None)
        subs = manager.get_subscribers(EventType.INVENTORY_CHANGED, "SESSION")
        assert len(subs) == 1
        assert subs[0].callback_id == cid

    def test_remove(self):
        manager = SubscriptionManager()
        cid = manager.add(EventType.INVENTORY_CHANGED, "SESSION", lambda e: None)
        assert manager.remove(cid) is True
        subs = manager.get_subscribers(EventType.INVENTORY_CHANGED, "SESSION")
        assert len(subs) == 0

    def test_remove_nonexistent(self):
        manager = SubscriptionManager()
        assert manager.remove("nonexistent") is False

    def test_clear(self):
        manager = SubscriptionManager()
        manager.add(EventType.INVENTORY_CHANGED, "SESSION", lambda e: None)
        manager.add(EventType.EXECUTION_COMPLETED, "GLOBAL", lambda e: None)
        manager.clear()
        assert len(manager.get_subscribers(EventType.INVENTORY_CHANGED, "SESSION")) == 0
        assert len(manager.get_subscribers(EventType.EXECUTION_COMPLETED, "GLOBAL")) == 0


# ====================================================================
# EventBus Reset and Re-registration Test
# ====================================================================


class TestEventBusReset:
    def test_reset_clears_all_subscribers(self):
        def handler(e: SystemEvent) -> None:
            pass

        event_bus.subscribe(EventType.INVENTORY_CHANGED, "SESSION", handler)
        event_bus.subscribe(EventType.EXECUTION_COMPLETED, "SESSION", handler)

        # 重置前应有订阅者
        event_bus.reset()

        # 重置后发布事件不应抛出异常（无订阅者）
        event_bus.publish(_SAMPLE_EVENT)  # 不应抛出异常

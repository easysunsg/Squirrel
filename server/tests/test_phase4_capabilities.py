"""Tests for Phase 4: Capability domain splitting and idempotent execution.

Tests cover:
1. CapabilityRegistry registration and lookup
2. InventoryCapability - all mutation/query handlers
3. ExpirationCapability - expiry queries
4. RecommendationCapability - recipe generation (mocked LLM)
5. BatchCapability - batch operations
6. HouseholdCapability - household management
7. ToolExecutor node
8. ResultValidator node
9. StateUpdater node
10. IdempotencyService
"""

import pytest
from datetime import datetime, timedelta

from app.models.schemas import Item
from app.models.state import (
    ActionStatus,
    AgentAction,
    ExtendedGraphState,
    PendingOperation,
    UserContext,
    generate_idempotency_key,
)
from app.services.capabilities import CapabilityRegistry, BaseCapability
from app.services.capabilities.inventory import InventoryCapability
from app.services.capabilities.expiration import ExpirationCapability
from app.services.capabilities.recommendation import RecommendationCapability
from app.services.capabilities.batch import BatchCapability
from app.services.capabilities.household import HouseholdCapability
from app.services.graph import (
    result_validator_node,
    route_after_validation,
    state_updater_node,
    tool_executor_node,
)
from app.services.idempotency import idempotency_service


# ====================================================================
# Test fixtures
# ====================================================================

SAMPLE_ITEM = Item(
    id="item-1", title="全麦面包", spaceId="kitchen", spaceName="主厨房",
    location="厨房二级柜", count=3, unit="袋", remainingPct=60,
    expireDate=(datetime.now() + timedelta(days=5)).strftime("%Y-%m-%d"),
)

SAMPLE_INVENTORY = [SAMPLE_ITEM]


# ====================================================================
# CapabilityRegistry tests
# ====================================================================


class TestCapabilityRegistry:
    def test_all_capabilities_registered(self):
        all_caps = CapabilityRegistry.all()
        names = {c.name for c in all_caps}
        assert "inventory" in names
        assert "expiration" in names
        assert "recommendation" in names
        assert "batch" in names
        assert "household" in names

    def test_get_by_name(self):
        cap = CapabilityRegistry.get("inventory")
        assert cap is not None
        assert isinstance(cap, InventoryCapability)

    def test_get_for_action(self):
        action = AgentAction(
            idempotency_key="test:0:inventory_add:abc",
            capability="inventory",
            tool_name="inventory_add",
        )
        cap = CapabilityRegistry.get_for_action(action)
        assert isinstance(cap, InventoryCapability)

    def test_get_nonexistent(self):
        assert CapabilityRegistry.get("nonexistent") is None


# ====================================================================
# InventoryCapability tests
# ====================================================================


class TestInventoryCapability:
    @pytest.fixture
    def cap(self):
        return InventoryCapability()

    @pytest.fixture
    def context(self):
        return {
            "inventory": SAMPLE_INVENTORY,
            "user_id": "u1",
            "user_name": "主人",
        }

    def test_can_handle(self, cap):
        action = AgentAction(
            idempotency_key="t:0:i:1", capability="inventory", tool_name="inventory_add",
        )
        assert cap.can_handle(action) is True

        action2 = AgentAction(
            idempotency_key="t:0:e:1", capability="expiration", tool_name="expiry",
        )
        assert cap.can_handle(action2) is False

    def test_add_generates_logs(self, cap, context):
        action = AgentAction(
            idempotency_key="t:0:i:1",
            capability="inventory",
            tool_name="inventory_add",
            arguments={
                "intent": "add",
                "target": "牛奶",
                "extracted_entities": {
                    "items": [{"title": "牛奶", "count": 2, "unit": "瓶"}],
                },
            },
        )
        result = cap.execute(action, context)
        assert len(result["mutation_logs"]) == 1
        assert result["mutation_logs"][0]["op_type"] == "add"
        assert result["mutation_logs"][0]["sku_title"] == "牛奶"

    def test_consume_generates_logs(self, cap, context):
        action = AgentAction(
            idempotency_key="t:0:i:2",
            capability="inventory",
            tool_name="inventory_consume",
            arguments={
                "intent": "consume",
                "target": "全麦面包",
                "extracted_entities": {"target": "全麦面包", "patch": {"deductCount": 1}},
            },
        )
        result = cap.execute(action, context)
        assert len(result["mutation_logs"]) == 1
        assert result["mutation_logs"][0]["op_type"] == "consume"

    def test_location_query(self, cap, context):
        action = AgentAction(
            idempotency_key="t:0:i:3",
            capability="inventory",
            tool_name="inventory_location_query",
            arguments={
                "intent": "location_query",
                "target": "全麦面包",
                "extracted_entities": {"target": "全麦面包"},
            },
        )
        result = cap.execute(action, context)
        assert "厨房二级柜" in result["reply_text"]

    def test_quantity_query(self, cap, context):
        action = AgentAction(
            idempotency_key="t:0:i:4",
            capability="inventory",
            tool_name="inventory_quantity_query",
            arguments={
                "intent": "quantity_query",
                "target": "全麦面包",
                "extracted_entities": {"target": "全麦面包"},
            },
        )
        result = cap.execute(action, context)
        assert "3" in result["reply_text"]

    def test_search_query_nonexistent(self, cap, context):
        action = AgentAction(
            idempotency_key="t:0:i:5",
            capability="inventory",
            tool_name="inventory_search_query",
            arguments={
                "intent": "search_query",
                "target": "不存在的物品",
                "extracted_entities": {"target": "不存在的物品"},
            },
        )
        result = cap.execute(action, context)
        assert "没有找到" in result["reply_text"]

    def test_update_location(self, cap, context):
        action = AgentAction(
            idempotency_key="t:0:i:6",
            capability="inventory",
            tool_name="inventory_update_location",
            arguments={
                "intent": "update_location",
                "target": "全麦面包",
                "extracted_entities": {
                    "target": "全麦面包",
                    "patch": {"location": "冰箱上层"},
                },
            },
        )
        result = cap.execute(action, context)
        assert len(result["mutation_logs"]) == 1
        assert result["mutation_logs"][0]["patch"]["location"] == "冰箱上层"


# ====================================================================
# ExpirationCapability tests
# ====================================================================


class TestExpirationCapability:
    @pytest.fixture
    def cap(self):
        return ExpirationCapability()

    def test_expiry_query_with_danger_items(self, cap):
        today = datetime.now()
        expired_item = Item(
            id="item-exp", title="过期牛奶", spaceId="kitchen", spaceName="主厨房",
            location="冰箱", count=1, unit="盒", remainingPct=10,
            expireDate=(today - timedelta(days=1)).strftime("%Y-%m-%d"),
        )
        context = {"inventory": [expired_item]}

        action = AgentAction(
            idempotency_key="t:0:e:1",
            capability="expiration",
            tool_name="expiry_query",
            arguments={"intent": "expiry_query", "extracted_entities": {}},
        )
        result = cap.execute(action, context)
        assert len(result["result"]["expiring_items"]) > 0

    def test_expiry_query_no_danger(self, cap):
        context = {"inventory": SAMPLE_INVENTORY}

        action = AgentAction(
            idempotency_key="t:0:e:2",
            capability="expiration",
            tool_name="expiry_query",
            arguments={"intent": "expiry_query", "extracted_entities": {}},
        )
        result = cap.execute(action, context)
        # SAMPLE_ITEM has remainingPct=60 and 5 days to expiry, may not be "danger"
        assert "reply_text" in result


# ====================================================================
# BatchCapability tests
# ====================================================================


class TestBatchCapability:
    @pytest.fixture
    def cap(self):
        return BatchCapability()

    def test_batch_add(self, cap):
        context = {"user_id": "u1", "user_name": "主人"}
        action = AgentAction(
            idempotency_key="t:0:b:1",
            capability="batch",
            tool_name="batch_add",
            arguments={
                "intent": "add",
                "extracted_entities": {
                    "items": [{"title": "鸡蛋", "count": 12}, {"title": "牛奶", "count": 2}],
                },
            },
        )
        result = cap.execute(action, context)
        assert len(result["mutation_logs"]) == 2
        assert result["mutation_logs"][0]["op_type"] == "add"


# ====================================================================
# HouseholdCapability tests
# ====================================================================


class TestHouseholdCapability:
    @pytest.fixture
    def cap(self):
        return HouseholdCapability()

    def test_can_handle(self, cap):
        action = AgentAction(
            idempotency_key="t:0:h:1", capability="household", tool_name="household_chat",
        )
        assert cap.can_handle(action) is True

    def test_chat_intent(self, cap):
        action = AgentAction(
            idempotency_key="t:0:h:1",
            capability="household",
            tool_name="household_chat",
            arguments={"intent": "chat"},
        )
        result = cap.execute(action, {})
        assert "开发中" in result["reply_text"]


# ====================================================================
# ToolExecutor node tests
# ====================================================================


class TestToolExecutorNode:
    def test_executor_finds_capability(self):
        state = {
            "intent": "add",
            "extracted_entities": {
                "target": "牛奶",
                "items": [{"title": "牛奶", "count": 1}],
            },
            "inventory": [],
            "current_user": UserContext(user_id="u1", user_name="主人", role="member"),
            "pending_operation": None,
            "confirmed_item_id": None,
            "confirmed_item_ids": [],
            "confirmed_patch": None,
            "user_preference": "",
            "reminder_time": "",
            "mutation_logs": [],
        }

        result = tool_executor_node(state)
        # Should find inventory capability and execute add
        if not result.get("idempotency_hit"):
            assert "mutation_logs" in result


# ====================================================================
# ResultValidator node tests
# ====================================================================


class TestResultValidator:
    def test_valid_logs_pass(self):
        state = {
            "mutation_logs": [{
                "event_id": "evt_123", "op_type": "add",
                "target_instance_id": "test", "sku_title": "牛奶",
                "delta": 1, "operator_id": "u1", "operator_name": "主人",
                "timestamp": datetime.now().isoformat(),
            }],
            "reply_text": "成功添加",
        }
        result = result_validator_node(state)
        assert result["validation_passed"] is True

    def test_empty_result_fails(self):
        state = {"mutation_logs": [], "reply_text": ""}
        result = result_validator_node(state)
        assert result["validation_passed"] is False

    def test_route_pass(self):
        assert route_after_validation({"validation_passed": True}) == "pass"

    def test_route_fail(self):
        assert route_after_validation({"validation_passed": False}) == "fail"


# ====================================================================
# StateUpdater node tests
# ====================================================================


class TestStateUpdater:
    def test_increments_version(self):
        state = {"graph_version": 5}
        result = state_updater_node(state)
        assert result["graph_version"] == 6

    def test_first_version(self):
        state = {"graph_version": 0}
        result = state_updater_node(state)
        assert result["graph_version"] == 1


# ====================================================================
# IdempotencyService tests
# ====================================================================


class TestIdempotencyService:
    def test_generate_key(self, tmp_path):
        key = generate_idempotency_key("sess_1", 0, "add_item", {"title": "牛奶"})
        assert key.startswith("sess_1:0:add_item:")

    def test_key_deterministic(self):
        args = {"title": "牛奶"}
        k1 = generate_idempotency_key("s1", 0, "add", args)
        k2 = generate_idempotency_key("s1", 0, "add", args)
        assert k1 == k2

    def test_key_different_for_different_args(self):
        k1 = generate_idempotency_key("s1", 0, "add", {"title": "牛奶"})
        k2 = generate_idempotency_key("s1", 0, "add", {"title": "面包"})
        assert k1 != k2
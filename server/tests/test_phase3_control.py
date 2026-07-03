"""Tests for Phase 3: Control layer (风控与预算守卫).

Tests cover:
1. ParameterResolver - parameter completeness checks
2. PolicyEngine - risk control policy evaluation
3. PreExecutionChecker - static interception
4. BudgetGuard - execution budget control
5. ConsistencyChecker - constraint consistency
6. CapabilityRouter - intent→capability routing
7. Full control pipeline integration
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
)
from app.services.graph import (
    budget_guard_node,
    capability_router_node,
    consistency_checker_node,
    parameter_resolver_node,
    policy_engine_node,
    pre_execution_checker_node,
    route_after_budget,
    route_after_capability,
    route_after_consistency,
    route_after_parameter_resolve,
    route_after_policy,
    route_after_pre_execution,
)


# ====================================================================
# ParameterResolver tests
# ====================================================================


class TestParameterResolver:
    def test_add_with_target_passes(self):
        state = {
            "intent": "add",
            "extracted_entities": {"target": "牛奶", "items": [{"title": "牛奶", "count": 2}]},
        }
        result = parameter_resolver_node(state)
        assert result == {}  # no missing parameters

    def test_add_without_target_fails(self):
        state = {
            "intent": "add",
            "extracted_entities": {},
        }
        result = parameter_resolver_node(state)
        assert "missing_parameters" in result
        assert "target_items" in result["missing_parameters"]

    def test_consume_with_target_passes(self):
        state = {
            "intent": "consume",
            "extracted_entities": {"target": "面包"},
        }
        result = parameter_resolver_node(state)
        assert result == {}

    def test_consume_without_target_fails(self):
        state = {
            "intent": "consume",
            "extracted_entities": {},
        }
        result = parameter_resolver_node(state)
        assert "missing_parameters" in result
        assert "target" in result["missing_parameters"]

    def test_update_location_missing_location(self):
        state = {
            "intent": "update_location",
            "extracted_entities": {"target": "面包"},
        }
        result = parameter_resolver_node(state)
        assert "missing_parameters" in result
        assert "location" in result["missing_parameters"]

    def test_update_location_with_location_passes(self):
        state = {
            "intent": "update_location",
            "extracted_entities": {"target": "面包", "location": "冰箱上层"},
        }
        result = parameter_resolver_node(state)
        assert result == {}

    def test_route_missing(self):
        state = {"missing_parameters": ["target"]}
        assert route_after_parameter_resolve(state) == "missing"

    def test_route_ready(self):
        state = {"missing_parameters": []}
        assert route_after_parameter_resolve(state) == "ready"


# ====================================================================
# PolicyEngine tests
# ====================================================================


class TestPolicyEngine:
    def test_no_violation_for_normal_add(self):
        state: ExtendedGraphState = {
            "intent": "add",
            "extracted_entities": {"target": "牛奶"},
            "pending_item_selection": [],
        }
        result = policy_engine_node(state)
        assert result.get("is_blocked") is False
        assert len(result.get("policy_violations", [])) == 0

    def test_warn_on_high_consumption(self):
        state: ExtendedGraphState = {
            "intent": "consume",
            "extracted_entities": {
                "target": "面包",
                "patch": {"deductCount": 15},
            },
            "pending_item_selection": [],
        }
        result = policy_engine_node(state)
        assert result.get("is_blocked") is False  # warn only
        assert len(result.get("policy_violations", [])) > 0

    def test_block_on_bulk_remove(self):
        state: ExtendedGraphState = {
            "intent": "remove",
            "extracted_entities": {"target": "物品"},
            "pending_item_selection": [{"id": f"item-{i}"} for i in range(8)],
        }
        result = policy_engine_node(state)
        assert result.get("is_blocked") is True

    def test_route_blocked(self):
        state = {"is_blocked": True}
        assert route_after_policy(state) == "blocked"

    def test_route_ready(self):
        state = {"is_blocked": False}
        assert route_after_policy(state) == "ready"


# ====================================================================
# PreExecutionChecker tests
# ====================================================================


class TestPreExecutionChecker:
    def test_consume_more_than_stock_auto_corrects(self):
        state: ExtendedGraphState = {
            "intent": "consume",
            "extracted_entities": {
                "target": "面包",
                "patch": {"deductCount": 100},
            },
            "inventory": [
                Item(id="item-1", title="面包", spaceId="kitchen", spaceName="主厨房",
                     location="柜子", count=3, unit="个", remainingPct=80),
            ],
        }
        result = pre_execution_checker_node(state)
        assert result.get("needs_correction") is True
        # Should auto-correct deductCount to total stock
        assert result["extracted_entities"]["patch"]["deductCount"] == 3

    def test_remove_nonexistent_item_invalid(self):
        state: ExtendedGraphState = {
            "intent": "remove",
            "extracted_entities": {"target": "不存在的物品"},
            "inventory": [
                Item(id="item-1", title="面包", spaceId="kitchen", spaceName="主厨房",
                     location="柜子", count=1, unit="个", remainingPct=80),
            ],
        }
        result = pre_execution_checker_node(state)
        assert result.get("is_invalid") is True

    def test_normal_operation_passes(self):
        state: ExtendedGraphState = {
            "intent": "add",
            "extracted_entities": {"target": "牛奶", "items": [{"title": "牛奶"}]},
            "inventory": [],
        }
        result = pre_execution_checker_node(state)
        assert result.get("is_invalid") is False
        assert result.get("needs_correction") is False

    def test_route_invalid(self):
        state = {"is_invalid": True}
        assert route_after_pre_execution(state) == "invalid"

    def test_route_ready(self):
        state = {"is_invalid": False}
        assert route_after_pre_execution(state) == "ready"


# ====================================================================
# BudgetGuard tests
# ====================================================================


class TestBudgetGuard:
    def test_normal_operation_passes(self):
        state: ExtendedGraphState = {
            "intent": "add",
            "extracted_entities": {"items": [{"title": "牛奶"}]},
            "loop_depth": 0,
            "max_depth": 5,
        }
        result = budget_guard_node(state)
        assert result.get("budget_exceeded") is False

    def test_loop_depth_exceeded(self):
        state: ExtendedGraphState = {
            "intent": "consume",
            "extracted_entities": {"target": "面包"},
            "loop_depth": 5,
            "max_depth": 5,
        }
        result = budget_guard_node(state)
        assert result.get("budget_exceeded") is True

    def test_batch_add_exceeds_limit(self):
        state: ExtendedGraphState = {
            "intent": "add",
            "extracted_entities": {"items": [{"title": f"物品{i}"} for i in range(25)]},
            "loop_depth": 0,
            "max_depth": 5,
        }
        result = budget_guard_node(state)
        assert result.get("budget_exceeded") is True

    def test_route_exceeded(self):
        state = {"budget_exceeded": True}
        assert route_after_budget(state) == "exceeded"

    def test_route_ready(self):
        state = {"budget_exceeded": False}
        assert route_after_budget(state) == "ready"


# ====================================================================
# ConsistencyChecker tests
# ====================================================================


class TestConsistencyChecker:
    def test_consistent_operation_passes(self):
        state: ExtendedGraphState = {
            "intent": "add",
            "extracted_entities": {"target": "牛奶"},
        }
        result = consistency_checker_node(state)
        assert result.get("is_inconsistent") is False

    def test_location_and_expiry_together_inconsistent(self):
        state: ExtendedGraphState = {
            "intent": "update_location",
            "extracted_entities": {
                "target": "面包",
                "patch": {"location": "冰箱", "expireDate": "2026-12-31"},
            },
        }
        result = consistency_checker_node(state)
        assert result.get("is_inconsistent") is True

    def test_route_inconsistent(self):
        state = {"is_inconsistent": True}
        assert route_after_consistency(state) == "inconsistent"

    def test_route_ready(self):
        state = {"is_inconsistent": False}
        assert route_after_consistency(state) == "ready"


# ====================================================================
# CapabilityRouter tests
# ====================================================================


class TestCapabilityRouter:
    def test_add_routes_to_inventory(self):
        state: ExtendedGraphState = {
            "intent": "add",
            "extracted_entities": {"target": "牛奶"},
        }
        result = capability_router_node(state)
        assert result.get("capability") == "inventory"
        assert result["current_action"].tool_name == "inventory_add"
        assert result["current_action"].status == ActionStatus.PENDING

    def test_expiry_query_routes_to_expiration(self):
        state: ExtendedGraphState = {
            "intent": "expiry_query",
            "extracted_entities": {},
        }
        result = capability_router_node(state)
        assert result.get("capability") == "expiration"

    def test_recipe_routes_to_recommendation(self):
        state: ExtendedGraphState = {
            "intent": "recipe",
            "extracted_entities": {"target": "鸡蛋"},
        }
        result = capability_router_node(state)
        assert result.get("capability") == "recommendation"

    def test_risk_level_determination(self):
        from app.services.graph import _determine_risk_level
        assert _determine_risk_level("add", {}) == "LOW"
        assert _determine_risk_level("remove", {}) == "MEDIUM"
        assert _determine_risk_level("consume", {"patch": {"deductCount": 10}}) == "HIGH"
        assert _determine_risk_level("chat", {}) == "LOW"

    def test_route_mutation(self):
        state = {"intent": "add"}
        assert route_after_capability(state) == "mutation"

    def test_route_query(self):
        state = {"intent": "expiry_query"}
        assert route_after_capability(state) == "query"
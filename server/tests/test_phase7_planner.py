"""Tests for Phase 7: Planner & Action Queue."""

import pytest
from app.models.state import (
    ActionStatus,
    AgentAction,
    ExtendedGraphState,
)
from app.services.graph import (
    planner_node,
    action_queue_node,
    loop_guard_node,
    route_after_queue,
    route_after_loop_guard,
)
from app.services.planner import plan_actions, _intent_to_capability


class TestPlanActions:
    def test_add_intent_creates_inventory_action(self):
        actions = plan_actions("add", {"target": "A"})
        assert len(actions) == 1
        assert actions[0].capability == "inventory"
        assert actions[0].tool_name == "inventory_add"
        assert actions[0].status == ActionStatus.PENDING

    def test_consume_intent_creates_inventory_action(self):
        actions = plan_actions("consume", {"target": "B"})
        assert actions[0].capability == "inventory"
        assert actions[0].tool_name == "inventory_consume"

    def test_recipe_intent_creates_recommendation_action(self):
        actions = plan_actions("recipe", {"target": "C"})
        assert actions[0].capability == "recommendation"
        assert actions[0].tool_name == "recommendation_recipe"

    def test_chat_intent_creates_chat_action(self):
        actions = plan_actions("chat", {})
        assert actions[0].capability == "chat"

    def test_unknown_intent_returns_empty(self):
        assert plan_actions("unknown_intent", {}) == []

    def test_idempotency_key_generated(self):
        actions = plan_actions("add", {"target": "X"}, "sess_t", 1)
        key = actions[0].idempotency_key
        assert "sess_t" in key and ":1:" in key

    def test_same_input_same_key(self):
        k1 = plan_actions("add", {"target": "X"}, "s1", 1)[0].idempotency_key
        k2 = plan_actions("add", {"target": "X"}, "s1", 1)[0].idempotency_key
        assert k1 == k2

    def test_different_input_different_key(self):
        k1 = plan_actions("add", {"target": "A"}, "s1", 1)[0].idempotency_key
        k2 = plan_actions("add", {"target": "B"}, "s1", 1)[0].idempotency_key
        assert k1 != k2


class TestIntentToCapability:
    def test_all_intents_mapped(self):
        for i in ["add", "consume", "remove", "update_location", "update_expiry",
                   "update_remaining", "expiry_query", "location_query",
                   "quantity_query", "search_query", "idle_query", "recipe", "chat"]:
            assert _intent_to_capability(i) is not None, f"{i}"

    def test_inventory_intents(self):
        for i in ["add", "consume", "remove", "update_location", "update_expiry"]:
            assert _intent_to_capability(i) == "inventory"


class TestPlannerNode:
    def test_sets_current_action(self):
        r = planner_node(ExtendedGraphState(intent="add", extracted_entities={"target": "X"}, graph_version=1))
        assert r["current_action"] is not None
        assert r["current_action"].tool_name == "inventory_add"
        assert len(r["action_queue"]) == 1

    def test_handles_unknown_intent(self):
        r = planner_node(ExtendedGraphState(intent="unknown"))
        assert r["current_action"] is None
        assert r["action_queue"] == []


class TestActionQueueNode:
    def test_queue_fifo(self):
        acts = [
            AgentAction(idempotency_key="k1", capability="i", tool_name="add", status=ActionStatus.PENDING),
            AgentAction(idempotency_key="k2", capability="i", tool_name="consume", status=ActionStatus.PENDING),
        ]
        r = action_queue_node(ExtendedGraphState(action_queue=acts))
        assert r["current_action"].tool_name == "add"
        assert len(r["action_queue"]) == 1
        assert r["action_queue"][0].tool_name == "consume"

    def test_queue_empty(self):
        r = action_queue_node(ExtendedGraphState(action_queue=[]))
        assert r["_queue_empty"] is True
        assert r["current_action"] is None

    def test_route_after_queue(self):
        assert route_after_queue(ExtendedGraphState(**{"_queue_empty": True})) == "empty"
        assert route_after_queue(ExtendedGraphState(**{"_queue_empty": False})) == "has_action"
        assert route_after_queue(ExtendedGraphState()) == "has_action"


class TestLoopGuard:
    def test_within_limit(self):
        r = loop_guard_node(ExtendedGraphState(loop_depth=0, max_depth=5))
        assert r["loop_exceeded"] is False
        assert r["loop_depth"] == 1

    def test_at_limit_triggers_halt(self):
        r = loop_guard_node(ExtendedGraphState(loop_depth=5, max_depth=5))
        assert r["loop_exceeded"] is True

    def test_route_after_loop_guard(self):
        assert route_after_loop_guard(ExtendedGraphState(**{"loop_exceeded": True})) == "halt"
        assert route_after_loop_guard(ExtendedGraphState(**{"loop_exceeded": False})) == "continue"

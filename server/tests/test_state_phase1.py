"""Tests for Phase 1: State model refactoring & execution semantics.

Tests cover:
1. AgentGraphState serialization/deserialization
2. SnapshotStoreState creation and restoration
3. Version conflict detection
4. Idempotency key generation
5. Agent → Extended state conversion (backward compatibility)
6. Extended → Agent state conversion
"""

import json
from datetime import datetime

import pytest
from pydantic import ValidationError

from app.models.state import (
    ActionStatus,
    AgentAction,
    AgentGraphState,
    ExtendedGraphState,
    MemoryStoreState,
    PendingOperation,
    SnapshotStoreState,
    UserContext,
    WorkspaceStoreState,
    agent_to_extended,
    create_snapshot,
    extended_to_agent,
    generate_idempotency_key,
    restore_snapshot,
    version_conflict_check,
)


class TestActionStatus:
    def test_enum_values(self):
        assert ActionStatus.PENDING.value == "PENDING"
        assert ActionStatus.RUNNING.value == "RUNNING"
        assert ActionStatus.SUCCESS.value == "SUCCESS"
        assert ActionStatus.FAILED.value == "FAILED"


class TestAgentAction:
    def test_minimal_agent_action(self):
        action = AgentAction(
            idempotency_key="sess_1:0:add_tool:abc123",
            capability="inventory",
            tool_name="add_item",
        )
        assert action.status == ActionStatus.PENDING
        assert action.risk_level == "LOW"
        assert action.action_id.startswith("act_")
        assert len(action.action_id) == 4 + 12  # "act_" + 12 hex chars

    def test_full_agent_action(self):
        action = AgentAction(
            idempotency_key="sess_1:0:add_tool:abc123",
            capability="expiration",
            tool_name="query_expiry",
            arguments={"days": 7},
            status=ActionStatus.RUNNING,
            risk_level="MEDIUM",
        )
        assert action.capability == "expiration"
        assert action.arguments == {"days": 7}
        assert action.status == ActionStatus.RUNNING

    def test_idempotency_key_required(self):
        with pytest.raises(ValidationError):
            AgentAction(capability="test", tool_name="test")


class TestSnapshotStoreState:
    def test_default_snapshot(self):
        snap = SnapshotStoreState()
        assert snap.is_suspended is False
        assert snap.graph_version == 0
        assert snap.suspension_reason is None
        assert snap.action_queue_snapshot == []
        assert snap.missing_parameters == []

    def test_create_snapshot_from_state(self):
        state = AgentGraphState(
            graph_version=3,
            loop_depth=2,
        )
        # Add some actions to workspace
        action = AgentAction(
            idempotency_key="sess:3:test:abc",
            capability="test",
            tool_name="test_tool",
        )
        state.workspace.action_queue.append(action)
        state.workspace.scratchpad["some_data"] = "value"

        snap = create_snapshot(state, reason="CONFIRMATION")
        assert snap.is_suspended is True
        assert snap.graph_version == 3
        assert snap.suspension_reason == "CONFIRMATION"
        assert snap.loop_depth_snapshot == 2
        assert len(snap.action_queue_snapshot) == 1
        assert snap.action_queue_snapshot[0].idempotency_key == "sess:3:test:abc"

    def test_restore_snapshot_success(self):
        state = AgentGraphState(graph_version=5)
        snap = SnapshotStoreState(
            is_suspended=True,
            snapshot_id="snap_test",
            graph_version=5,
            action_queue_snapshot=[
                AgentAction(
                    idempotency_key="sess:5:test:abc",
                    capability="test",
                    tool_name="test_tool",
                )
            ],
        )

        restored = restore_snapshot(state, snap)
        assert restored.execution_mode == "RESUME"
        assert len(restored.workspace.action_queue) == 1

    def test_restore_snapshot_version_conflict(self):
        state = AgentGraphState(graph_version=6)
        snap = SnapshotStoreState(
            is_suspended=True,
            snapshot_id="snap_test",
            graph_version=5,  # stale snapshot
        )

        with pytest.raises(ValueError, match="版本冲突"):
            restore_snapshot(state, snap)


class TestAgentGraphState:
    def test_default_state(self):
        state = AgentGraphState()
        assert state.execution_mode == "NEW"
        assert state.graph_version == 0
        assert state.loop_depth == 0
        assert state.memory.user_id == "default_user"
        assert isinstance(state.workspace, WorkspaceStoreState)
        assert isinstance(state.snapshot, SnapshotStoreState)

    def test_execution_mode_transitions(self):
        state = AgentGraphState(execution_mode="NEW")
        assert state.execution_mode == "NEW"

        state.execution_mode = "RESUME"
        assert state.execution_mode == "RESUME"

        state.execution_mode = "SUSPENDED"
        assert state.execution_mode == "SUSPENDED"

        state.execution_mode = "REPLAY"
        assert state.execution_mode == "REPLAY"

    def test_graph_version_increment(self):
        state = AgentGraphState(graph_version=0)
        state.graph_version += 1
        assert state.graph_version == 1

    def test_serialization_roundtrip(self):
        original = AgentGraphState(
            session_id="sess_test",
            trace_id="trace_test",
            execution_mode="SUSPENDED",
            graph_version=42,
            raw_user_input="测试输入",
            final_response={"reply_text": "测试回复"},
        )
        data = original.model_dump()
        restored = AgentGraphState.model_validate(data)
        assert restored.session_id == "sess_test"
        assert restored.execution_mode == "SUSPENDED"
        assert restored.graph_version == 42
        assert restored.raw_user_input == "测试输入"


class TestBackwardCompatibility:
    def test_extended_to_agent_conversion(self):
        ext: ExtendedGraphState = {
            "raw_text_input": "测试输入",
            "image_payloads": [],
            "current_user": UserContext(user_id="u1", user_name="主人", role="admin"),
            "intent": "add",
            "extracted_entities": {"target": "牛奶"},
            "interaction_mode": "normal",
            "current_context_item": None,
            "pending_item_selection": [],
            "pending_operation": None,
            "reply_text": "好的",
            "recipe_recommendation": None,
            "mutation_logs": [],
            "inventory": [],
            "last_added_item": None,
            "user_preference": "无特殊要求",
            "reminder_time": "",
            "confirmed_item_id": None,
            "confirmed_item_ids": [],
            "confirmed_patch": None,
            "pending_add_items": [],
        }

        agent = extended_to_agent(ext)
        assert agent.raw_user_input == "测试输入"
        assert agent.memory.user_id == "u1"
        assert agent.execution_mode == "NEW"
        assert agent.normalized_request.get("intent") == "add"

    def test_agent_to_extended_conversion(self):
        agent = AgentGraphState(
            session_id="sess_test",
            raw_user_input="测试",
            normalized_request={
                "intent": "query",
                "extracted_entities": {"target": "面包"},
            },
            final_response={"reply_text": "找到了"},
            memory=MemoryStoreState(
                user_id="u1",
                household_profile={"user_name": "主人", "role": "member"},
            ),
        )
        agent.workspace.scratchpad["interaction_mode"] = "normal"
        agent.workspace.scratchpad["inventory"] = []

        ext = agent_to_extended(agent)
        assert ext["raw_text_input"] == "测试"
        assert ext["intent"] == "query"
        assert ext["current_user"].user_id == "u1"

    def test_conversion_roundtrip(self):
        """Test that extended → agent → extended preserves key fields."""
        ext: ExtendedGraphState = {
            "raw_text_input": "帮我查一下牛奶",
            "image_payloads": [],
            "current_user": UserContext(user_id="u1", user_name="主人", role="member"),
            "intent": "search_query",
            "extracted_entities": {"target": "牛奶"},
            "interaction_mode": "normal",
            "current_context_item": None,
            "pending_item_selection": [],
            "pending_operation": None,
            "reply_text": "找到了牛奶",
            "recipe_recommendation": None,
            "mutation_logs": [],
            "inventory": [],
            "last_added_item": None,
            "user_preference": "无特殊要求",
            "reminder_time": "",
            "confirmed_item_id": None,
            "confirmed_item_ids": [],
            "confirmed_patch": None,
            "pending_add_items": [],
        }

        agent = extended_to_agent(ext)
        ext2 = agent_to_extended(agent)
        assert ext2["raw_text_input"] == "帮我查一下牛奶"
        assert ext2["intent"] == "search_query"
        assert ext2["current_user"].user_id == "u1"


class TestIdempotencyKey:
    def test_key_generation(self):
        key = generate_idempotency_key("sess_1", 0, "add_item", {"title": "牛奶", "count": 2})
        assert key.startswith("sess_1:0:add_item:")
        assert len(key) > len("sess_1:0:add_item:")

    def test_deterministic_for_same_args(self):
        args = {"title": "牛奶", "count": 2}
        key1 = generate_idempotency_key("sess_1", 0, "add_item", args)
        key2 = generate_idempotency_key("sess_1", 0, "add_item", args)
        assert key1 == key2

    def test_different_for_different_args(self):
        key1 = generate_idempotency_key("sess_1", 0, "add_item", {"title": "牛奶"})
        key2 = generate_idempotency_key("sess_1", 0, "add_item", {"title": "面包"})
        assert key1 != key2

    def test_different_for_different_version(self):
        args = {"title": "牛奶"}
        key1 = generate_idempotency_key("sess_1", 0, "add_item", args)
        key2 = generate_idempotency_key("sess_1", 1, "add_item", args)
        assert key1 != key2


class TestVersionConflictCheck:
    def test_no_conflict(self):
        assert version_conflict_check(5, 5) is True

    def test_conflict(self):
        assert version_conflict_check(5, 4) is False
        assert version_conflict_check(4, 5) is False

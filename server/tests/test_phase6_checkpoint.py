"""Tests for Phase 6: Checkpoint & REPLAY Mode.

Tests cover:
1. Checkpoint persistence (save, get, list, delete)
2. checkpoint_node - persists state snapshots after execution
3. TaskEvaluator node - CONTINUE/DONE/SUSPEND routing
4. REPLAY mode smoke test via run_squirrel_graph
"""

import json
from uuid import uuid4

import pytest

from app.db.sqlite import (
    cleanup_expired_checkpoints,
    connect,
    delete_checkpoint,
    get_checkpoint,
    list_checkpoints,
    save_checkpoint,
)
from app.models.state import ExtendedGraphState
from app.services.graph import (
    TASK_CONTINUE,
    TASK_DONE,
    TASK_SUSPEND,
    checkpoint_node,
    route_after_evaluator,
    run_squirrel_graph,
    task_evaluator_node,
)
from app.services.replay import ReplayEngine


# ====================================================================
# Fixtures
# ====================================================================


@pytest.fixture(autouse=True)
def _init_db():
    """Ensure DB is initialized before each test."""
    from app.db.sqlite import init_db
    init_db()
    yield


# ====================================================================
# Checkpoint DB Persistence Tests
# ====================================================================


class TestCheckpointPersistence:
    def test_save_and_get_checkpoint(self):
        checkpoint_id = f"ckpt_{uuid4().hex[:12]}"
        snapshot = {"intent": "add", "graph_version": 1, "mutation_log_count": 2}

        with connect() as conn:
            save_checkpoint(conn, checkpoint_id, "session-1", 1, "checkpoint_node", snapshot)
            result = get_checkpoint(conn, checkpoint_id)

        assert result is not None
        assert result["id"] == checkpoint_id
        assert result["session_id"] == "session-1"
        assert result["graph_version"] == 1
        assert result["node_name"] == "checkpoint_node"
        assert result["state_snapshot"]["intent"] == "add"
        assert result["state_snapshot"]["mutation_log_count"] == 2

    def test_get_nonexistent_checkpoint(self):
        with connect() as conn:
            result = get_checkpoint(conn, "ckpt_nonexistent")
        assert result is None

    def test_list_checkpoints_newest_first(self):
        with connect() as conn:
            save_checkpoint(conn, f"ckpt_{uuid4().hex[:12]}", "session-list", 1, "node_a", {"v": 1})
            save_checkpoint(conn, f"ckpt_{uuid4().hex[:12]}", "session-list", 2, "node_b", {"v": 2})
            save_checkpoint(conn, f"ckpt_{uuid4().hex[:12]}", "session-list", 3, "node_c", {"v": 3})
            results = list_checkpoints(conn, "session-list", limit=10)

        assert len(results) == 3
        assert results[0]["graph_version"] == 3
        assert results[2]["graph_version"] == 1

    def test_list_checkpoints_respects_session(self):
        with connect() as conn:
            save_checkpoint(conn, f"ckpt_{uuid4().hex[:12]}", "session-a", 1, "node", {})
            save_checkpoint(conn, f"ckpt_{uuid4().hex[:12]}", "session-b", 1, "node", {})
            results = list_checkpoints(conn, "session-a", limit=10)

        assert len(results) == 1
        assert all(c["session_id"] == "session-a" for c in results)

    def test_delete_checkpoint(self):
        ckpt_id = f"ckpt_{uuid4().hex[:12]}"
        with connect() as conn:
            save_checkpoint(conn, ckpt_id, "session-del", 1, "node", {})
            assert delete_checkpoint(conn, ckpt_id) is True
            assert get_checkpoint(conn, ckpt_id) is None

    def test_delete_nonexistent_checkpoint(self):
        with connect() as conn:
            assert delete_checkpoint(conn, "ckpt_nonexistent") is False

    def test_cleanup_expired_checkpoints(self):
        with connect() as conn:
            ckpt_id = f"ckpt_{uuid4().hex[:12]}"
            save_checkpoint(conn, ckpt_id, "session-exp", 1, "node", {})
            result = cleanup_expired_checkpoints(conn, ttl_minutes=0)
            assert result >= 1

    def test_checkpoint_updates_on_conflict(self):
        ckpt_id = f"ckpt_{uuid4().hex[:12]}"
        with connect() as conn:
            save_checkpoint(conn, ckpt_id, "session-upd", 1, "node_v1", {"version": 1})
            save_checkpoint(conn, ckpt_id, "session-upd", 2, "node_v2", {"version": 2})
            result = get_checkpoint(conn, ckpt_id)

        assert result["graph_version"] == 2
        assert result["node_name"] == "node_v2"


# ====================================================================
# Checkpoint Node Tests
# ====================================================================


class TestCheckpointNode:
    def test_checkpoint_node_saves_when_version_positive(self):
        state = ExtendedGraphState(
            mutation_logs=[
                {"event_id": "e1", "op_type": "add", "target_instance_id": "new_1",
                 "sku_title": "牛奶", "delta": 2},
            ],
            graph_version=1,
            intent="add",
            reply_text="已添加牛奶",
            interaction_mode="normal",
        )
        result = checkpoint_node(state)

        assert "_last_checkpoint_id" in result
        ckpt_id = result["_last_checkpoint_id"]
        assert ckpt_id.startswith("ckpt_")

        with connect() as conn:
            saved = get_checkpoint(conn, ckpt_id)
        assert saved is not None
        assert saved["state_snapshot"]["intent"] == "add"

    def test_checkpoint_node_skips_when_version_zero(self):
        state = ExtendedGraphState(
            mutation_logs=[],
            graph_version=0,
            intent="chat",
        )
        result = checkpoint_node(state)
        assert result == {}

    def test_checkpoint_node_empty_logs(self):
        state = ExtendedGraphState(
            mutation_logs=[],
            graph_version=2,
            intent="chat",
        )
        result = checkpoint_node(state)
        assert "_last_checkpoint_id" in result
        with connect() as conn:
            saved = get_checkpoint(conn, result["_last_checkpoint_id"])
        assert saved is not None
        assert saved["state_snapshot"]["mutation_log_count"] == 0


# ====================================================================
# TaskEvaluator Node Tests
# ====================================================================


class TestTaskEvaluator:
    def test_done_with_mutation_logs(self):
        state = ExtendedGraphState(
            mutation_logs=[
                {"event_id": "e1", "op_type": "add", "target_instance_id": "new_1",
                 "sku_title": "牛奶", "delta": 2},
            ],
            errors=[],
            is_blocked=False,
        )
        result = task_evaluator_node(state)
        assert result["_task_result"] == TASK_DONE

    def test_done_no_changes(self):
        state = ExtendedGraphState(
            mutation_logs=[],
            errors=[],
            is_blocked=False,
            interaction_mode="normal",
        )
        result = task_evaluator_node(state)
        assert result["_task_result"] == TASK_DONE

    def test_done_when_blocked(self):
        state = ExtendedGraphState(
            mutation_logs=[],
            errors=[],
            is_blocked=True,
        )
        result = task_evaluator_node(state)
        assert result["_task_result"] == TASK_DONE

    def test_suspend_with_errors_no_logs(self):
        state = ExtendedGraphState(
            mutation_logs=[],
            errors=[{"message": "DB error"}],
            is_blocked=False,
        )
        result = task_evaluator_node(state)
        assert result["_task_result"] == TASK_SUSPEND

    def test_suspend_pending_selection(self):
        state = ExtendedGraphState(
            mutation_logs=[],
            errors=[],
            is_blocked=False,
            interaction_mode="pending_selection",
        )
        result = task_evaluator_node(state)
        assert result["_task_result"] == TASK_SUSPEND

    def test_route_after_evaluator(self):
        state = ExtendedGraphState(**{"_task_result": TASK_DONE})
        assert route_after_evaluator(state) == "done"

        state = ExtendedGraphState(**{"_task_result": TASK_SUSPEND})
        assert route_after_evaluator(state) == "suspend"

        state = ExtendedGraphState(**{"_task_result": TASK_CONTINUE})
        assert route_after_evaluator(state) == "continue"

        state = ExtendedGraphState()
        assert route_after_evaluator(state) == "done"


# ====================================================================
# ReplayEngine Tests
# ====================================================================


class TestReplayEngine:
    def test_load_checkpoints(self):
        with connect() as conn:
            save_checkpoint(conn, f"ckpt_{uuid4().hex[:12]}", "session-rep", 1, "node", {"v": 1})
            save_checkpoint(conn, f"ckpt_{uuid4().hex[:12]}", "session-rep", 2, "node", {"v": 2})

        engine = ReplayEngine("session-rep")
        checkpoints = engine.load_checkpoints()
        assert len(checkpoints) == 2

    def test_get_latest_checkpoint(self):
        with connect() as conn:
            save_checkpoint(conn, f"ckpt_{uuid4().hex[:12]}", "session-late", 1, "node", {"v": 1})
            save_checkpoint(conn, f"ckpt_{uuid4().hex[:12]}", "session-late", 2, "node", {"v": 2})

        engine = ReplayEngine("session-late")
        engine.load_checkpoints()
        latest = engine.get_latest_checkpoint()
        assert latest is not None
        assert latest["graph_version"] == 2

    def test_replay_from_checkpoint(self):
        ckpt_id = f"ckpt_{uuid4().hex[:12]}"
        with connect() as conn:
            save_checkpoint(conn, ckpt_id, "session-rep2", 3, "executor", {"intent": "add"})

        engine = ReplayEngine("session-rep2")
        result = engine.replay_from_checkpoint(ckpt_id)

        assert result["replayed"] is True
        assert result["graph_version"] == 3
        assert result["state_snapshot"]["intent"] == "add"

    def test_replay_nonexistent_checkpoint_raises(self):
        engine = ReplayEngine("session-nonexist")
        with pytest.raises(ValueError):
            engine.replay_from_checkpoint("ckpt_nonexistent")

    def test_fast_forward(self):
        with connect() as conn:
            for v in range(1, 6):
                save_checkpoint(conn, f"ckpt_{uuid4().hex[:12]}", "session-ff", v, "node", {"v": v})

        engine = ReplayEngine("session-ff")
        snapshots = engine.fast_forward(3)

        assert len(snapshots) == 3
        assert snapshots[0]["v"] == 1
        assert snapshots[2]["v"] == 3


# ====================================================================
# REPLAY Mode Integration Test
# ====================================================================


class TestReplayMode:
    def test_replay_mode_without_checkpoints_returns_fallback(self):
        result = run_squirrel_graph("test", execution_mode="REPLAY")
        assert result["chat_result"].intent == "chat"
        # replyText 包含友好提示或为空字符串（LLM fallback 路径）
        assert result["chat_result"].replyText is not None
        assert result["db_operations"]["upsert_items"] == []
        assert result["db_operations"]["delete_ids"] == []

    @pytest.mark.slow
    def test_replay_mode_with_checkpoint(self):
        import pytest; pytest.skip("slow")
        from app.models.schemas import Item
        inventory = [
            Item(id="item-1", title="全麦面包", spaceName="主厨房",
                 location="厨房二级柜", count=3, unit="袋", remainingPct=60),
        ]
        normal_result = run_squirrel_graph("把全麦面包吃了", inventory=inventory)
        assert normal_result["chat_result"] is not None

        with connect() as conn:
            checkpoints = list_checkpoints(conn, "default_session", limit=5)
        if checkpoints:
            replay_result = run_squirrel_graph("", execution_mode="REPLAY")
            assert replay_result["chat_result"] is not None

    def test_replay_mode_returns_valid_structure(self):
        result = run_squirrel_graph("", execution_mode="REPLAY")

        expected_keys = {
            "chat_result", "db_operations", "interaction_mode",
            "pending_item_selection", "pending_operation",
            "last_added_item", "current_context_item", "recipe_recommend",
        }
        assert expected_keys.issubset(result.keys())
        assert "upsert_items" in result["db_operations"]
        assert "delete_ids" in result["db_operations"]


# ====================================================================
# ResponseGenerator Node Tests (Phase 8)
# ====================================================================


class TestResponseGenerator:
    """验证 ResponseGenerator 节点。"""

    def test_reply_text_passed_through(self):
        state = ExtendedGraphState(
            reply_text="已完成操作",
            intent="add",
            mutation_logs=[{"event_id": "e1", "op_type": "add", "target_instance_id": "new_1",
                           "sku_title": "牛奶", "delta": 2}],
        )
        from app.services.graph import response_generator_node
        result = response_generator_node(state)
        assert result["reply_text"] == "已完成操作"
        assert result["final_response"]["reply_text"] == "已完成操作"

    def test_context_released_on_remove(self):
        from app.services.graph import response_generator_node
        state = ExtendedGraphState(
            current_context_item={"id": "item-1", "title": "面包"},
            mutation_logs=[{"event_id": "e1", "op_type": "consume",
                           "target_instance_id": "item-1", "sku_title": "面包", "delta": -1}],
        )
        result = response_generator_node(state)
        assert result["current_context_item"] is None  # 已释放

    def test_context_preserved_on_unrelated_change(self):
        from app.services.graph import response_generator_node
        state = ExtendedGraphState(
            current_context_item={"id": "item-1", "title": "面包"},
            mutation_logs=[{"event_id": "e1", "op_type": "add",
                           "target_instance_id": "new_2", "sku_title": "牛奶", "delta": 2}],
        )
        result = response_generator_node(state)
        assert result["current_context_item"] is not None  # 未被释放

    def test_no_mutation_logs(self):
        from app.services.graph import response_generator_node
        state = ExtendedGraphState(
            reply_text="查询完成",
            intent="expiry_query",
            mutation_logs=[],
            interaction_mode="normal",
        )
        result = response_generator_node(state)
        assert result["final_response"]["has_mutations"] is False
        assert result["final_response"]["intent"] == "expiry_query"

    def test_default_reply(self):
        from app.services.graph import response_generator_node
        state = ExtendedGraphState()
        result = response_generator_node(state)
        assert "收到" in result["reply_text"]

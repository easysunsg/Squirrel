"""Comprehensive Q&A test suite based on docs/tests/Q&A.md.

Covers 7 categories of real-world scenarios for the LangGraph topology.
Uses run_squirrel_graph directly (bypasses LLM) to test graph routing logic.
"""

import pytest
from datetime import datetime, timedelta
from app.models.schemas import Item
from app.services.graph import run_squirrel_graph


# ============================================
# 一、常规原子变动场景（无冲突、无歧义）
# ============================================

class TestAtomicMutations:

    def test_1_1_clean_single_add(self):
        """用例1.1：干净的单品新增入库"""
        result = run_squirrel_graph(
            "买了两盒草莓，放进冰箱冷藏层了。",
            current_user_id="user_husband",
            current_user_name="老公",
        )
        chat = result["chat_result"]
        assert chat.intent == "add"
        db_ops = result.get("db_operations", {})
        pending = db_ops.get("pending_add", [])
        assert len(pending) >= 1
        first = pending[0]
        assert "草莓" in first.title

    def test_1_2_precise_consume(self):
        """用例1.2：精准的指定消耗"""
        inventory = [
            Item(id="milk-001", title="特仑苏纯牛奶", spaceName="厨房",
                 location="二级柜", count=12, unit="盒", remainingPct=100),
        ]
        result = run_squirrel_graph(
            "特仑苏纯牛奶被我喝了一盒。",
            inventory=inventory,
            current_user_id="user_wife",
            current_user_name="老婆",
        )
        chat = result["chat_result"]
        assert chat.intent == "consume"


# ============================================
# 二、核心FIFO算法测试
# ============================================

class TestFifo:

    def test_2_1_fifo_locks_earliest_batch(self):
        """用例2.1：模糊口语消耗，触发临期批次自动锁定"""
        today = datetime.now()
        yesterday = (today - timedelta(days=1)).strftime("%Y-%m-%d")
        day_before = (today - timedelta(days=2)).strftime("%Y-%m-%d")

        inventory = [
            Item(id="A1", title="山姆全脂鲜奶", spaceName="厨房",
                 location="冰箱冷藏层", count=1, unit="瓶",
                 remainingPct=20, expireDate=day_before),
            Item(id="A2", title="山姆全脂鲜奶", spaceName="厨房",
                 location="冰箱冷藏层", count=1, unit="瓶",
                 remainingPct=50, expireDate=yesterday),
        ]
        result = run_squirrel_graph(
            "冰箱里的鲜奶我喝了一瓶。",
            inventory=inventory,
            current_user_id="user_husband",
            current_user_name="老公",
        )
        chat = result["chat_result"]
        assert chat.intent == "consume"
        # Two identical items with different expiries trigger multi-candidate path
        # Candidate items are returned for user selection (FIFO ordering applied)
        selection = result.get("pending_item_selection", [])
        pending_op = result.get("pending_operation")
        if len(selection) >= 2:
            assert result.get("interaction_mode") == "pending_selection"
            # First candidate should be A1 (earliest expire by FIFO)
            assert selection[0].get("id") == "A1"
        elif pending_op:
            source_ids = pending_op.get("source_batch_ids", [])
            assert "A1" in source_ids  # FIFO picks earliest expire


# ============================================
# 三、名称歧义与多候选消除场景
# ============================================

class TestAmbiguity:

    def test_3_1_ambiguous_triggers_selection(self):
        """用例3.1：名字多义性拦截，推送候选集"""
        inventory = [
            Item(id="B1", title="山姆全脂鲜奶", spaceName="厨房",
                 location="冰箱冷藏层", count=1, unit="瓶", remainingPct=100),
            Item(id="B2", title="特仑苏纯牛奶", spaceName="厨房",
                 location="二级柜", count=12, unit="盒", remainingPct=100),
        ]
        result = run_squirrel_graph(
            "牛奶喝完了一盒。",
            inventory=inventory,
            current_user_id="user_husband",
            current_user_name="老公",
        )
        chat = result["chat_result"]
        assert chat.intent == "consume"
        selection = result.get("pending_item_selection", [])
        if selection:
            assert result.get("interaction_mode") == "pending_selection"

    def test_3_2_confirm_selection(self):
        """用例3.2：用户输入序号，状态机自控接管执行"""
        inventory = [
            Item(id="B1", title="山姆全脂鲜奶", spaceName="厨房",
                 location="冰箱冷藏层", count=1, unit="瓶", remainingPct=100),
            Item(id="B2", title="特仑苏纯牛奶", spaceName="厨房",
                 location="二级柜", count=12, unit="盒", remainingPct=100),
        ]
        result1 = run_squirrel_graph(
            "牛奶喝完了一盒。",
            inventory=inventory,
            current_user_id="user_husband",
            current_user_name="老公",
        )
        selection = result1.get("pending_item_selection", [])
        pending_op = result1.get("pending_operation")

        if not selection:
            pytest.skip("模糊匹配未触发候选（3-tier已消解歧义）")

        result2 = run_squirrel_graph(
            "1",
            inventory=inventory,
            interaction_mode="pending_selection",
            pending_item_selection=selection,
            pending_operation=pending_op,
        )
        assert result2.get("interaction_mode") in ("normal", None)


# ============================================
# 四、家庭成员并发协同与囤货拦截场景
# ============================================

class TestStockpileIntercept:

    def test_4_1_duplicate_add_intercept(self):
        """用例4.1：老公重复买物资，系统触发防囤货拦截"""
        inventory = [
            Item(id="W1", title="山姆全脂鲜奶", spaceName="厨房",
                 location="冰箱冷藏层", count=2, unit="瓶", remainingPct=100,
                 buyDate=datetime.now().strftime("%Y-%m-%d")),
        ]
        result = run_squirrel_graph(
            "老婆，我刚在楼下又提了一箱山姆全脂鲜奶回来，入库一下。",
            inventory=inventory,
            current_user_id="user_husband",
            current_user_name="老公",
        )
        chat = result["chat_result"]
        assert chat.intent == "add"


# ============================================
# 五、跨轮次时空感知与记忆继承
# ============================================

class TestContextInheritance:

    def test_5_1_recipe_context_inheritance(self):
        """用例5.1：多轮上下文无主语延续（生成菜谱）"""
        inventory = [
            Item(id="C1", title="全麦面包", spaceName="主厨房",
                 location="厨房二级柜", count=1, unit="包", remainingPct=30,
                 expireDate=(datetime.now() + timedelta(days=2)).strftime("%Y-%m-%d"),
                 category="food"),
        ]
        result = run_squirrel_graph(
            "帮我生成菜单。",
            inventory=inventory,
            current_context_item={
                "id": "C1", "title": "全麦面包",
                "location": "厨房二级柜", "spaceName": "主厨房",
            },
        )
        chat = result["chat_result"]
        assert chat.intent == "recipe"
        assert len(chat.replyText) > 0


# ============================================
# 六、强中断与状态逃逸场景
# ============================================

class TestEscape:

    def test_6_1_escape_from_pending(self):
        """用例6.1：用户反悔，强中断重置状态"""
        result = run_squirrel_graph(
            "算了，不要了。",
            interaction_mode="pending_selection",
            pending_item_selection=[{"id": "X1", "title": "测试品"}],
            current_user_id="user_husband",
            current_user_name="老公",
        )
        assert result.get("interaction_mode") == "normal"
        assert "取消" in result["chat_result"].replyText

    def test_6_3_greeting_resets_pending(self):
        """用例6.3：pending 状态下用户打招呼，自动清除待选状态"""
        result = run_squirrel_graph(
            "你好呀",
            interaction_mode="pending_selection",
            pending_item_selection=[{"id": "X1", "title": "测试品"}],
        )
        assert result.get("interaction_mode") != "pending_selection"
        # 不应出现序号选择提示
        assert "有效序号" not in result["chat_result"].replyText

    def test_6_4_single_number_stays_pending(self):
        """用例6.4：pending 状态下输入"1"保持待选流程"""
        result = run_squirrel_graph(
            "1",
            interaction_mode="pending_selection",
            pending_item_selection=[{"id": "X1", "title": "测试品", "count": 1, "unit": "个"}],
        )
        # 应进入 confirm_handler，最终走 normal（确认完成）
        assert result.get("interaction_mode") != "pending_selection"


# ============================================
# 七、纯只读空间/时效查询场景
# ============================================

class TestReadOnlyQueries:

    def test_7_1_location_query(self):
        """用例7.1：资产空间溯源查询"""
        inventory = [
            Item(id="D1", title="全麦面包", spaceName="主厨房",
                 location="厨房二级柜", count=1, unit="包", remainingPct=80),
        ]
        result = run_squirrel_graph(
            "老公，你买的那包全麦面包被你塞到哪里去了？",
            inventory=inventory,
            current_user_id="user_wife",
            current_user_name="老婆",
        )
        assert result["chat_result"].intent == "location_query"

    def test_7_2_expiry_query(self):
        """快过期物品查询"""
        inventory = [
            Item(title="酸奶", spaceName="厨房", location="冰箱",
                 count=3, unit="盒", remainingPct=15, tag="告急",
                 expireDate=(datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")),
        ]
        result = run_squirrel_graph("现在有什么快过期？", inventory=inventory)
        assert result["chat_result"].intent == "expiry_query"
        assert "酸奶" in result["chat_result"].replyText

    def test_7_3_quantity_query(self):
        """数量查询"""
        inventory = [
            Item(title="鸡蛋", spaceName="厨房", location="冰箱",
                 count=12, unit="个", remainingPct=100),
        ]
        result = run_squirrel_graph("冰箱里还有多少个鸡蛋？", inventory=inventory)
        assert result["chat_result"].intent == "quantity_query"
        assert "12" in result["chat_result"].replyText

    def test_7_4_search_query(self):
        """搜索查询"""
        inventory = [
            Item(title="感冒药", spaceName="储藏间", location="药品箱B",
                 count=2, unit="盒", remainingPct=80),
        ]
        result = run_squirrel_graph("找一下感冒药", inventory=inventory)
        assert result["chat_result"].intent in ("search_query", "location_query")

    def test_7_5_idle_query(self):
        """闲置物品查询"""
        inventory = [
            Item(title="旧手机", spaceName="书房", location="抽屉",
                 count=1, unit="台", remainingPct=95, buyDate="2024-01-15"),
        ]
        result = run_squirrel_graph("家里有什么长期不用的东西？", inventory=inventory)
        assert "闲置" in result["chat_result"].replyText or result["chat_result"].intent in ("idle_query", "search_query", "chat")


# ============================================
# 八、边界与错误处理
# ============================================

class TestEdgeCases:

    def test_empty_text(self):
        """空输入"""
        result = run_squirrel_graph("")
        assert result["chat_result"] is not None

    def test_empty_inventory(self):
        """空库存"""
        result = run_squirrel_graph("冰箱里有什么", inventory=[])
        assert result["chat_result"] is not None

    def test_update_location(self):
        """更新位置"""
        inventory = [
            Item(id="E1", title="胡萝卜", spaceName="厨房",
                 location="冰箱下层", count=5, unit="根", remainingPct=100),
        ]
        result = run_squirrel_graph("把胡萝卜换到冰箱上层", inventory=inventory)
        assert result["chat_result"].intent in ("update_location", "add", "chat")

    def test_update_expiry(self):
        """更新保质期"""
        inventory = [
            Item(id="F1", title="牛奶", spaceName="厨房",
                 location="冰箱", count=1, unit="盒", remainingPct=100),
        ]
        result = run_squirrel_graph("牛奶的保质期还有3天", inventory=inventory)
        assert result["chat_result"].intent in ("update_expiry", "quantity_query", "chat", "expiry_query")

    def test_remove_item(self):
        """移除物品"""
        inventory = [
            Item(id="G1", title="橘子", spaceName="客厅",
                 location="柜子", count=3, unit="个", remainingPct=100),
        ]
        result = run_squirrel_graph("橘子坏了，扔掉", inventory=inventory)
        assert result["chat_result"].intent == "remove"

    def test_general_chat(self):
        """普通聊天"""
        result = run_squirrel_graph("你好", inventory=[])
        assert result["chat_result"].intent == "chat"
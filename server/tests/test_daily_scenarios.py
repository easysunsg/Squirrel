r"""Tests for all 50 daily-life AI scenarios against the /api/chat SSE endpoint.

Each test method corresponds to one scenario from docs/daily-ai-scenarios.md and
exercises the full request → SSE parse → response validation pipeline using
the FastAPI TestClient against a freshly created app (isolated SQLite DB).

After all tests pass, run the companion script or call the output helper to
generate docs/daily-ai-test-results.md with the conversation transcripts.

Usage:
    cd server
    uv run pytest tests/test_daily_scenarios.py -v --tb=short
"""

from __future__ import annotations

import json
import os
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.models.schemas import Item

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

DOCS_DIR = Path(__file__).resolve().parents[2] / "docs"
OUTPUT_FILE = DOCS_DIR / "daily-ai-test-results.md"


def _read_sse(response) -> dict[str, Any]:
    """Parse an SSE ``text/event-stream`` response and return the last
    ``event: result`` payload as a Python dict."""
    raw = b""
    for chunk in response.iter_bytes():
        raw += chunk
    text = raw.decode("utf-8")

    blocks = text.split("\n\n")
    for block in reversed(blocks):
        lines = block.strip().split("\n")
        event_type = ""
        event_data = ""
        for line in lines:
            if line.startswith("event: "):
                event_type = line[7:].strip()
            elif line.startswith("data: "):
                event_data = line[6:]
        if event_type == "result" and event_data:
            return json.loads(event_data)

    raise AssertionError(f"No event: result in SSE stream.\nRaw preview: {text[:500]}")


def _chat(
    client: TestClient,
    text: str,
    *,
    inventory: list[Item] | None = None,
    user_name: str = "主人",
) -> dict[str, Any]:
    """Post a single user message to ``/api/chat`` and return the result
    payload (the ``event: result`` block)."""
    payload: dict[str, Any] = {
        "messages": [
            {
                "id": f"msg-{hash(text) & 0xFFFFFFFF:08x}",
                "sender": "user",
                "text": text,
                "timestamp": "刚刚",
            }
        ],
        "userName": user_name,
    }
    if inventory is not None:
        payload["currentInventory"] = [i.model_dump() for i in inventory]
    resp = client.post("/api/chat", json=payload)
    assert resp.status_code == 200, f"Chat endpoint returned {resp.status_code}"
    assert resp.headers.get("content-type", "").startswith("text/event-stream")
    return _read_sse(resp)


def _confirm_add(client: TestClient, result: dict[str, Any]) -> None:
    """If the result contains a pending add operation, confirm it with the
    suggested items so the inventory is updated."""
    if result.get("needsConfirmation") and result.get("pendingId"):
        pending_id = result["pendingId"]
        items = result.get("itemSuggestion", {}).get("items", [])
        cr = client.post(
            "/api/chat/confirm",
            json={"pendingId": pending_id, "items": items},
        )
        # 200 is ok; 404 means the pending already expired — that's fine
        assert cr.status_code in (200, 404)


def _current_items(client: TestClient) -> list[dict[str, Any]]:
    """Return the current inventory item list from ``/api/items``."""
    return client.get("/api/items").json()["items"]


def _reset(client: TestClient) -> None:
    """Reset inventory to factory defaults."""
    client.post("/api/items/reset")


@pytest.fixture
def client():
    """Each test gets a *fresh* app (and therefore a fresh in-memory SQLite
    database seeded with the three default items)."""
    return TestClient(create_app())


# ===================================================================
# 一、🌅 晨间日常（#1–#5）
# ===================================================================

class TestMorningRoutine:
    """Morning routine – general chat and lightweight queries."""

    def test_1_morning_grumpiness(self, client: TestClient) -> None:
        """#1 起床气 — 用户不想起床，智能体给予回应。"""
        result = _chat(client, "再睡五分钟……")
        assert result.get("reply")
        assert len(result["reply"]) > 0
        assert result.get("messages")

    def test_2_what_to_wear(self, client: TestClient) -> None:
        """#2 今天穿什么 — 天气/穿搭类咨询。"""
        result = _chat(client, "今天穿什么？")
        assert result.get("reply")

    def test_3_breakfast_suggestion(self, client: TestClient) -> None:
        """#3 早餐营养师 — 冰箱内容咨询与食谱建议。"""
        result = _chat(client, "早餐吃什么？冰箱里有鸡蛋、番茄、菠菜")
        assert result.get("reply")

    def test_4_leaving_check(self, client: TestClient) -> None:
        """#4 出门前检查 — 提醒确认类对话。"""
        result = _chat(client, "我出门了！")
        assert result.get("reply")

    def test_5_commute_news(self, client: TestClient) -> None:
        """#5 通勤新闻速读 — 资讯查询。"""
        result = _chat(client, "今天有什么要闻吗？")
        assert result.get("reply")


# ===================================================================
# 二、🍳 烹饪与饮食（#6–#10）
# ===================================================================

class TestCookingAndDiet:
    """Cooking, meal planning, dietary advice."""

    def test_6_empty_fridge(self, client: TestClient) -> None:
        """#6 冰箱快空了 — 基于现有食材的烹饪建议。"""
        result = _chat(
            client,
            "冰箱里只剩鸡蛋、西兰花、黄油和快过期的牛奶了，能做什么？",
        )
        assert result.get("reply")

    def test_7_cooking_for_friends(self, client: TestClient) -> None:
        """#7 招待朋友 — 设计不易翻车的菜单。"""
        result = _chat(
            client,
            "周末有三个大人一个小孩来吃饭，帮我设计一个不容易翻车的菜单",
        )
        assert result.get("reply")

    def test_8_blood_sugar_control(self, client: TestClient) -> None:
        """#8 营养控糖咨询 — 饮食调整建议。"""
        result = _chat(client, "我体检血糖偏高，早上喝白粥吃油条是不是不太好？")
        assert result.get("reply")

    def test_9_midnight_snack(self, client: TestClient) -> None:
        """#9 深夜饿了 — 健康宵夜建议。"""
        result = _chat(client, "半夜饿了，有什么健康点儿的吃的推荐吗？")
        assert result.get("reply")

    def test_10_grocery_list(self, client: TestClient) -> None:
        """#10 买菜清单 — 按需生成采购计划。"""
        result = _chat(
            client,
            "帮我生成这周的买菜清单，两个人吃，五天的晚餐",
        )
        assert result.get("reply")


# ===================================================================
# 三、🏥 健康与身体（#11–#15）
# ===================================================================

class TestHealthAndBody:
    """Health advice, symptom triage, exercise data."""

    def test_11_headache(self, client: TestClient) -> None:
        """#11 头痛发作 — 症状分析与缓解建议。"""
        result = _chat(client, "头好痛，可能是盯屏幕太久了")
        assert result.get("reply")

    def test_12_running_analysis(self, client: TestClient) -> None:
        """#12 跑步记录分析 — 运动数据咨询。"""
        result = _chat(client, "我最近跑步配速6分半，是不是退步了？")
        assert result.get("reply")

    def test_13_insomnia(self, client: TestClient) -> None:
        """#13 失眠求助 — 助眠方法建议。"""
        result = _chat(client, "睡不着，试了好几种方法都没用")
        assert result.get("reply")

    def test_14_medication_reminder(self, client: TestClient) -> None:
        """#14 药物提醒 — 药食/酒精相互作用查询。"""
        result = _chat(client, "我今晚要喝酒，但早上刚吃了最后一粒阿奇霉素，有冲突吗？")
        assert result.get("reply")

    def test_15_mood_dip(self, client: TestClient) -> None:
        """#15 情绪低落 — 心理健康陪伴。"""
        result = _chat(client, "最近心情不太好，觉得什么事都没意思")
        assert result.get("reply")


# ===================================================================
# 四、🛒 购物与消费（#16–#20）
# ===================================================================

class TestShopping:
    """Shopping decisions, budgeting, price comparison."""

    def test_16_phone_dilemma(self, client: TestClient) -> None:
        """#16 买手机纠结 — 消费决策辅助。"""
        result = _chat(
            client,
            "手机A拍照好但续航差，手机B续航强但比较重，我该怎么选？",
        )
        assert result.get("reply")

    def test_17_sale_warning(self, client: TestClient) -> None:
        """#17 大促剁手预警 — 购物车优化建议。"""
        result = _chat(client, "双十一购物车堆了20多件东西，帮我看看哪些是真正需要的？")
        assert result.get("reply")

    def test_18_gift_idea(self, client: TestClient) -> None:
        """#18 买礼物没头绪 — 礼物推荐。"""
        result = _chat(client, "好朋友快生日了，预算300以内，她喜欢手作的东西，送什么好？")
        assert result.get("reply")

    def test_19_return_process(self, client: TestClient) -> None:
        """#19 退货流程太麻烦 — 退货指导。"""
        result = _chat(client, "买的台灯色温不对，但退货流程好复杂，不想退了")
        assert result.get("reply")

    def test_20_price_compare(self, client: TestClient) -> None:
        """#20 超市比价 — 线上线下价格对比决策。"""
        result = _chat(
            client,
            "帮我算算是在楼下超市买菜划算还是App下单划算？",
        )
        assert result.get("reply")


# ===================================================================
# 五、✈️ 出行与旅行（#21–#25）
# ===================================================================

class TestTravel:
    """Travel planning, navigation, flight issues."""

    def test_21_business_trip(self, client: TestClient) -> None:
        """#21 出差行程安排 — 行程规划。"""
        result = _chat(
            client,
            "下周二下午到上海出差，周四中午回，帮我规划一下行程和住宿",
        )
        assert result.get("reply")

    def test_22_flight_delayed(self, client: TestClient) -> None:
        """#22 航班延误了 — 改签策略。"""
        result = _chat(client, "航班延误了，能帮我看看有没有更早的航班可以改签吗？")
        assert result.get("reply")

    def test_23_travel_planner(self, client: TestClient) -> None:
        """#23 旅行规划师 — 旅行路线设计。"""
        result = _chat(
            client,
            "国庆想去云南，五天四晚，预算5000一个人，不想太累，求推荐",
        )
        assert result.get("reply")

    def test_24_lost(self, client: TestClient) -> None:
        """#24 迷路了 — 导航帮助。"""
        result = _chat(client, "我在一条小巷子里迷路了，面前是一个红色门的房子")
        assert result.get("reply")

    def test_25_jet_lag(self, client: TestClient) -> None:
        """#25 时差反应 — 生物钟调整建议。"""
        result = _chat(client, "从美国回来三天了，每天晚上7点困凌晨3点醒，时差好难受")
        assert result.get("reply")


# ===================================================================
# 六、💼 工作与效率（#26–#30）
# ===================================================================

class TestWorkAndProductivity:
    """Workplace scenarios, career advice, productivity."""

    def test_26_dont_want_to_work(self, client: TestClient) -> None:
        """#26 不想上班 — 任务分解与动力恢复。"""
        result = _chat(client, "周一早上完全不想上班，最不想写周报了")
        assert result.get("reply")

    def test_27_meeting_distraction(self, client: TestClient) -> None:
        """#27 开会走神被抓包 — 会议救场。"""
        result = _chat(client, "开会走神了，老板突然点名让我发言怎么办？")
        assert result.get("reply")

    def test_28_resume_review(self, client: TestClient) -> None:
        """#28 简历修改 — 职业发展咨询。"""
        result = _chat(client, "想跳槽，但感觉简历写得太平淡了，能帮我看看吗？")
        assert result.get("reply")

    def test_29_email_draft(self, client: TestClient) -> None:
        """#29 邮件写不好 — 职场邮件代写。"""
        result = _chat(
            client,
            "要写一封解释项目延期的邮件给客户，既要说明原因又不能让对方觉得我们不靠谱，帮我起草",
        )
        assert result.get("reply")

    def test_30_yearly_review(self, client: TestClient) -> None:
        """#30 年终总结凑字数 — 工作总结润色。"""
        result = _chat(client, "年终总结要写2000字，感觉今年没干什么大事，能帮我扩充一下吗？")
        assert result.get("reply")


# ===================================================================
# 七、🏠 家庭与生活管理（#31–#35）
# ===================================================================

class TestHomeManagement:
    """Home management, maintenance, cleaning."""

    def test_31_moving_mess(self, client: TestClient) -> None:
        """#31 搬家整理崩溃 — 整理计划建议。"""
        result = _chat(client, "搬家三天了还有5个箱子没拆，完全不想动了")
        assert result.get("reply")

    def test_32_high_utility_bill(self, client: TestClient) -> None:
        """#32 水电费异常 — 能源使用分析。"""
        result = _chat(client, "这个月电费贵了一倍，680块，是不是哪里有问题？")
        assert result.get("reply")

    def test_33_renovation_choice(self, client: TestClient) -> None:
        """#33 装修选择困难 — 设计方案咨询。"""
        result = _chat(
            client,
            "卫生间翻新，浅灰还是米白瓷砖？纠结三天了",
        )
        assert result.get("reply")

    def test_34_plant_care(self, client: TestClient) -> None:
        """#34 绿植养护 — 家庭园艺指导。"""
        result = _chat(client, "龟背竹叶子发黄了，是不是浇水太多了？")
        assert result.get("reply")

    def test_35_pet_unwell(self, client: TestClient) -> None:
        """#35 宠物不对劲 — 宠物健康紧急判断。"""
        result = _chat(client, "我家猫今天不吃不喝一直窝在角落，是不是生病了？")
        assert result.get("reply")


# ===================================================================
# 八、🎮 娱乐与休闲（#36–#40）
# ===================================================================

class TestEntertainment:
    """Entertainment recommendations, gaming, hobbies."""

    def test_36_binge_watch(self, client: TestClient) -> None:
        """#36 剧荒求助 — 影视推荐。"""
        result = _chat(client, "最近好无聊，有什么好看的剧推荐吗？")
        assert result.get("reply")

    def test_37_game_stuck(self, client: TestClient) -> None:
        """#37 游戏卡关 — 游戏攻略建议。"""
        result = _chat(client, "BOSS打了十几遍过不去，是不是我打法有问题？")
        assert result.get("reply")

    def test_38_book_choice(self, client: TestClient) -> None:
        """#38 读书选择 — 入门读物推荐。"""
        result = _chat(client, "半年没完整读完一本书了，推荐一本容易读进去的")
        assert result.get("reply")

    def test_39_learning_instrument(self, client: TestClient) -> None:
        """#39 学乐器受挫 — 学习方法建议。"""
        result = _chat(client, "自学尤克里里两周，和弦转换还是卡顿，我是不是没有音乐天赋？")
        assert result.get("reply")

    def test_40_photo_editing(self, client: TestClient) -> None:
        """#40 拍照修图 — 摄影后期建议。"""
        result = _chat(client, "拍了一张风景照但灰蒙蒙的，想要那种电影感色调")
        assert result.get("reply")


# ===================================================================
# 九、📚 学习与成长（#41–#45）
# ===================================================================

class TestLearningAndGrowth:
    """Learning, career development, personal growth."""

    def test_41_vocabulary_struggle(self, client: TestClient) -> None:
        """#41 背单词坚持不下去 — 学习方法调整。"""
        result = _chat(client, "每天背30个单词坚持了三天就断了，我是不是太没毅力了？")
        assert result.get("reply")

    def test_42_career_confusion(self, client: TestClient) -> None:
        """#42 职业方向迷茫 — 职业规划咨询。"""
        result = _chat(
            client,
            "工作三年了，感觉遇到了天花板，不知道要不要转产品经理",
        )
        assert result.get("reply")

    def test_43_reading_notes(self, client: TestClient) -> None:
        """#43 读书笔记整理 — 知识管理建议。"""
        result = _chat(client, "读完半本书感觉啥也没记住，怎么整理读书笔记比较好？")
        assert result.get("reply")

    def test_44_public_speaking(self, client: TestClient) -> None:
        """#44 公众演讲紧张 — 演讲焦虑缓解。"""
        result = _chat(client, "下周要在全公司做分享，上台就紧张发抖怎么办？")
        assert result.get("reply")

    def test_45_habit_forming(self, client: TestClient) -> None:
        """#45 习惯养成 — 喝水习惯培养。"""
        result = _chat(client, "总忘记喝水，一天喝不到800ml，有什么办法吗？")
        assert result.get("reply")


# ===================================================================
# 十、🤖 情感与陪伴（#46–#50）
# ===================================================================

class TestEmotionalCompanion:
    """Emotional support, companionship, deep talks."""

    def test_46_after_breakup(self, client: TestClient) -> None:
        """#46 分手后的夜晚 — 情感支持。"""
        result = _chat(client, "刚分手，晚上特别难熬")
        assert result.get("reply")

    def test_47_family_fight(self, client: TestClient) -> None:
        """#47 和家人吵架了 — 家庭矛盾调解。"""
        result = _chat(client, "刚和爸妈吵完架，又生气又内疚")
        assert result.get("reply")

    def test_48_loneliness(self, client: TestClient) -> None:
        """#48 孤独感突然袭来 — 孤独陪伴。"""
        result = _chat(client, "周末晚上一个人在家，突然觉得好孤独")
        assert result.get("reply")

    def test_49_birthday_surprise(self, client: TestClient) -> None:
        """#49 收到意外惊喜 — 日常惊喜互动。"""
        result = _chat(client, "今天有什么特别的吗？")
        assert result.get("reply")

    def test_50_midnight_philosophy(self, client: TestClient) -> None:
        """#50 深夜哲学 — 存在主义话题探讨。"""
        result = _chat(client, "你说，人活着的意义到底是什么？")
        assert result.get("reply")


# ===================================================================
# Additional — 库存管理专项场景（原文档中涉及物品操作的核心交互）
# 这些场景更充分地测试系统在物品管理、查询、操作方面的能力
# ===================================================================

class TestInventoryOperations:
    """Extended tests for core inventory operations — add, consume, update,
    query, remove — that exercise the full graph pipeline."""

    def test_add_single_item(self, client: TestClient) -> None:
        """买入一件物品，确认后验证入库。"""
        result = _chat(client, "我今天买了一把油麦菜，放冰箱下层")
        assert result.get("reply")
        assert result.get("needsConfirmation") in (True, None)
        if result.get("needsConfirmation"):
            _confirm_add(client, result)
            items = _current_items(client)
            assert any("油麦菜" in item["title"] for item in items)

    def test_add_multiple_items(self, client: TestClient) -> None:
        """批量买入多件物品。"""
        result = _chat(client, "买了三盒草莓和两瓶牛奶，都放冰箱")
        assert result.get("reply")
        if result.get("needsConfirmation"):
            _confirm_add(client, result)

    def test_consume_item(self, client: TestClient) -> None:
        """消耗一件已有物品。"""
        # First add it
        r1 = _chat(client, "买了一箱特仑苏牛奶，放厨房柜子里")
        assert r1.get("reply")
        if r1.get("needsConfirmation"):
            _confirm_add(client, r1)

        # Then consume one
        r2 = _chat(client, "喝了一盒特仑苏")
        assert r2.get("reply")

    def test_location_query(self, client: TestClient) -> None:
        """询问物品位置。"""
        result = _chat(client, "全麦面包放在哪了？")
        assert result.get("reply")

    def test_expiry_query(self, client: TestClient) -> None:
        """询问快过期物品。"""
        result = _chat(client, "有什么快过期的东西吗？")
        assert result.get("reply")

    def test_quantity_query(self, client: TestClient) -> None:
        """询问数量。"""
        result = _chat(client, "请问我们冰箱里还有多少鸡蛋？")
        assert result.get("reply")

    def test_update_location(self, client: TestClient) -> None:
        """更新物品存放位置。"""
        # First add 胡萝卜
        r1 = _chat(client, "买了胡萝卜，放冰箱下层")
        assert r1.get("reply")
        if r1.get("needsConfirmation"):
            _confirm_add(client, r1)

        # Then move it
        r2 = _chat(client, "把胡萝卜换到冰箱上层")
        assert r2.get("reply")

    def test_remove_item(self, client: TestClient) -> None:
        """扔掉/删除一件物品。"""
        r1 = _chat(client, "买了橘子，放客厅柜子里")
        assert r1.get("reply")
        if r1.get("needsConfirmation"):
            _confirm_add(client, r1)

        r2 = _chat(client, "橘子坏了，扔掉")
        assert r2.get("reply")

    def test_search_query(self, client: TestClient) -> None:
        """搜索物品。"""
        result = _chat(client, "找一下感冒药")
        assert result.get("reply")

    def test_recipe_recommendation(self, client: TestClient) -> None:
        """菜谱推荐。"""
        result = _chat(client, "帮我推荐个菜谱，用掉快要过期的东西")
        assert result.get("reply")

    def test_ambiguous_selection(self, client: TestClient) -> None:
        """歧义消除——两个相近物品需要用户选择。"""
        # Add two similar items
        r1 = _chat(client, "买了山姆全脂鲜奶，放冰箱冷藏层")
        if r1.get("needsConfirmation"):
            _confirm_add(client, r1)

        r2 = _chat(client, "买了特仑苏纯牛奶，放厨房柜子里")
        if r2.get("needsConfirmation"):
            _confirm_add(client, r2)

        # Ambiguous request
        r3 = _chat(client, "牛奶喝完了一盒")
        assert r3.get("reply")

    def test_escape_from_pending(self, client: TestClient) -> None:
        """在待选状态下取消操作。"""
        result = _chat(client, "算了，不要了")
        assert result.get("reply")


# ===================================================================
# Generate conversation transcript document
# ===================================================================

@pytest.fixture(scope="session", autouse=False)
def _output_doc():
    """Fixture that prepares the output document path.
    Not autouse — call explicitly when generating the doc."""
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    return OUTPUT_FILE


def _write_conversation_entry(client: TestClient, scenario_id: str, title: str,
                              user_text: str, assistant_reply: str) -> None:
    """Append one conversation turn to the output markdown document."""
    with open(OUTPUT_FILE, "a", encoding="utf-8") as f:
        f.write(f"\n### {scenario_id}：{title}\n\n")
        f.write(f"**🧑 用户**：{user_text}\n\n")
        f.write(f"**🤖 智能体**：{assistant_reply}\n\n")
        f.write("---\n")


# ===================================================================
# 独立生成脚本 —— 运行所有场景并输出对话文档
# ===================================================================

def run_all_scenarios_and_generate_doc() -> None:
    """Run every scenario through the actual chat endpoint and produce a
    complete conversation transcript at ``docs/daily-ai-test-results.md``.

    This function is designed to be invoked directly from a script:
        cd server && python -c "from tests.test_daily_scenarios import run_all_scenarios_and_generate_doc; run_all_scenarios_and_generate_doc()"
    """
    import warnings
    import sys
    # Fix console encoding for Windows
    if sys.stdout.encoding and sys.stdout.encoding.upper() in ("GBK", "GB2312", "CP936"):
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    warnings.filterwarnings("ignore", category=DeprecationWarning)

    client = TestClient(create_app())
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)

    scenarios = [
        # (id, title, user_text)
        # ── 晨间日常 ──
        ("#1",  "起床气", "再睡五分钟……"),
        ("#2",  "今天穿什么", "今天穿什么？"),
        ("#3",  "早餐营养师", "早餐吃什么？冰箱里有鸡蛋、番茄、菠菜"),
        ("#4",  "出门前检查", "我出门了！"),
        ("#5",  "通勤新闻速读", "今天有什么要闻吗？"),
        # ── 烹饪与饮食 ──
        ("#6",  "冰箱快空了", "冰箱里只剩鸡蛋、西兰花、黄油和快过期的牛奶了，能做什么？"),
        ("#7",  "招待朋友不翻车", "周末三个大人一个小孩来吃饭，帮我设计一个不容易翻车的菜单"),
        ("#8",  "营养控糖咨询", "我体检血糖偏高，早上喝白粥吃油条是不是不太好？"),
        ("#9",  "深夜饿了", "半夜饿了，有什么健康点儿的吃的推荐吗？"),
        ("#10", "买菜清单", "帮我生成这周的买菜清单，两个人吃，五天的晚餐"),
        # ── 健康与身体 ──
        ("#11", "头痛发作", "头好痛，可能是盯屏幕太久了"),
        ("#12", "跑步记录分析", "我最近跑步配速6分半，是不是退步了？"),
        ("#13", "失眠求助", "睡不着，试了好几种方法都没用"),
        ("#14", "药物提醒", "我今晚要喝酒，但早上刚吃了最后一粒阿奇霉素，有冲突吗？"),
        ("#15", "情绪低落", "最近心情不太好，觉得什么事都没意思"),
        # ── 购物与消费 ──
        ("#16", "买手机纠结", "手机A拍照好但续航差，手机B续航强但比较重，我该怎么选？"),
        ("#17", "大促剁手预警", "双十一购物车堆了20多件东西，帮我看看哪些是真正需要的？"),
        ("#18", "买礼物没头绪", "好朋友快生日了，预算300以内，她喜欢手作的东西，送什么好？"),
        ("#19", "退货流程太麻烦", "买的台灯色温不对，但退货流程好复杂，不想退了"),
        ("#20", "超市比价", "帮我算算是在楼下超市买菜划算还是App下单划算？"),
        # ── 出行与旅行 ──
        ("#21", "出差行程安排", "下周二下午到上海出差，周四中午回，帮我规划一下行程和住宿"),
        ("#22", "航班延误了", "航班延误了，能帮我看看有没有更早的航班可以改签吗？"),
        ("#23", "旅行规划师", "国庆想去云南，五天四晚，预算5000一个人，不想太累，求推荐"),
        ("#24", "迷路了", "我在一条小巷子里迷路了，面前是一个红色门的房子"),
        ("#25", "时差反应", "从美国回来三天了，每天晚上7点困凌晨3点醒，时差好难受"),
        # ── 工作与效率 ──
        ("#26", "不想上班", "周一早上完全不想上班，最不想写周报了"),
        ("#27", "开会走神被抓包", "开会走神了，老板突然点名让我发言怎么办？"),
        ("#28", "简历修改", "想跳槽，但感觉简历写得太平淡了，能帮我看看吗？"),
        ("#29", "邮件写不好", "要写一封解释项目延期的邮件给客户，既要说明原因又不能让对方觉得我们不靠谱，帮我起草"),
        ("#30", "年终总结凑字数", "年终总结要写2000字，感觉今年没干什么大事，能帮我扩充一下吗？"),
        # ── 家庭与生活管理 ──
        ("#31", "搬家整理崩溃", "搬家三天了还有5个箱子没拆，完全不想动了"),
        ("#32", "水电费异常", "这个月电费贵了一倍，680块，是不是哪里有问题？"),
        ("#33", "装修选择困难", "卫生间翻新，浅灰还是米白瓷砖？纠结三天了"),
        ("#34", "绿植养护", "龟背竹叶子发黄了，是不是浇水太多了？"),
        ("#35", "宠物不对劲", "我家猫今天不吃不喝一直窝在角落，是不是生病了？"),
        # ── 娱乐与休闲 ──
        ("#36", "剧荒求助", "最近好无聊，有什么好看的剧推荐吗？"),
        ("#37", "游戏卡关", "BOSS打了十几遍过不去，是不是我打法有问题？"),
        ("#38", "读书选择", "半年没完整读完一本书了，推荐一本容易读进去的"),
        ("#39", "学乐器受挫", "自学尤克里里两周，和弦转换还是卡顿，我是不是没有音乐天赋？"),
        ("#40", "拍照修图", "拍了一张风景照但灰蒙蒙的，想要那种电影感色调"),
        # ── 学习与成长 ──
        ("#41", "背单词坚持不下去", "每天背30个单词坚持了三天就断了，我是不是太没毅力了？"),
        ("#42", "职业方向迷茫", "工作三年了，感觉遇到了天花板，不知道要不要转产品经理"),
        ("#43", "读书笔记整理", "读完半本书感觉啥也没记住，怎么整理读书笔记比较好？"),
        ("#44", "公众演讲紧张", "下周要在全公司做分享，上台就紧张发抖怎么办？"),
        ("#45", "习惯养成", "总忘记喝水，一天喝不到800ml，有什么办法吗？"),
        # ── 情感与陪伴 ──
        ("#46", "分手后的夜晚", "刚分手，晚上特别难熬"),
        ("#47", "和家人吵架了", "刚和爸妈吵完架，又生气又内疚"),
        ("#48", "孤独感突然袭来", "周末晚上一个人在家，突然觉得好孤独"),
        ("#49", "生日惊喜", "今天有什么特别的吗？"),
        ("#50", "深夜哲学", "你说，人活着的意义到底是什么？"),
    ]

    # Write document header
    print(OUTPUT_FILE)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write(f"# 人与智能体的日常对话：50个场景测试结果\n\n")
        f.write(f"> 以下对话由测试程序 `test_daily_scenarios.py` 自动生成，\n")
        f.write(f"> 通过 `POST /api/chat` 接口向系统发送用户消息并记录回复。\n")
        f.write(f"> 测试日期：{date.today().isoformat()}\n\n")
        f.write("| # | 场景 | 状态 |\n")
        f.write("|---|------|------|\n")

    passed = 0
    failed = 0
    results_rows: list[str] = []

    for scenario_id, title, user_text in scenarios:
        try:
            result = _chat(client, user_text)
            reply = result.get("reply", "（无回复）")
            status = "✅"
            passed += 1
        except Exception as exc:
            reply = f"**测试异常**：{exc}"
            status = "❌"
            failed += 1

        # Append to summary table
        results_rows.append(f"| {scenario_id} | {title} | {status} |\n")

        # Append detailed conversation
        with open(OUTPUT_FILE, "a", encoding="utf-8") as f:
            f.write(f"| {scenario_id} | {title} | {status} |\n")

    # Rewrite summary table
    with open(OUTPUT_FILE, "r+", encoding="utf-8") as f:
        content = f.read()
        # Replace placeholder table with real data
        table_start = content.find("| # | 场景 | 状态 |")
        table_end = content.find("\n\n", table_start)
        if table_end == -1:
            table_end = len(content)
        new_content = (
            content[:table_start]
            + "| # | 场景 | 状态 |\n"
            + "|---|------|------|\n"
            + "".join(results_rows)
            + content[table_end:]
        )
        f.seek(0)
        f.write(new_content)
        f.truncate()

    # Append detailed conversation entries
    _reset(client)
    with open(OUTPUT_FILE, "a", encoding="utf-8") as f:
        f.write(f"\n## 详细对话\n\n")
        f.write(f"总计 **{passed + failed}** 个场景，通过 **{passed}**，失败 **{failed}**。\n\n")

    for scenario_id, title, user_text in scenarios:
        try:
            result = _chat(client, user_text)
            reply = result.get("reply", "（无回复）")
        except Exception as exc:
            reply = f"**测试异常**：{exc}"

        with open(OUTPUT_FILE, "a", encoding="utf-8") as f:
            f.write(f"### {scenario_id} {title}\n\n")
            f.write(f"**🧑 用户**：{user_text}\n\n")
            f.write(f"**🤖 智能体**：{reply}\n\n")
            f.write("---\n\n")

    with open(OUTPUT_FILE, "a", encoding="utf-8") as f:
        f.write(f"\n*报告自动生成于 {date.today().isoformat()} | 通过 {passed}/{passed + failed}*\n")

    print(f"\n✅ 对话文档已生成：{OUTPUT_FILE}")
    print(f"   通过 {passed}/{passed + failed} 个场景")


if __name__ == "__main__":
    run_all_scenarios_and_generate_doc()

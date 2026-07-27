r"""Comprehensive tests for all 50 Q&A scenarios against the /api/chat SSE endpoint.

Each scenario from q&a_demo.md is a multi-turn dialogue testing specific LangGraph
capabilities: atomic mutations, FIFO, ambiguity resolution, multi-member coordination,
spatial topology, and escape handling.

Usage:
    cd server
    uv run pytest tests/test_qa_50_scenarios.py -v --tb=short

Generate comparison report (runs all scenarios and produces expected-vs-actual doc):
    cd server
    uv run python -c "from tests.test_qa_50_scenarios import generate_qa_report; generate_qa_report()"
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings


# ---------------------------------------------------------------------------
# SSE Helpers
# ---------------------------------------------------------------------------

QA_DIR = Path(__file__).resolve().parent / "qa"
DEMO_FILE = QA_DIR / "q&a_demo.md"
REPORT_FILE = QA_DIR / "qa-test-results.md"


def _read_sse(response) -> dict[str, Any]:
    """Parse an SSE streaming response and return the last ``event: result`` payload."""
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
    inventory: list[dict] | None = None,
    user_name: str = "主人",
) -> dict[str, Any]:
    """Send a user message to /api/chat and return the SSE result payload."""
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
        payload["currentInventory"] = inventory
    resp = client.post("/api/chat", json=payload)
    assert resp.status_code == 200, f"Chat returned {resp.status_code}"
    assert resp.headers.get("content-type", "").startswith("text/event-stream")
    return _read_sse(resp)


def _confirm_add(client: TestClient, result: dict[str, Any]) -> dict[str, Any] | None:
    """Confirm a pending add operation."""
    if result.get("needsConfirmation") and result.get("pendingId"):
        pending_id = result["pendingId"]
        items = result.get("itemSuggestion", {}).get("items", [])
        cr = client.post(
            "/api/chat/confirm",
            json={"pendingId": pending_id, "items": items},
        )
        assert cr.status_code in (200, 404)
        return cr.json() if cr.status_code == 200 else None
    return None


def _confirm_consume(
    client: TestClient,
    result: dict[str, Any],
    selected_index: int = 0,
    consume_all: bool = False,
) -> dict[str, Any] | None:
    """Confirm a pending consume operation, selecting one candidate."""
    if result.get("needsConfirmation") and result.get("pendingId"):
        pending_id = result["pendingId"]
        cr = client.post(
            "/api/chat/consume-confirm",
            json={
                "pendingId": pending_id,
                "selectedIndex": selected_index,
                "consumeAll": consume_all,
            },
        )
        assert cr.status_code in (200, 404)
        return cr.json() if cr.status_code == 200 else None
    return None


def _current_items(client: TestClient) -> list[dict[str, Any]]:
    return client.get("/api/items").json()["items"]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    """Give each scenario isolated SQLite, Markdown, and vector-store paths."""
    monkeypatch.setattr(settings, "data_dir", tmp_path / "data")
    monkeypatch.setattr(settings, "storage_dir", tmp_path / "storage")
    monkeypatch.setattr(settings, "chroma_enabled", False)

    # Import only after overriding settings: app.main creates a global app on import.
    from app.main import create_app
    from app.services.vector_store import vector_store

    monkeypatch.setattr(vector_store, "_collection", None)

    with TestClient(create_app()) as test_client:
        yield test_client


def test_client_uses_isolated_storage(client: TestClient, tmp_path: Path) -> None:
    """The QA suite must never write to configured development storage."""
    from app.services.vector_store import vector_store

    assert settings.database_path == tmp_path / "data" / "squirrel.sqlite3"
    assert settings.database_path.exists()
    assert settings.storage_dir == tmp_path / "storage"
    assert not vector_store.enabled


# ===================================================================
# Scenario Data Definitions
#
# Each scenario is a dict with:
#   id       - scenario number string
#   title    - scenario name
#   category - category label
#   turns    - list of turn dicts:
#       text         - user message
#       user_name    - who is speaking
#       expected     - list of keywords that must appear in the reply
#       not_expected - list of keywords that must NOT appear (optional)
#       action       - post-chat action: "confirm_add" / "confirm_consume_N" /
#                      "confirm_consume_all" / "" (default)
# ===================================================================

CATEGORY_1 = "一、常规物资增删改存（1-10）"
CATEGORY_2 = "二、FIFO与保质期博弈（11-20）"
CATEGORY_3 = "三、多意图歧义消除（21-30）"
CATEGORY_4 = "四、多家庭成员协同（31-38）"
CATEGORY_5 = "五、空间拓扑与移动（39-44）"
CATEGORY_6 = "六、强中断与异常容错（45-50）"

SCENARIOS: list[dict[str, Any]] = [
    # ===================================================================
    # 一、常规物资增删改存与突发变动（1-10）
    # ===================================================================
    {
        "id": "1",
        "title": "干净的单品增量入库",
        "category": CATEGORY_1,
        "turns": [
            {"text": "我刚买了两盒草莓，放进冰箱冷藏层了。", "user_name": "老公", "expected": ["草莓"], "action": "confirm_add"},
            {"text": "每盒大概有500克，你把备注加上。", "user_name": "老公", "expected": ["备注"]},
            {"text": "保质期一般是3天，算一下什么时候过期？", "user_name": "老公", "expected": ["3天", "过期"]},
            {"text": "帮我看看冷藏层里还有别的盘装生鲜吗？", "user_name": "老公", "expected": ["冷藏层"]},
            {"text": "知道了，草莓洗一盒下午吃。", "user_name": "老公", "expected": ["草莓"]},
        ],
    },
    {
        "id": "2",
        "title": "顺手消耗与库存实时唱空",
        "category": CATEGORY_1,
        "turns": [
            {"text": "我刚把厨房二级柜里最后那一盒特仑苏牛奶喝了。", "user_name": "老婆", "expected": ["特仑苏"]},
            {"text": "现在二级柜里牛奶是不是空了？", "user_name": "老婆", "expected": ["空"]},
            {"text": "那柜子里还剩什么饮料吗？", "user_name": "老婆", "expected": ["可乐", "矿泉水"]},
            {"text": "把特仑苏加入我们的未来采购清单。", "user_name": "老婆", "expected": ["采购"]},
            {"text": "顺便查查冰箱里还有没有别的牌子的鲜奶？", "user_name": "老婆", "expected": ["鲜奶"]},
        ],
    },
    {
        "id": "3",
        "title": "批量大采购分类合并入库",
        "category": CATEGORY_1,
        "turns": [
            {"text": "刚去超市大采购回来，买了3包吐司放面包机旁，5瓶可乐放冰箱。", "user_name": "老公", "expected": ["吐司", "可乐"], "action": "confirm_add"},
            {"text": "等等，可乐里有2瓶是无糖的，放柜子里了。", "user_name": "老公", "expected": ["无糖"]},
            {"text": "吐司的保质期是到下周一。", "user_name": "老公", "expected": ["下周一"]},
            {"text": "家里现在一共有多少瓶可乐了？", "user_name": "老公", "expected": ["可乐"]},
            {"text": "帮我看看吐司还能放几天？", "user_name": "老公", "expected": ["吐司"]},
        ],
    },
    {
        "id": "4",
        "title": "模糊计量单位的日常扣减",
        "category": CATEGORY_1,
        "turns": [
            {"text": "晚饭做菜用了大半袋面粉。", "user_name": "老婆", "expected": ["面粉"]},
            {"text": "还剩0.3袋啊，那大概还够做一次饼吗？", "user_name": "老婆", "expected": ["面粉"]},
            {"text": "那我再开一袋新的。", "user_name": "老婆", "expected": ["面粉"]},
            {"text": "刚才那一小袋用完的空袋子我扔了。", "user_name": "老婆", "expected": ["面粉"]},
            {"text": "家里还有几袋囤着的面粉？", "user_name": "老婆", "expected": ["面粉"]},
        ],
    },
    {
        "id": "5",
        "title": "小票/清单识别后的人工补充",
        "category": CATEGORY_1,
        "turns": [
            {"text": "管家，这是刚才美团外卖送来的账单，你帮我记一下。买了鸡蛋30枚、生菜1包。", "user_name": "老公", "expected": ["鸡蛋", "生菜"], "action": "confirm_add"},
            {"text": "鸡蛋放蛋格，生菜放蔬菜保鲜盒。", "user_name": "老公", "expected": ["蛋格"]},
            {"text": "生菜好像比较容易坏，帮我设置4天后提醒吃。", "user_name": "老公", "expected": ["4天"]},
            {"text": "原本蛋格里还有几个剩的鸡蛋吗？", "user_name": "老公", "expected": ["鸡蛋"]},
            {"text": "好吧，那过会儿提醒我先把那3个旧的吃了。", "user_name": "老公", "expected": ["旧"]},
        ],
    },
    {
        "id": "6",
        "title": "突发损坏导致的物资全额报废",
        "category": CATEGORY_1,
        "turns": [
            {"text": "哎呀，我不小心把刚买的那瓶橄榄油打碎在地板上了。", "user_name": "老婆", "expected": ["橄榄油"]},
            {"text": "我没事，就是可惜了这瓶油。家里还有备用的油吗？", "user_name": "老婆", "expected": ["花生油"]},
            {"text": "花生油太重了，帮我把橄榄油加到外卖清单里。", "user_name": "老婆", "expected": ["橄榄油"]},
            {"text": "地上全都是油，顺便帮我查查厨房纸巾放哪了？", "user_name": "老婆", "expected": ["纸巾"]},
            {"text": "用掉了1卷纸巾，你扣掉吧。", "user_name": "老婆", "expected": ["纸巾"]},
        ],
    },
    {
        "id": "7",
        "title": "聚会备货——大批量特定物资追加",
        "category": CATEGORY_1,
        "turns": [
            {"text": "周末朋友要来家里聚会，我一口气买了24罐青岛啤酒。", "user_name": "老公", "expected": ["青岛啤酒"], "action": "confirm_add"},
            {"text": "把其中12罐塞进冰箱冰镇，剩下的留在储物角。", "user_name": "老公", "expected": ["冰箱", "储物角"]},
            {"text": "原本冰箱里应该还有几罐百威吧？", "user_name": "老公", "expected": ["百威"]},
            {"text": "百威也打上「周末聚会」标签，别被我一个人喝了。", "user_name": "老公", "expected": ["聚会"]},
            {"text": "太棒了，帮我算算这么多啤酒够6个人喝吗？", "user_name": "老公", "expected": ["啤酒"]},
        ],
    },
    {
        "id": "8",
        "title": "零食开封后的状态与位置变更",
        "category": CATEGORY_1,
        "turns": [
            {"text": "我把那袋大包装的乐事薯片打开吃了。", "user_name": "老婆", "expected": ["乐事"]},
            {"text": "没吃完，我用夹子夹起来放客厅茶几上了。", "user_name": "老婆", "expected": ["茶几"]},
            {"text": "开封后这种天气几天内会皮掉？", "user_name": "老婆", "expected": ["小时"]},
            {"text": "那茶几上还有别的开封零食吗？我顺便一起消灭掉。", "user_name": "老婆", "expected": ["茶几"]},
            {"text": "趣多多那我顺便拿过来了，现在两个都在茶几上。", "user_name": "老婆", "expected": ["茶几"]},
        ],
    },
    {
        "id": "9",
        "title": "漏报补登——回忆几天前的消耗",
        "category": CATEGORY_1,
        "turns": [
            {"text": "管家，我记性不好。前天晚上其实我偷偷把最后一盒冰淇淋吃掉了，当时忘了说。", "user_name": "老公", "expected": ["冰淇淋"]},
            {"text": "那昨天老婆在系统里查的时候，是不是显示还有一盒？", "user_name": "老公", "expected": ["错误"]},
            {"text": "老婆发现了吗？她昨天有没有去冰箱拿？", "user_name": "老公", "expected": ["老婆"]},
            {"text": "那就好。你赶紧在外卖清单里帮我补一盒一模一样的。", "user_name": "老公", "expected": ["补货"]},
            {"text": "谢谢管家，这件事要保密。", "user_name": "老公", "expected": ["保密"]},
        ],
    },
    {
        "id": "10",
        "title": "临时借用与归还管理",
        "category": CATEGORY_1,
        "turns": [
            {"text": "隔壁邻居小张来借了一整瓶生抽酱油。", "user_name": "老婆", "expected": ["生抽"]},
            {"text": "我们自己做饭还有生抽用吗？", "user_name": "老婆", "expected": ["生抽"]},
            {"text": "过了两天，小张把酱油还回来了。", "user_name": "老婆", "expected": ["归还"]},
            {"text": "他带回来的是个全新未开封的吗？", "user_name": "老婆", "expected": ["确认"]},
            {"text": "是的，原样奉还的。", "user_name": "老婆", "expected": ["归档"]},
        ],
    },
    # ===================================================================
    # 二、先进先出（FIFO）与保质期深度博弈（11-20）
    # ===================================================================
    {
        "id": "11",
        "title": "喝牛奶触发临期批次自动扣减",
        "category": CATEGORY_2,
        "turns": [
            {"text": "冰箱里的鲜奶我喝了一瓶。", "user_name": "老公", "expected": ["鲜奶"]},
            {"text": "那我刚刚喝的这瓶是不是明天就过期了？", "user_name": "老公", "expected": ["过期"]},
            {"text": "那冰箱里剩下那一瓶还能放几天？", "user_name": "老公", "expected": ["天"]},
            {"text": "帮我设置个提醒，在剩下那一瓶过期的前一天叫我。", "user_name": "老公", "expected": ["提醒"]},
            {"text": "太靠谱了。如果我老婆问起，你就让她优先喝那一瓶。", "user_name": "老公", "expected": ["老婆"]},
        ],
    },
    {
        "id": "12",
        "title": "查面包保质期并直接触发临期消耗",
        "category": CATEGORY_2,
        "turns": [
            {"text": "管家，厨房面包机旁边的全麦面包还有几天过期？", "user_name": "老婆", "expected": ["全麦面包"]},
            {"text": "啊！那我现在就把它当早饭吃了2片。", "user_name": "老婆", "expected": ["全麦面包"]},
            {"text": "那一袋里面一共还剩几片？", "user_name": "老婆", "expected": ["片"]},
            {"text": "老公起床后让他把剩下的3片全解决掉。", "user_name": "老婆", "expected": ["老公"]},
            {"text": "如果他吃了，系统会自动扣掉吧？", "user_name": "老婆", "expected": ["核销"]},
        ],
    },
    {
        "id": "13",
        "title": "新旧批次混杂时的保质期精准更新",
        "category": CATEGORY_2,
        "turns": [
            {"text": "系统里有两批午餐肉罐头对吧？我想改一下它们的保质期。", "user_name": "老公", "expected": ["午餐肉"]},
            {"text": "改后面那批刚买的5罐的，它们是到2028年5月才过期。", "user_name": "老公", "expected": ["2028"]},
            {"text": "顺便帮我确认下，如果我今天晚上开一罐，系统会默认开哪一批？", "user_name": "老公", "expected": ["老库存"]},
            {"text": "好，那帮我拿出一罐老库存放在灶台上准备晚上做菜。", "user_name": "老公", "expected": ["灶台"]},
            {"text": "那老库存就只剩2罐了是吧？", "user_name": "老公", "expected": ["2罐"]},
        ],
    },
    {
        "id": "14",
        "title": "询问最急需消耗的食材并顺接做菜",
        "category": CATEGORY_2,
        "turns": [
            {"text": "管家，现在厨房和冰箱里哪些东西最急着吃掉？", "user_name": "老婆", "expected": ["过期"]},
            {"text": "帮我生成菜单。", "user_name": "老婆", "expected": ["菜谱"]},
            {"text": "听起来不错，还需要别的配料吗？", "user_name": "老婆", "expected": ["配料"]},
            {"text": "好，那我把全麦面包和肥牛卷都用完了。", "user_name": "老婆", "expected": ["核销"]},
            {"text": "刚才那一盘肥牛卷是不是彻底没了？", "user_name": "老婆", "expected": ["肥牛"]},
        ],
    },
    {
        "id": "15",
        "title": "临期提醒触发的紧急转赠或处理",
        "category": CATEGORY_2,
        "turns": [
            {"text": "系统刚才弹窗说我上个月买的那箱车厘子快过期了？", "user_name": "老公", "expected": ["车厘子"]},
            {"text": "太多了根本吃不完，我全拿去送给公司同事了。", "user_name": "老公", "expected": ["转赠"]},
            {"text": "这样的话，水果区彻底空了吗？", "user_name": "老公", "expected": ["清空"]},
            {"text": "那等会儿下班我再去买点新鲜的苹果和橙子吧。", "user_name": "老公", "expected": ["苹果"]},
            {"text": "帮我把苹果和橙子先写在临时备忘里。", "user_name": "老公", "expected": ["备忘"]},
        ],
    },
    {
        "id": "16",
        "title": "冷冻层肉类超长保质期错觉纠正",
        "category": CATEGORY_2,
        "turns": [
            {"text": "管家，冰箱底层冷冻室里是不是还有两块牛排？能查到是什么时候放进去的吗？", "user_name": "老婆", "expected": ["牛排"]},
            {"text": "啊？冷冻不是可以放好几年吗？这还能吃吗？", "user_name": "老婆", "expected": ["冷冻"]},
            {"text": "天哪，那听你的，帮我把这两块牛排彻底扔了。", "user_name": "老婆", "expected": ["牛排"]},
            {"text": "冷冻室里还有其他放了超过半年的僵尸肉吗？", "user_name": "老婆", "expected": ["五花肉"]},
            {"text": "那块五花肉也一起扔掉吧，以后冷冻层超过半年的自动飘红提醒我。", "user_name": "老婆", "expected": ["提醒"]},
        ],
    },
    {
        "id": "17",
        "title": "发现过期物资并进行一键清退",
        "category": CATEGORY_2,
        "turns": [
            {"text": "管家，帮我检索全屋所有已经过期的东西，我今天大扫除。", "user_name": "老公", "expected": ["过期"]},
            {"text": "全扔了，一个不留。", "user_name": "老公", "expected": ["清退"]},
            {"text": "沙拉酱扔了的话，冰箱里还有其他开封的调味酱吗？", "user_name": "老公", "expected": ["番茄酱"]},
            {"text": "那曲奇饼干扔了，客厅零食柜里还有啥？", "user_name": "老公", "expected": ["海苔"]},
            {"text": "漂亮，今天的过期清退任务算完成了。", "user_name": "老公", "expected": ["零过期"]},
        ],
    },
    {
        "id": "18",
        "title": "相同SKU不同生产日期的精确核对",
        "category": CATEGORY_2,
        "turns": [
            {"text": "管家，系统里显示我有两袋同样的泰国香米，对吧？", "user_name": "老婆", "expected": ["泰国香米"]},
            {"text": "我看了一下袋子，一袋是2025年10月产的，另一袋是2026年3月产的。", "user_name": "老婆", "expected": ["批次"]},
            {"text": "现在正在吃的是那一袋2025年的。", "user_name": "老婆", "expected": ["2025"]},
            {"text": "如果这袋吃完了，你要提醒我那一袋新的。", "user_name": "老婆", "expected": ["提醒"]},
            {"text": "这袋旧的还剩大概四分之一。", "user_name": "老婆", "expected": ["四分之一"]},
        ],
    },
    {
        "id": "19",
        "title": "囤货期未满但品质下降的提前扣减",
        "category": CATEGORY_2,
        "turns": [
            {"text": "管家，放在阳台储物箱里的那箱苹果，虽然还没到过期时间，但有几个已经烂了。", "user_name": "老公", "expected": ["苹果"]},
            {"text": "一共烂了4个，我都挑出来扔了。", "user_name": "老公", "expected": ["4"]},
            {"text": "剩下的苹果看起来也有点蔫了，怎么办？", "user_name": "老公", "expected": ["冰箱"]},
            {"text": "好主意，我已经把剩下的12个苹果全部挪进冰箱蔬菜室了。", "user_name": "老公", "expected": ["12"]},
            {"text": "那这两天记得提醒全家吃苹果。", "user_name": "老公", "expected": ["提醒"]},
        ],
    },
    {
        "id": "20",
        "title": "婴儿奶粉多批次开封时效倒计时",
        "category": CATEGORY_2,
        "turns": [
            {"text": "管家，宝宝的爱他美奶粉3段，今天我新开了一罐。", "user_name": "老婆", "expected": ["爱他美"]},
            {"text": "那原来那一罐没吃完的呢？", "user_name": "老婆", "expected": ["旧奶粉"]},
            {"text": "旧的里面其实就剩最后底下一两勺的量了，我刚才直接倒掉把罐子洗了。", "user_name": "老婆", "expected": ["清零"]},
            {"text": "所以现在就只有今天新开的这一罐在吃对吧？", "user_name": "老婆", "expected": ["30天"]},
            {"text": "储藏间里还有未开封的存货吗？", "user_name": "老婆", "expected": ["囤货"]},
        ],
    },
    # ===================================================================
    # 三、多意图交织与歧义多候选消除（21-30）
    # ===================================================================
    {
        "id": "21",
        "title": "牛奶喝了触发多库候选集精准多选一",
        "category": CATEGORY_3,
        "turns": [
            {"text": "牛奶喝完了一盒。", "user_name": "老公", "expected": ["选择"]},
            {"text": "1", "user_name": "老公", "expected": ["山姆"]},
            {"text": "那山姆鲜奶还剩多少了？", "user_name": "老公", "expected": ["山姆"]},
            {"text": "特仑苏那边没人动过吧？", "user_name": "老公", "expected": ["特仑苏"]},
            {"text": "行，明天提醒我买新牛奶。", "user_name": "老公", "expected": ["提醒"]},
        ],
    },
    {
        "id": "22",
        "title": "名字极度相似物品的单选排除",
        "category": CATEGORY_3,
        "turns": [
            {"text": "我拿了一罐可乐。", "user_name": "老婆", "expected": ["选择"]},
            {"text": "我要减肥，当然是拿无糖的那个。", "user_name": "老婆", "expected": ["无糖"]},
            {"text": "地柜里无糖的还剩几罐？", "user_name": "老婆", "expected": ["2罐"]},
            {"text": "把剩下的2罐无糖的也顺手帮我塞进冰箱冷藏层。", "user_name": "老婆", "expected": ["冰箱"]},
            {"text": "太好了，现在的冰箱冷藏层里是不是两种可乐都有了？", "user_name": "老婆", "expected": ["经典", "无糖"]},
        ],
    },
    {
        "id": "23",
        "title": "输入非标序号的智能纠偏",
        "category": CATEGORY_3,
        "turns": [
            {"text": "把大米搬到阳台。", "user_name": "老公", "expected": ["选择"]},
            {"text": "第一个，重的那个。", "user_name": "老公", "expected": ["五常大米"]},
            {"text": "阳台那边干燥吗？适合放米吗？", "user_name": "老公", "expected": ["防潮"]},
            {"text": "放进阳台的防虫储物箱里了，你在系统里备注下。", "user_name": "老公", "expected": ["防虫"]},
            {"text": "那吊柜里那个赠品小糯米还在对吧？", "user_name": "老公", "expected": ["糯米"]},
        ],
    },
    {
        "id": "24",
        "title": "多选一过程中突然变更数量",
        "category": CATEGORY_3,
        "turns": [
            {"text": "把番茄拿出来。", "user_name": "老婆", "expected": ["选择"]},
            {"text": "第二个，我一口气拿了3个做番茄炒蛋。", "user_name": "老婆", "expected": ["3"]},
            {"text": "剩下的2个番茄看着还新鲜吗？", "user_name": "老婆", "expected": ["番茄"]},
            {"text": "那我明天晚上把它们也做汤用了。", "user_name": "老婆", "expected": ["番茄"]},
            {"text": "小番茄没动吧？", "user_name": "老婆", "expected": ["圣女果"]},
        ],
    },
    {
        "id": "25",
        "title": "用户选择全部后的批量属性覆盖",
        "category": CATEGORY_3,
        "turns": [
            {"text": "帮我把家里的苏打水全部移到客厅。", "user_name": "老公", "expected": ["选择"]},
            {"text": "全部，两批一起挪过去。", "user_name": "老公", "expected": ["9瓶"]},
            {"text": "现在客厅一共有9瓶了是吧？", "user_name": "老公", "expected": ["9"]},
            {"text": "冰箱里是不是就没有苏打水了？", "user_name": "老公", "expected": ["清空"]},
            {"text": "那我拿2瓶放客厅的小茶几上随手喝。", "user_name": "老公", "expected": ["茶几"]},
        ],
    },
    {
        "id": "26",
        "title": "跨轮次完全省略主语的追问",
        "category": CATEGORY_3,
        "turns": [
            {"text": "家里那两个空气净化器滤芯放在哪？", "user_name": "老婆", "expected": ["滤芯"]},
            {"text": "把主卧那个拿给我。", "user_name": "老婆", "expected": ["主卧"]},
            {"text": "那另一个呢？", "user_name": "老婆", "expected": ["客厅"]},
            {"text": "把它也拿到主卧来备用。", "user_name": "老婆", "expected": ["主卧"]},
            {"text": "所以现在主卧一共有两个滤芯了对吧？", "user_name": "老婆", "expected": ["两个"]},
        ],
    },
    {
        "id": "27",
        "title": "名字相同但位置不同的物资精准调配",
        "category": CATEGORY_3,
        "turns": [
            {"text": "把洗手液消耗一瓶。", "user_name": "老公", "expected": ["选择"]},
            {"text": "1号主卫的，彻底用空挤不出来了。", "user_name": "老公", "expected": ["主卫"]},
            {"text": "主卧储藏间里有全新洗手液的囤货可以补充吗？", "user_name": "老公", "expected": ["洗手液"]},
            {"text": "拿一瓶新的补到主卫去。", "user_name": "老公", "expected": ["主卫"]},
            {"text": "储藏间里是不是只剩1瓶备用的了？", "user_name": "老公", "expected": ["1瓶"]},
        ],
    },
    {
        "id": "28",
        "title": "模糊多选项中夹杂无效回复的容错",
        "category": CATEGORY_3,
        "turns": [
            {"text": "我把那包薯片吃了。", "user_name": "老婆", "expected": ["选择"]},
            {"text": "哎呀我突然想起来我今天好饿啊。", "user_name": "老婆", "expected": ["乐事"]},
            {"text": "我吃的是绿颜色的那个乐事。", "user_name": "老婆", "expected": ["乐事"]},
            {"text": "那茶几上那个黄颜色的呢？", "user_name": "老婆", "expected": ["上好佳"]},
            {"text": "算了，留着明天吃吧。", "user_name": "老婆", "expected": ["明天"]},
        ],
    },
    {
        "id": "29",
        "title": "连续否定候选集后的重新检索",
        "category": CATEGORY_3,
        "turns": [
            {"text": "我刚把那盒巧克力给吃了。", "user_name": "老公", "expected": ["选择"]},
            {"text": "都不是，是我情人节藏在书房抽屉里的那盒手工巧克力。", "user_name": "老公", "expected": ["手工巧克力"]},
            {"text": "哈哈，这个你也能记下来啊。", "user_name": "老公", "expected": ["建档"]},
            {"text": "那冰箱侧门那个德芙还在吧？", "user_name": "老公", "expected": ["德芙"]},
            {"text": "行，别告诉我老婆书房巧克力的事。", "user_name": "老公", "expected": ["保密"]},
        ],
    },
    {
        "id": "30",
        "title": "拼音缩写或错别字引发的候选集匹配",
        "category": CATEGORY_3,
        "turns": [
            {"text": "我煮了一包wdn吃。", "user_name": "老婆", "expected": ["乌冬面"]},
            {"text": "对对对，就是乌冬面，拼音你都懂。", "user_name": "老婆", "expected": ["乌冬面"]},
            {'text': '顺便帮我查查，煮面用的番茄酱有吗？我字打错了变成了"番切将"。', "user_name": "老婆", "expected": ["番茄酱"]},
            {"text": "太聪明了。那我用了一点番茄酱。", "user_name": "老婆", "expected": ["番茄酱"]},
            {"text": "乌冬面还剩2包，够吃几顿？", "user_name": "老婆", "expected": ["2包"]},
        ],
    },
    # ===================================================================
    # 四、多家庭成员并发协同与囤货拦截（31-38）
    # ===================================================================
    {
        "id": "31",
        "title": "老公重复买物资，系统触发防囤货拦截",
        "category": CATEGORY_4,
        "turns": [
            {"text": "老婆，我刚在楼下超市又提了一箱山姆全脂鲜奶回来，入库一下。", "user_name": "老公", "expected": ["鲜奶"], "action": "confirm_add"},
            {"text": "啊？她已经买了吗？那我这箱怎么办，能退吗？", "user_name": "老公", "expected": ["退"]},
            {"text": "太险了，幸好你提醒我，我现在就下楼去退掉。这笔入库先算了。", "user_name": "老公", "expected": ["取消"]},
            {"text": "退完了。帮我查查我老婆外卖买的那箱放冰箱了吗？", "user_name": "老公", "expected": ["冰箱"]},
            {"text": "好，那我今晚回家直接喝我老婆买的那箱。", "user_name": "老公", "expected": ["老婆"]},
        ],
    },
    {
        "id": "32",
        "title": "老婆消耗了老公刚买的特色零食",
        "category": CATEGORY_4,
        "turns": [
            {"text": "老公放在茶几上那盒黑巧克力被我吃光了。", "user_name": "老婆", "expected": ["巧克力"]},
            {"text": "我老公今天晚上回来查，会看到是谁吃的吗？", "user_name": "老婆", "expected": ["记录"]},
            {"text": "哈哈不用，你就跟他说是我吃的。顺便帮我查查，他还有没有藏别的零食？", "user_name": "老婆", "expected": ["腰果"]},
            {"text": "腰果我也拿走了，放客厅茶几。", "user_name": "老婆", "expected": ["腰果"]},
            {"text": "这样他回家一眼就能看到，哈哈。", "user_name": "老婆", "expected": ["茶几"]},
        ],
    },
    {
        "id": "33",
        "title": "两个人都声称自己打翻了同一个酱油瓶",
        "category": CATEGORY_4,
        "turns": [
            {"text": "完蛋了，我把厨房那瓶生抽酱油打碎了。", "user_name": "老公", "expected": ["生抽"]},
            {"text": "管家，厨房里那瓶生抽酱油刚才被打碎了，清掉吧。", "user_name": "老婆", "expected": ["空仓"]},
            {"text": "哦，原来他已经跟你说过了啊，他在清理现场吗？", "user_name": "老婆", "expected": ["老公"]},
            {"text": "那赶紧帮我们在外卖买一个，做晚饭要用。", "user_name": "老婆", "expected": ["采购"]},
            {"text": "我已经在手机上点好外卖了，大概20分钟送达。", "user_name": "老婆", "expected": ["送达"]},
        ],
    },
    {
        "id": "34",
        "title": "备忘录共享——多租户合力补充采购清单",
        "category": CATEGORY_4,
        "turns": [
            {'text': '管家，在周末采购清单里加上"手撕面包"。', "user_name": "老公", "expected": ["手撕面包"]},
            {'text': '管家，我也要在采购清单里加东西，帮我加上"维达卷纸一箱"。', "user_name": "老婆", "expected": ["卷纸"]},
            {"text": "帮我看看清单里还有别的东西吗？上次加的苹果还在吗？", "user_name": "老公", "expected": ["苹果"]},
            {"text": "卷纸改成买两箱，一箱放主卫，一箱放客卫。", "user_name": "老婆", "expected": ["两箱"]},
            {"text": "行，这份清单下午发到我微信，我去超市照着买。", "user_name": "老公", "expected": ["清单"]},
        ],
    },
    {
        "id": "35",
        "title": "家庭聚会分工——确认谁负责消耗什么",
        "category": CATEGORY_4,
        "turns": [
            {"text": "周末朋友聚会剩了好多熟食，系统里有记录吗？", "user_name": "老婆", "expected": ["烤鸭"]},
            {"text": "那分工一下，老公负责今天中午把烤鱼吃了，我负责吃烤鸭。", "user_name": "老婆", "expected": ["烤鱼", "烤鸭"]},
            {"text": "管家，我中午想随便吃点，冰箱里有什么是指定给我的吗？", "user_name": "老公", "expected": ["烤鱼"]},
            {"text": "啊？为什么要我吃烤鱼，我想吃烤鸭。", "user_name": "老公", "expected": ["老婆"]},
            {"text": "行吧，听老婆的，那我把烤鱼拿出来热了吃了，你扣掉吧。", "user_name": "老公", "expected": ["烤鱼"]},
        ],
    },
    {
        "id": "36",
        "title": "抢零食场景——两人同时宣告所有权",
        "category": CATEGORY_4,
        "turns": [
            {"text": "零食柜里最后一盒坚果是我的了，我带去办公室。", "user_name": "老公", "expected": ["坚果"]},
            {"text": "等一下！那盒坚果我昨晚就预定了，不许他带走。", "user_name": "老婆", "expected": ["坚果"]},
            {"text": "算了算了，好男不跟女斗，留给老婆吃吧。", "user_name": "老公", "expected": ["老婆"]},
            {"text": "这还差不多。管家，帮我把它加到外卖单里，帮老公再买一盒一模一样的。", "user_name": "老婆", "expected": ["补货"]},
            {"text": "谢谢老婆，管家你赶紧下单吧。", "user_name": "老公", "expected": ["订单"]},
        ],
    },
    {
        "id": "37",
        "title": "错记库位——老婆在冰箱找老公放进柜子的东西",
        "category": CATEGORY_4,
        "turns": [
            {"text": "管家，冰箱里我怎么找不到昨天买的那袋开心果了？", "user_name": "老婆", "expected": ["开心果"]},
            {"text": "老公！你为什么把开心果放电视柜里啊，真是气死我了。", "user_name": "老婆", "expected": ["电视柜"]},
            {"text": "我找到了，我现在把它拿出来放到厨房零食框里，冰箱放不下了。", "user_name": "老婆", "expected": ["零食框"]},
            {"text": "电视柜抽屉里被他腾空了吗？里面还剩啥？", "user_name": "老婆", "expected": ["空"]},
            {"text": "行，那以后那个抽屉不许他乱放食物。", "user_name": "老婆", "expected": ["标签"]},
        ],
    },
    {
        "id": "38",
        "title": "财务/成本感知——重复购买触发预算警告",
        "category": CATEGORY_4,
        "turns": [
            {"text": "管家，我又网购了一整箱依云矿泉水，帮我入库。", "user_name": "老公", "expected": ["依云"], "action": "confirm_add"},
            {"text": "啊？已经买过这么多了吗？我看网上打折便宜就忍不住下单了。", "user_name": "老公", "expected": ["囤货"]},
            {"text": "那能取消订单吗？还没发货。", "user_name": "老公", "expected": ["退款"]},
            {"text": "好，我已经成功申请退款了。系统里的那两箱存货够我喝到下个月吧？", "user_name": "老公", "expected": ["够"]},
            {"text": "太感谢了，以后这种超额囤货打折货，你一定要像今天这样拼命拦住我。", "user_name": "老公", "expected": ["拦住"]},
        ],
    },
    # ===================================================================
    # 五、空间拓扑树与时空感知移动（39-44）
    # ===================================================================
    {
        "id": "39",
        "title": "换季大挪移——调味品集体从桌面进地柜",
        "category": CATEGORY_5,
        "turns": [
            {"text": "天气热了，帮我把灶台台面上的所有开封酱料全都挪到地柜冷暗处。", "user_name": "老婆", "expected": ["老干妈"]},
            {"text": "蚝油开封后放地柜会坏吗？要不要进冰箱？", "user_name": "老婆", "expected": ["蚝油"]},
            {"text": "听你的，那我把蚝油单独塞进冰箱冷藏层。", "user_name": "老婆", "expected": ["蚝油"]},
            {"text": "现在的灶台台面上是不是彻底干净了，没有任何调料了？", "user_name": "老婆", "expected": ["干净"]},
            {"text": "太舒服了，地柜那两瓶开封的设置3个月到期提醒。", "user_name": "老婆", "expected": ["提醒"]},
        ],
    },
    {
        "id": "40",
        "title": "空间重命名——小冰箱改名饮料冷藏柜",
        "category": CATEGORY_5,
        "turns": [
            {'text': '管家，把书房的"小冰箱"在系统里改名叫"饮料冷藏柜"。', "user_name": "老公", "expected": ["重命名"]},
            {'text': '原先小冰箱里冰着的那些巴黎水还在新名字下面吧？', "user_name": "老公", "expected": ["巴黎水"]},
            {'text': '帮我把面膜拿出来放回卧室。', "user_name": "老公", "expected": ["面膜"]},
            {"text": "所以现在饮料冷藏柜里是纯饮料了吗？", "user_name": "老公", "expected": ["巴黎水"]},
            {"text": "很好，以后别的东西不许记到这个饮料柜里。", "user_name": "老公", "expected": ["策略"]},
        ],
    },
    {
        "id": "41",
        "title": "跨房间搬运——客厅的水果拿到主卧",
        "category": CATEGORY_5,
        "turns": [
            {"text": "我把客厅茶几上的那盘香蕉拿到主卧床头柜上了。", "user_name": "老婆", "expected": ["香蕉"]},
            {"text": "主卧床头柜上现在还有其他能吃的东西吗？", "user_name": "老婆", "expected": ["香蕉"]},
            {"text": "那客厅茶几上是不是就没水果了？", "user_name": "老婆", "expected": ["空"]},
            {"text": "等下让老公把厨房的洗干净的苹果拿两个到客厅茶几补位。", "user_name": "老婆", "expected": ["苹果"]},
            {"text": "好，等他完成了你自动更新就行。", "user_name": "老婆", "expected": ["自动"]},
        ],
    },
    {
        "id": "42",
        "title": "隐藏空间探索——发现过期很久的抽屉死角",
        "category": CATEGORY_5,
        "turns": [
            {"text": "管家，我刚刚清理书房最底层那个尘封的储物死角，居然翻出了一袋三年前的牛肉干。", "user_name": "老公", "expected": ["牛肉干"]},
            {"text": "这肯定不能吃了，保质期是到2024年的，我直接丢垃圾桶了。", "user_name": "老公", "expected": ["超期"]},
            {"text": "那个死角抽屉里还有别的东西吗？", "user_name": "老公", "expected": ["肉眼"]},
            {"text": "还有一盒没开封的签字笔和几本旧书。", "user_name": "老公", "expected": ["签字笔"]},
            {"text": "太有成就感了。那个抽屉现在算干净了吧。", "user_name": "老公", "expected": ["干净"]},
        ],
    },
    {
        "id": "43",
        "title": "新增收纳神器——创建全新三级子抽屉",
        "category": CATEGORY_5,
        "turns": [
            {'text': '管家，我买了一个分层收纳盒，放进厨房大抽屉里了，以后分成"一号格"和"二号格"。', "user_name": "老婆", "expected": ["一号格", "二号格"]},
            {'text': '以后一号格专门放厨房小工具，二号格放封口夹和保鲜膜。', "user_name": "老婆", "expected": ["工具", "耗材"]},
            {'text': '把大抽屉里原本乱放的3个封口夹和1卷保鲜膜全都塞进二号格。', "user_name": "老婆", "expected": ["封口夹"]},
            {'text': '大抽屉里原先那个开瓶器放进一号格。', "user_name": "老婆", "expected": ["开瓶器"]},
            {"text": "现在这个大抽屉是不是不凌乱了？", "user_name": "老婆", "expected": ["整洁"]},
        ],
    },
    {
        "id": "44",
        "title": "空间倾覆——收纳盒整体被清空并注销",
        "category": CATEGORY_5,
        "turns": [
            {'text': '管家，那个旧的"塑料储物筐"太破了，我决定把它连框带里面的杂物整体打包废弃掉。', "user_name": "老公", "expected": ["电池", "抹布"]},
            {"text": "电池我拿出来丢到有害垃圾回收处，抹布跟着旧筐一起扔了。", "user_name": "老公", "expected": ["电池", "抹布"]},
            {"text": "呼，差点把有毒电池给一起扔了。", "user_name": "老公", "expected": ["完整性"]},
            {"text": "原本放旧筐的那个地方现在空出来了吧？", "user_name": "老公", "expected": ["复位"]},
            {"text": "行，旧筐注销完毕，系统里没有这个词了吧？", "user_name": "老公", "expected": ["剥离"]},
        ],
    },
    # ===================================================================
    # 六、强中断、状态逃逸与异常容错（45-50）
    # ===================================================================
    {
        "id": "45",
        "title": "引导单选确认时用户突发反悔（Escape机制）",
        "category": CATEGORY_6,
        "turns": [
            {"text": "把冰箱里的可乐删掉一瓶。", "user_name": "老公", "expected": ["选择"]},
            {"text": "算了，不要了，不想删了。", "user_name": "老公", "expected": ["取消"]},
            {"text": "虚惊一场。帮我查查冷冻层里有冰块吗？", "user_name": "老公", "expected": ["冰块"]},
            {"text": "太好了。那我拿4个冰块出来配威士忌。", "user_name": "老公", "expected": ["冰块"]},
            {"text": "刚刚那次删除可乐的错误挂起没有污染数据库吧？", "user_name": "老公", "expected": ["未动"]},
        ],
    },
    {
        "id": "46",
        "title": "连续轰炸——一句话塞入4个不相干动作",
        "category": CATEGORY_6,
        "turns": [
            {"text": "管家，买了两袋面粉放粮仓，把冰箱里的烂苹果扔了，顺便看看牛奶过期没，最后给我生成个晚饭菜谱。", "user_name": "老婆", "expected": ["面粉", "苹果", "牛奶", "菜谱"]},
            {"text": "那最后一个动作呢？晚饭菜谱呢？", "user_name": "老婆", "expected": ["菜谱"]},
            {"text": "太厉害了，一句话的事情你全办到了。那面粉数量现在是多少了？", "user_name": "老婆", "expected": ["面粉"]},
            {"text": "刚才扔掉的那个烂苹果，没把其他好苹果也删了吧？", "user_name": "老婆", "expected": ["锁定"]},
            {"text": "行，那就按这个菜谱做晚饭，牛奶等会儿我直接喝。", "user_name": "老婆", "expected": ["菜谱"]},
        ],
    },
    {
        "id": "47",
        "title": "极度非结构化大白话的意图提炼",
        "category": CATEGORY_6,
        "turns": [
            {"text": "那个啥，管家啊，就是天天在厨房灶台前戳着的那个红颜色的长得像老干妈一样的那个辣椒酱，刚刚被我吭哧吭哧直接干掉了一大半，可能就剩个底儿了。", "user_name": "老公", "expected": ["老干妈"]},
            {"text": "卧槽，这也行。那剩下的这点底儿还能吃一顿吗？", "user_name": "老公", "expected": ["底儿"]},
            {"text": "行，那今天晚上我做菜就把这最后一点底儿全用了。", "user_name": "老公", "expected": ["清仓"]},
            {"text": "地柜里还有未开封的老干妈囤货吗？", "user_name": "老公", "expected": ["老干妈"]},
            {"text": "太好了，无缝衔接。", "user_name": "老公", "expected": ["衔接"]},
        ],
    },
    {
        "id": "48",
        "title": "识别中断——在确认中途改去问天气",
        "category": CATEGORY_6,
        "turns": [
            {"text": "把冰箱里的可乐拿一瓶出来。", "user_name": "老婆", "expected": ["选择"]},
            {"text": "外面好像下雨了，管家，今天出门要带伞吗？", "user_name": "老婆", "expected": ["带伞"]},
            {"text": "噢噢对，差点忘了。我拿的是2号无糖的。", "user_name": "老婆", "expected": ["无糖"]},
            {"text": "谢谢管家，你没被我带偏。零度可乐还剩几罐？", "user_name": "老婆", "expected": ["1罐"]},
            {"text": "好的，加在下班采购随手记里吧。", "user_name": "老婆", "expected": ["采购"]},
        ],
    },
    {
        "id": "49",
        "title": "底层数据冲突/死锁状态下的安全强行回滚",
        "category": CATEGORY_6,
        "turns": [
            {"text": "管家，系统好像卡住了，我刚才说改位置它没反应，重新查一下东北大米在哪里？", "user_name": "老公", "expected": ["大米"]},
            {"text": "呼，吓死我了，没丢数据就好。那我重新提交一次：我想把它移到阳台。", "user_name": "老公", "expected": ["阳台"]},
            {"text": "现在系统状态完全恢复正常了吧？", "user_name": "老公", "expected": ["正常"]},
            {"text": "那原本阳台储物柜里放着的那些杂物没被大米压着或者冲掉吧？", "user_name": "老公", "expected": ["独立"]},
            {"text": "太棒了，这套系统重构得真稳。", "user_name": "老公", "expected": ["安全"]},
        ],
    },
    {
        "id": "50",
        "title": "情感化求助——心情不好，家里有什么能大吃一顿的",
        "category": CATEGORY_6,
        "turns": [
            {"text": "管家，今天工作被老板骂了，心情极度不好！快帮我查查全家现在有什么能让我大吃一顿、暴饮暴食的快乐源泉？", "user_name": "老婆", "expected": ["冰淇淋", "薯片"]},
            {"text": "呜呜呜，还是你对我好。我要吃那个哈根达斯！全部吃掉！", "user_name": "老婆", "expected": ["哈根达斯"]},
            {"text": "吃甜的心情好多了。系统里那盒哈根达斯是不是彻底除名了？", "user_name": "老婆", "expected": ["清空"]},
            {"text": "薯片我拿出来放在茶几上，等会儿一边看剧一边继续吃。", "user_name": "老婆", "expected": ["薯片"]},
            {"text": "谢谢管家，今天多亏有你陪我。", "user_name": "老婆", "expected": ["后盾"]},
        ],
    },
]


# ===================================================================
# Tests
# ===================================================================


def _run_turns(client: TestClient, turns: list[dict]) -> list[dict[str, Any]]:
    """Run a sequence of dialogue turns and validate expected keywords."""
    results = []
    for i, turn in enumerate(turns):
        result = _chat(client, turn["text"], user_name=turn.get("user_name", "主人"))
        results.append(result)

        # Assert expected keywords are present
        for kw in turn.get("expected", []):
            assert kw in result.get("reply", ""), (
                f"Turn {i+1}: expected keyword '{kw}' in reply, got:\n"
                f"  {result.get('reply', '')[:300]}"
            )

        # Assert not_expected keywords are absent
        for kw in turn.get("not_expected", []):
            assert kw not in result.get("reply", ""), (
                f"Turn {i+1}: unexpected keyword '{kw}' in reply:\n"
                f"  {result.get('reply', '')[:300]}"
            )

        # Post-chat action (confirm_add / confirm_consume)
        action = turn.get("action", "")
        if action == "confirm_add":
            _confirm_add(client, result)
        elif action.startswith("confirm_consume_"):
            idx = int(action.split("_")[-1]) if len(action.split("_")) >= 3 else 0
            _confirm_consume(client, result, selected_index=idx)
        elif action == "confirm_consume_all":
            _confirm_consume(client, result, selected_index=0, consume_all=True)

    return results


@pytest.mark.parametrize(
    "scenario",
    SCENARIOS,
    ids=lambda s: f"[{s['category'][:4]}][#{s['id']}] {s['title'][:30]}",
)
def test_all_scenarios(client: TestClient, scenario: dict) -> None:
    """Run all turns of a scenario and validate expected keywords."""
    results = _run_turns(client, scenario["turns"])
    assert len(results) == len(scenario["turns"]), (
        f"Expected {len(scenario['turns'])} replies, got {len(results)}"
    )


# ===================================================================
# Report Generation — runs all scenarios and produces comparison doc
# ===================================================================


def _parse_demo_expected() -> dict[str, list[str]]:
    """Parse q&a_demo.md to extract expected assistant replies per turn.

    Returns: {scenario_id: [reply_for_turn_1, reply_for_turn_2, ...]}
    """
    if not DEMO_FILE.exists():
        print(f"Warning: Demo file not found at {DEMO_FILE}")
        return {}

    text = DEMO_FILE.read_text(encoding="utf-8")
    result: dict[str, list[str]] = {}

    # Find scenario blocks: "#### 场景 N"
    blocks = re.split(r"(?=####\s+场景\s+\d+)", text)

    for block in blocks:
        id_match = re.search(r"####\s+场景\s+(\d+)", block)
        if not id_match:
            continue
        sc_id = id_match.group(1)
        replies: list[str] = []

        # Extract all "轮 N 管家：" lines
        for turn_match in re.finditer(
            r"\*\*\s*轮\s*\d+\s*管家\*\*\s*[：:]\s*(.+?)(?=\n\s*\*\s*\*\s*轮|\n\s*\*\*\s*轮|\n\n####|\Z)",
            block,
            re.DOTALL,
        ):
            reply = turn_match.group(1).strip()
            reply = reply.replace("**", "").strip()
            reply = reply.split("\n")[0].strip()
            if reply:
                replies.append(reply)

        if replies:
            result[sc_id] = replies

    return result


def generate_qa_report() -> None:
    """Run all 50 scenarios through /api/chat and produce a detailed comparison report.

    Output: server/tests/qa/qa-test-results.md
    """
    with TemporaryDirectory(prefix="squirrel-qa-") as temp_dir:
        original_data_dir = settings.data_dir
        original_storage_dir = settings.storage_dir
        original_chroma_enabled = settings.chroma_enabled
        settings.data_dir = Path(temp_dir) / "data"
        settings.storage_dir = Path(temp_dir) / "storage"
        settings.chroma_enabled = False

        try:
            from app.main import create_app
            from app.services.vector_store import vector_store

            original_vector_collection = vector_store._collection
            vector_store._collection = None
            try:
                with TestClient(create_app()) as client:
                    _generate_qa_report(client)
            finally:
                vector_store._collection = original_vector_collection
        finally:
            settings.data_dir = original_data_dir
            settings.storage_dir = original_storage_dir
            settings.chroma_enabled = original_chroma_enabled


def _generate_qa_report(client: TestClient) -> None:
    """Generate the report using an already isolated application client."""

    expected_replies = _parse_demo_expected()

    QA_DIR.mkdir(parents=True, exist_ok=True)

    report_lines = [
        "# Q&A 50场景测试结果报告\n",
        f"> 测试日期：{date.today().format()}\n",
        "> 测试方式：通过 `POST /api/chat` 端点逐轮发送用户消息并记录回复\n",
    ]

    # Summary table header
    report_lines.append("## 汇总\n")
    report_lines.append("| # | 场景名称 | 总轮次 | 通过 | 失败 |\n")
    report_lines.append("|---|---------|------|------|------|\n")

    detail_lines: list[str] = []
    detail_lines.append("\n## 详细对比\n")

    total_turns = 0
    passed_turns = 0
    failed_scenarios = 0

    for scenario in SCENARIOS:
        sc_id = scenario["id"]
        sc_title = scenario["title"]
        turns = scenario["turns"]
        sc_expected = expected_replies.get(sc_id, [])

        results: list[dict[str, Any]] = []
        try:
            results = _run_turns(client, turns)
        except Exception as e:
            print(f"[ERROR] Scenario #{sc_id} ({sc_title}): {e}")
            results = [{"reply": f"❌ 测试异常：{e}"} for _ in turns]

        sc_pass = 0
        for i, turn in enumerate(turns):
            total_turns += 1
            actual = results[i].get("reply", "(无回复)") if i < len(results) else "(测试失败)"
            expected_txt = sc_expected[i] if i < len(sc_expected) else "(无预期)"

            kw_ok = all(kw in actual for kw in turn.get("expected", []))
            not_kw_ok = all(kw not in actual for kw in turn.get("not_expected", []))
            status = "✅" if (kw_ok and not_kw_ok) else "❌"
            if kw_ok and not_kw_ok:
                sc_pass += 1
                passed_turns += 1

            # Detail entry
            detail_lines.append(f"### [#{sc_id}] {sc_title} — 第{i+1}轮\n")
            detail_lines.append(f"**用户（{turn.get('user_name', '主人')}）**：\n")
            detail_lines.append(f"> {turn['text']}\n\n")
            detail_lines.append(f"**预期回答**：\n")
            detail_lines.append(f"> {expected_txt}\n\n")
            detail_lines.append(f"**实际回答**：\n")
            detail_lines.append(f"> {actual}\n\n")
            detail_lines.append(f"**结果**：{status}\n")
            detail_lines.append("---\n\n")

        if sc_pass < len(turns):
            failed_scenarios += 1

        report_lines.append(
            f"| #{sc_id} | {sc_title} | {len(turns)} | {sc_pass} | {len(turns) - sc_pass} |\n"
        )

    # Write report
    report_lines.insert(
        1,
        f"> 共 {len(SCENARIOS)} 个场景，{total_turns} 轮对话，通过 {passed_turns}，"
        f"失败 {total_turns - passed_turns}，场景级失败 {failed_scenarios}\n",
    )

    full_report = ("".join(report_lines) + "\n" + "".join(detail_lines)
                   + f"\n*报告由 test_qa_50_scenarios.py 自动生成于 {date.today().isoformat()}*")
    REPORT_FILE.write_text(full_report, encoding="utf-8")

    print(f"\n✅ 测试报告已生成：{REPORT_FILE}")
    print(f"   场景数：{len(SCENARIOS)}")
    print(f"   对话轮次：{total_turns}")
    print(f"   通过：{passed_turns}/{total_turns}")


if __name__ == "__main__":
    generate_qa_report()

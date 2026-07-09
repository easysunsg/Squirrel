#!/usr/bin/env python3
"""Standalone script to run all 50 daily-life scenarios against /api/chat
and produce a conversation transcript document.

Usage:
    cd server
    python ../scripts/generate_scenario_doc.py
"""

from __future__ import annotations

import json
import os
import sys
from datetime import date
from pathlib import Path
from typing import Any

# Ensure the `server` directory is on sys.path so we can import app modules.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "server"))

from fastapi.testclient import TestClient
from app.main import create_app


DOCS_DIR = Path(__file__).resolve().parents[1] / "docs"
OUTPUT_FILE = DOCS_DIR / "daily-ai-test-results.md"


def _read_sse(response) -> dict[str, Any]:
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
    raise AssertionError(f"No event: result found. Raw: {text[:300]}")


def _chat(client: TestClient, text: str) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "messages": [
            {"id": f"msg-{hash(text) & 0xFFFFFFFF:08x}", "sender": "user", "text": text, "timestamp": "刚刚"}
        ]
    }
    resp = client.post("/api/chat", json=payload)
    assert resp.status_code == 200
    return _read_sse(resp)


def main() -> None:
    client = TestClient(create_app())
    DOCS_DIR.mkdir(parents=True, exist_ok=True)

    scenarios = [
        ("#1",  "起床气", "再睡五分钟……"),
        ("#2",  "今天穿什么", "今天穿什么？"),
        ("#3",  "早餐营养师", "早餐吃什么？冰箱里有鸡蛋、番茄、菠菜"),
        ("#4",  "出门前检查", "我出门了！"),
        ("#5",  "通勤新闻速读", "今天有什么要闻吗？"),
        ("#6",  "冰箱快空了", "冰箱里只剩鸡蛋、西兰花、黄油和快过期的牛奶了，能做什么？"),
        ("#7",  "招待朋友不翻车", "周末三个大人一个小孩来吃饭，帮我设计一个不容易翻车的菜单"),
        ("#8",  "营养控糖咨询", "我体检血糖偏高，早上喝白粥吃油条是不是不太好？"),
        ("#9",  "深夜饿了", "半夜饿了，有什么健康点儿的吃的推荐吗？"),
        ("#10",  "买菜清单", "帮我生成这周的买菜清单，两个人吃，五天的晚餐"),
        ("#11",  "头痛发作", "头好痛，可能是盯屏幕太久了"),
        ("#12",  "跑步记录分析", "我最近跑步配速6分半，是不是退步了？"),
        ("#13",  "失眠求助", "睡不着，试了好几种方法都没用"),
        ("#14",  "药物提醒", "我今晚要喝酒，但早上刚吃了最后一粒阿奇霉素，有冲突吗？"),
        ("#15",  "情绪低落", "最近心情不太好，觉得什么事都没意思"),
        ("#16",  "买手机纠结", "手机A拍照好但续航差，手机B续航强但比较重，我该怎么选？"),
        ("#17",  "大促剁手预警", "双十一购物车堆了20多件东西，帮我看看哪些是真正需要的？"),
        ("#18",  "买礼物没头绪", "好朋友快生日了，预算300以内，她喜欢手作的东西，送什么好？"),
        ("#19",  "退货流程太麻烦", "买的台灯色温不对，但退货流程好复杂，不想退了"),
        ("#20",  "超市比价", "帮我算算是在楼下超市买菜划算还是App下单划算？"),
        ("#21",  "出差行程安排", "下周二下午到上海出差，周四中午回，帮我规划一下行程和住宿"),
        ("#22",  "航班延误了", "航班延误了，能帮我看看有没有更早的航班可以改签吗？"),
        ("#23",  "旅行规划师", "国庆想去云南，五天四晚，预算5000一个人，不想太累，求推荐"),
        ("#24",  "迷路了", "我在一条小巷子里迷路了，面前是一个红色门的房子"),
        ("#25",  "时差反应", "从美国回来三天了，每天晚上7点困凌晨3点醒，时差好难受"),
        ("#26",  "不想上班", "周一早上完全不想上班，最不想写周报了"),
        ("#27",  "开会走神被抓包", "开会走神了，老板突然点名让我发言怎么办？"),
        ("#28",  "简历修改", "想跳槽，但感觉简历写得太平淡了，能帮我看看吗？"),
        ("#29",  "邮件写不好", "要写一封解释项目延期的邮件给客户，既要说明原因又不能让对方觉得我们不靠谱，帮我起草"),
        ("#30",  "年终总结凑字数", "年终总结要写2000字，感觉今年没干什么大事，能帮我扩充一下吗？"),
        ("#31",  "搬家整理崩溃", "搬家三天了还有5个箱子没拆，完全不想动了"),
        ("#32",  "水电费异常", "这个月电费贵了一倍，680块，是不是哪里有问题？"),
        ("#33",  "装修选择困难", "卫生间翻新，浅灰还是米白瓷砖？纠结三天了"),
        ("#34",  "绿植养护", "龟背竹叶子发黄了，是不是浇水太多了？"),
        ("#35",  "宠物不对劲", "我家猫今天不吃不喝一直窝在角落，是不是生病了？"),
        ("#36",  "剧荒求助", "最近好无聊，有什么好看的剧推荐吗？"),
        ("#37",  "游戏卡关", "BOSS打了十几遍过不去，是不是我打法有问题？"),
        ("#38",  "读书选择", "半年没完整读完一本书了，推荐一本容易读进去的"),
        ("#39",  "学乐器受挫", "自学尤克里里两周，和弦转换还是卡顿，我是不是没有音乐天赋？"),
        ("#40",  "拍照修图", "拍了一张风景照但灰蒙蒙的，想要那种电影感色调"),
        ("#41",  "背单词坚持不下去", "每天背30个单词坚持了三天就断了，我是不是太没毅力了？"),
        ("#42",  "职业方向迷茫", "工作三年了，感觉遇到了天花板，不知道要不要转产品经理"),
        ("#43",  "读书笔记整理", "读完半本书感觉啥也没记住，怎么整理读书笔记比较好？"),
        ("#44",  "公众演讲紧张", "下周要在全公司做分享，上台就紧张发抖怎么办？"),
        ("#45",  "习惯养成", "总忘记喝水，一天喝不到800ml，有什么办法吗？"),
        ("#46",  "分手后的夜晚", "刚分手，晚上特别难熬"),
        ("#47",  "和家人吵架了", "刚和爸妈吵完架，又生气又内疚"),
        ("#48",  "孤独感突然袭来", "周末晚上一个人在家，突然觉得好孤独"),
        ("#49",  "生日惊喜", "今天有什么特别的吗？"),
        ("#50",  "深夜哲学", "你说，人活着的意义到底是什么？"),
    ]

    results_rows: list[str] = []
    conversation_entries: list[str] = []
    passed = 0
    failed = 0

    for scenario_id, title, user_text in scenarios:
        try:
            result = _chat(client, user_text)
            reply = result.get("reply", "（无回复）")
            passed += 1
        except Exception as exc:
            reply = f"**测试异常**：{exc}"
            failed += 1

        if results_rows:
            results_rows.append(f"| {scenario_id} | {title} | {'OK' if not reply.startswith('**测试异常**') else 'FAIL'} |\n")

        conversation_entries.append(f"### {scenario_id} {title}\n\n**User**: {user_text}\n\n**Agent**: {reply}\n\n---\n")

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write("# 50 Daily-Life AI Scenarios - Test Results\n\n")
        f.write(f"Date: {date.today().isoformat()}\n\n")
        f.write(f"**Passed**: {passed}/{len(scenarios)}\n\n")
        f.write("## Conversation Transcript\n\n")
        f.writelines(conversation_entries)

    print(f"Done. Output -> {OUTPUT_FILE}")
    print(f"Passed {passed}/{len(scenarios)}, Failed {failed}")


if __name__ == "__main__":
    main()

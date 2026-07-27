import json
from datetime import date, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.services.llm import llm_service


def _read_sse(response) -> dict:
    raw = b"".join(response.iter_bytes()).decode("utf-8")
    for block in reversed(raw.split("\n\n")):
        event_type = ""
        event_data = ""
        for line in block.strip().split("\n"):
            if line.startswith("event: "):
                event_type = line[7:].strip()
            elif line.startswith("data: "):
                event_data = line[6:]
        if event_type == "result" and event_data:
            return json.loads(event_data)
    raise AssertionError(f"No result event: {raw[:500]}")


def _chat(client: TestClient, text: str) -> dict:
    response = client.post(
        "/api/chat",
        json={
            "messages": [
                {
                    "id": f"msg-{abs(hash(text))}",
                    "sender": "user",
                    "text": text,
                    "timestamp": "刚刚",
                }
            ],
            "userName": "老公",
        },
    )
    assert response.status_code == 200
    return _read_sse(response)


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path / "data")
    monkeypatch.setattr(settings, "storage_dir", tmp_path / "storage")
    monkeypatch.setattr(settings, "chroma_enabled", False)
    monkeypatch.setattr(llm_service, "enabled", False)

    from app.main import create_app
    from app.services.vector_store import vector_store

    monkeypatch.setattr(vector_store, "_collection", None)
    with TestClient(create_app()) as test_client:
        yield test_client


def test_strawberry_followup_conversation_updates_one_batch(client: TestClient) -> None:
    milk_expiry = (date.today() + timedelta(days=7)).isoformat()
    milk_response = client.post(
        "/api/items",
        json={
            "title": "牛奶",
            "category": "food",
            "location": "冰箱下层",
            "count": 1,
            "unit": "瓶",
            "expireDate": milk_expiry,
            "remark": "早餐用",
        },
    )
    assert milk_response.status_code == 201
    milk_before = next(
        item for item in client.get("/api/items").json()["items"]
        if item["title"] == "牛奶"
    )

    add_result = _chat(client, "我刚买了两盒草莓，放进冰箱冷藏层了")
    assert add_result["needsConfirmation"] is True
    assert "草莓" in add_result["reply"]
    assert "2盒" in add_result["reply"]
    pending_items = add_result["itemSuggestion"]["items"]
    assert len(pending_items) == 1
    assert pending_items[0]["title"] == "草莓"
    assert pending_items[0]["count"] == 2
    assert pending_items[0]["unit"] == "盒"
    assert pending_items[0]["location"] == "冰箱冷藏层"

    confirm_result = _chat(client, "确认")
    assert confirm_result["needsConfirmation"] is False
    assert "已确认入库：草莓 2盒" in confirm_result["reply"]

    remark_result = _chat(client, "每盒大概有500克，你把备注加上")
    assert "草莓" in remark_result["reply"]
    assert "500 克" in remark_result["reply"]

    expiry_result = _chat(client, "保质期一般是3天，算一下什么时候过期？")
    expected_expiry = (date.today() + timedelta(days=3)).isoformat()
    assert "草莓" in expiry_result["reply"]
    assert expected_expiry in expiry_result["reply"]

    search_result = _chat(client, "帮我看看冷藏层里还有别的盘装生鲜吗？")
    assert search_result["reply"] == "冷藏层里除了「草莓」，没有找到其他盘装生鲜。"
    assert "胡萝卜" not in search_result["reply"]
    assert "牛奶" not in search_result["reply"]

    consume_result = _chat(client, "知道了，草莓洗一盒下午吃")
    assert "草莓" in consume_result["reply"]
    assert consume_result["needsConfirmation"] is True
    consume_confirm_result = _chat(client, "1")
    assert consume_confirm_result["needsConfirmation"] is False

    items = client.get("/api/items").json()["items"]
    strawberry = next(item for item in items if item["title"] == "草莓")
    milk_after = next(item for item in items if item["title"] == "牛奶")
    assert strawberry["count"] == 1
    assert "500 克" in strawberry["remark"]
    assert strawberry["expireDate"] == expected_expiry
    assert milk_after["expireDate"] == milk_before["expireDate"]
    assert milk_after["remark"] == milk_before["remark"]


def test_add_can_be_cancelled_through_chat(client: TestClient) -> None:
    add_result = _chat(client, "我刚买了两盒草莓，放进冰箱冷藏层了")
    assert add_result["needsConfirmation"] is True

    cancel_result = _chat(client, "取消")
    assert cancel_result["needsConfirmation"] is False
    assert cancel_result["reply"] == "已取消入库。"

    items = client.get("/api/items").json()["items"]
    assert not any(item["title"] == "草莓" for item in items)

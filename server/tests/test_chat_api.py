"""Tests for /api/chat SSE endpoint.

Each test posts a /api/chat request and reads the SSE stream to extract
the final event: result data:, then validates the JSON payload.
"""

import json
from collections.abc import Generator

from fastapi.testclient import TestClient

from app.main import create_app


client = TestClient(create_app())


def _read_sse(response) -> dict:
    """Read an SSE response and return the parsed `result` event data."""
    data = b""
    for chunk in response.iter_bytes():
        data += chunk
    text = data.decode("utf-8")

    # Find the last `event: result` block
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

    raise AssertionError(f"No event: result found in SSE stream. Raw: {text[:500]}")


def test_chat_add_returns_pending():
    """add 操作返回 pendingId 不直接入库"""
    response = client.post(
        "/api/chat",
        json={
            "messages": [
                {"id": "msg-user-1", "sender": "user", "text": "我今天买了一把油麦菜，放冰箱下层", "timestamp": "刚刚"}
            ]
        },
    )

    assert response.status_code == 200
    assert response.headers.get("content-type", "").startswith("text/event-stream")
    data = _read_sse(response)
    assert data.get("needsConfirmation") is True
    assert data.get("pendingId") is not None
    assert data["itemSuggestion"]["pendingId"] == data["pendingId"]
    assert len(data["itemSuggestion"]["items"]) >= 1

    # 验证未入库
    items = client.get("/api/items").json()["items"]
    assert not any(item["title"] == "油麦菜" for item in items)


def test_chat_add_then_confirm():
    """确认后物品才入库"""
    # 第一轮：解析
    chat_resp = client.post(
        "/api/chat",
        json={
            "messages": [
                {"id": "msg-user-1", "sender": "user", "text": "买了牛奶，放冰箱下层", "timestamp": "刚刚"}
            ]
        },
    )
    data = _read_sse(chat_resp)
    pending_id = data["pendingId"]
    pending_items = data["itemSuggestion"]["items"]
    # 修改数量再确认
    pending_items[0]["count"] = 2

    # 第二轮：确认
    confirm_resp = client.post(
        "/api/chat/confirm",
        json={"pendingId": pending_id, "items": pending_items},
    )
    assert confirm_resp.status_code == 200
    assert confirm_resp.json()["ok"] is True

    # 验证已入库
    items = client.get("/api/items").json()["items"]
    milk = next(item for item in items if item["title"] == "牛奶")
    assert milk["count"] == 2


def test_chat_confirm_expired_pending():
    """过期 pending 返回 404"""
    response = client.post(
        "/api/chat/confirm",
        json={"pendingId": "pending-nonexistent", "items": []},
    )
    assert response.status_code == 404


def test_chat_confirm_empty_items():
    """确认空列表 = 取消入库"""
    chat_resp = client.post(
        "/api/chat",
        json={
            "messages": [
                {"id": "msg-user-cancel", "sender": "user", "text": "买了鸡蛋，放冰箱", "timestamp": "刚刚"}
            ]
        },
    )
    data = _read_sse(chat_resp)
    pending_id = data["pendingId"]

    confirm_resp = client.post(
        "/api/chat/confirm",
        json={"pendingId": pending_id, "items": []},
    )
    assert confirm_resp.status_code == 200
    assert "新增 0 件" in confirm_resp.json()["messages"][-1]["text"]



def test_chat_updates_location():
    # 添加并确认胡萝卜
    r1 = client.post(
        "/api/chat",
        json={
            "messages": [
                {"id": "msg-user-2", "sender": "user", "text": "买了胡萝卜，放冰箱下层", "timestamp": "刚刚"}
            ]
        },
    )
    d1 = _read_sse(r1)
    if d1.get("pendingId"):
        client.post("/api/chat/confirm", json={"pendingId": d1["pendingId"], "items": d1.get("itemSuggestion", {}).get("items", [])})

    # 确认后验证已入库
    items_before = client.get("/api/items").json()["items"]
    carrot_before = next((item for item in items_before if item["title"] == "胡萝卜"), None)
    assert carrot_before is not None, "胡萝卜应已入库"
    assert carrot_before["location"] == "冰箱下层"

    response = client.post(
        "/api/chat",
        json={
            "messages": [
                {"id": "msg-user-3", "sender": "user", "text": "把胡萝卜换到冰箱上层", "timestamp": "刚刚"}
            ]
        },
    )

    assert response.status_code == 200
    _read_sse(response)  # ensure it parses
    items = client.get("/api/items").json()["items"]
    carrot = next(item for item in items if item["title"] == "胡萝卜")
    assert carrot["location"] == "冰箱上层"


def test_chat_remove_item():
    client.post(
        "/api/chat",
        json={
            "messages": [
                {"id": "msg-user-4", "sender": "user", "text": "买了橘子，放客厅柜子里", "timestamp": "刚刚"}
            ]
        },
    )

    response = client.post(
        "/api/chat",
        json={
            "messages": [
                {"id": "msg-user-5", "sender": "user", "text": "橘子坏了，扔掉", "timestamp": "刚刚"}
            ]
        },
    )

    assert response.status_code == 200
    _read_sse(response)
    items = client.get("/api/items").json()["items"]
    assert not any(item["title"] == "橘子" for item in items)


def test_chat_query_does_not_mutate_inventory():
    before = client.get("/api/items").json()["items"]

    response = client.post(
        "/api/chat",
        json={
            "messages": [
                {"id": "msg-user-6", "sender": "user", "text": "我家里还有什么蔬菜？", "timestamp": "刚刚"}
            ]
        },
    )

    after = client.get("/api/items").json()["items"]
    assert response.status_code == 200
    _read_sse(response)
    assert len(before) == len(after)


def test_chat_ambiguous_update_returns_suggestion():
    # 添加并确认第一个牛奶
    r1 = client.post(
        "/api/chat",
        json={
            "messages": [
                {"id": "msg-user-7", "sender": "user", "text": "买了牛奶，放冰箱下层", "timestamp": "刚刚"}
            ]
        },
    )
    d1 = _read_sse(r1)
    if d1.get("pendingId"):
        client.post("/api/chat/confirm", json={"pendingId": d1["pendingId"], "items": d1.get("itemSuggestion", {}).get("items", [])})

    # 添加并确认第二个牛奶（不同位置）
    r2 = client.post(
        "/api/chat",
        json={
            "messages": [
                {"id": "msg-user-8", "sender": "user", "text": "买了牛奶，放客厅柜子里", "timestamp": "刚刚"}
            ]
        },
    )
    d2 = _read_sse(r2)
    if d2.get("pendingId"):
        client.post("/api/chat/confirm", json={"pendingId": d2["pendingId"], "items": d2.get("itemSuggestion", {}).get("items", [])})

    response = client.post(
        "/api/chat",
        json={
            "messages": [
                {"id": "msg-user-9", "sender": "user", "text": "把牛奶换到冰箱中层", "timestamp": "刚刚"}
            ]
        },
    )

    assert response.status_code == 200
    data = _read_sse(response)
    assert data["itemSuggestion"] is not None
    assert data["itemSuggestion"]["matches"]


def test_sse_content_type_and_events():
    """SSE 格式校验：Content-Type 和事件结构"""
    response = client.post(
        "/api/chat",
        json={
            "messages": [
                {"id": "msg-user-sse", "sender": "user", "text": "你好", "timestamp": "刚刚"}
            ]
        },
    )
    assert response.status_code == 200
    assert response.headers.get("content-type", "").startswith("text/event-stream")
    assert response.headers.get("x-accel-buffering") == "no"

    raw = b""
    for chunk in response.iter_bytes():
        raw += chunk
    text = raw.decode("utf-8")

    # Should contain at least one event: status and one event: result
    assert "event: status" in text
    assert "event: result" in text or "event: error" in text
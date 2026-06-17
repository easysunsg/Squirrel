from fastapi.testclient import TestClient

from app.main import create_app


client = TestClient(create_app())


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
    data = response.json()
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
    data = chat_resp.json()
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
    data = chat_resp.json()
    pending_id = data["pendingId"]

    confirm_resp = client.post(
        "/api/chat/confirm",
        json={"pendingId": pending_id, "items": []},
    )
    assert confirm_resp.status_code == 200
    assert "新增 0 件" in confirm_resp.json()["messages"][-1]["text"]



def test_chat_updates_location():
    client.post(
        "/api/chat",
        json={
            "messages": [
                {"id": "msg-user-2", "sender": "user", "text": "买了牛奶，放冰箱下层", "timestamp": "刚刚"}
            ]
        },
    )

    response = client.post(
        "/api/chat",
        json={
            "messages": [
                {"id": "msg-user-3", "sender": "user", "text": "把牛奶换到冰箱上层", "timestamp": "刚刚"}
            ]
        },
    )

    assert response.status_code == 200
    items = client.get("/api/items").json()["items"]
    milk = next(item for item in items if item["title"] == "牛奶")
    assert milk["location"] == "冰箱上层"


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
    assert len(before) == len(after)


def test_chat_ambiguous_update_returns_suggestion():
    client.post(
        "/api/chat",
        json={
            "messages": [
                {"id": "msg-user-7", "sender": "user", "text": "买了牛奶，放冰箱下层", "timestamp": "刚刚"}
            ]
        },
    )
    client.post(
        "/api/chat",
        json={
            "messages": [
                {"id": "msg-user-8", "sender": "user", "text": "买了牛奶，放客厅柜子里", "timestamp": "刚刚"}
            ]
        },
    )

    response = client.post(
        "/api/chat",
        json={
            "messages": [
                {"id": "msg-user-9", "sender": "user", "text": "把牛奶换到冰箱中层", "timestamp": "刚刚"}
            ]
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["itemSuggestion"] is not None
    assert data["itemSuggestion"]["matches"]

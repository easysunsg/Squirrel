from app.models.schemas import Item
from app.services.graph import run_squirrel_graph


def test_graph_routes_add_to_operations():
    result = run_squirrel_graph("3袋螺蛳粉，放客厅箱子里")

    assert result["chat_result"].intent == "add"
    assert result["chat_result"].operations[0].item.title == "螺蛳粉"


def test_graph_routes_expiry_query():
    inventory = [
        Item(title="全麦面包", spaceName="主厨房", location="厨房二级柜", remainingPct=10, tag="告急"),
    ]

    result = run_squirrel_graph("现在有什么快过期", inventory)

    assert result["chat_result"].intent == "expiry_query"
    assert "全麦面包" in result["chat_result"].replyText


def test_graph_routes_search_query():
    inventory = [
        Item(title="感冒药", spaceName="储藏间", location="药品箱 B", remainingPct=80, tag="充足"),
    ]

    result = run_squirrel_graph("我的感冒药放在哪了？", inventory)

    assert result["chat_result"].intent == "location_query"
    assert "感冒药" in result["chat_result"].replyText


from app.db.sqlite import connect, create_pending_confirmation, get_pending_confirmation, delete_pending_confirmation, cleanup_expired_pending
from uuid import uuid4


def test_create_and_get_pending():
    items = [Item(title="青椒", count=7, unit="个")]
    with connect() as conn:
        pending_id = create_pending_confirmation(conn, items)
        got = get_pending_confirmation(conn, pending_id)
    assert got is not None
    assert len(got) == 1
    assert got[0].title == "青椒"
    assert got[0].count == 7


def test_get_nonexistent_pending():
    with connect() as conn:
        got = get_pending_confirmation(conn, "pending-nonexistent")
    assert got is None


def test_delete_pending():
    items = [Item(title="牙膏", count=2)]
    with connect() as conn:
        pending_id = create_pending_confirmation(conn, items)
        deleted = delete_pending_confirmation(conn, pending_id)
    assert deleted is True


def test_cleanup_expired_pending():
    with connect() as conn:
        pending_id = f"pending-{uuid4().hex[:12]}"
        conn.execute(
            "INSERT INTO pending_confirmation(id, items, created_at) VALUES(?, ?, ?)",
            (pending_id, "[]", "2020-01-01"),
        )
        cleaned = cleanup_expired_pending(conn, ttl_minutes=30)
    assert cleaned >= 1

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

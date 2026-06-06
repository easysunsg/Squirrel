from app.models.schemas import Item
from app.services.graph import run_squirrel_graph


def test_graph_routes_ingest_to_parser():
    result = run_squirrel_graph("3袋螺蛳粉，放客厅箱子里")

    assert result["intent"] == "ingest"
    assert result["parsed_items"][0].title == "螺蛳粉"


def test_graph_routes_expiry_query():
    inventory = [
        Item(title="全麦面包", spaceName="主厨房", location="厨房二级柜", remainingPct=10, tag="告急"),
    ]

    result = run_squirrel_graph("现在有什么快过期", inventory)

    assert result["intent"] == "expiry_query"
    assert "全麦面包" in result["reply_text"]

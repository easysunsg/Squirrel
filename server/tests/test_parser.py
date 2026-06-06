from app.services.parser import parse_lightning_text


def test_parse_single_item_with_location_and_quantity():
    items = parse_lightning_text("3袋螺蛳粉，放客厅箱子里")

    assert len(items) == 1
    assert items[0].title == "螺蛳粉"
    assert items[0].count == 3
    assert items[0].unit == "袋"
    assert items[0].spaceName == "储藏间"
    assert items[0].location == "客厅箱子"


def test_parse_batch_items():
    items = parse_lightning_text("买了鸡蛋、香蕉、猪肉，都放冰箱")

    assert [item.title for item in items] == ["鸡蛋", "香蕉", "猪肉"]
    assert all(item.spaceName == "主厨房" for item in items)

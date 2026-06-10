from app.services.parser import (
    build_chat_result,
    extract_expire_patch,
    extract_location_update,
    extract_target_title,
    parse_lightning_text,
)


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


def test_extract_location_update():
    assert extract_target_title("把牛奶换到冰箱上层") == "牛奶"
    assert extract_location_update("把牛奶换到冰箱上层") == "冰箱上层"


def test_extract_expire_patch():
    patch = extract_expire_patch("土豆保质期再延 2 天")

    assert patch is not None
    assert "expireDate" in patch


def test_build_chat_result_for_remove_and_search():
    remove_result = build_chat_result("橘子坏了，扔掉")
    search_result = build_chat_result("我家里还有什么蔬菜？")

    assert remove_result.intent == "remove"
    assert remove_result.operations[0].target == "橘子"
    assert search_result.intent == "search_query"

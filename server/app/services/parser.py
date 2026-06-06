import re
from datetime import date, timedelta

from app.models.schemas import Item


def days_from_now(days: int) -> str:
    return (date.today() + timedelta(days=days)).isoformat()


def guess_space(text: str) -> tuple[str, str]:
    if re.search(r"冰箱|冷藏|冷冻|厨房|灶台", text):
        return "kitchen", "主厨房"
    if re.search(r"车库|工具|螺丝|扳手|锤", text):
        return "garage", "车库工具"
    if re.search(r"储藏|客厅|箱|柜|药|卫生间|镜柜", text):
        return "storage", "储藏间"
    return "kitchen", "主厨房"


def guess_icon(title: str, space_name: str) -> str:
    if space_name == "车库工具":
        return "construction"
    if re.search(r"药|维|感冒", title):
        return "medication"
    if re.search(r"面包|吐司", title):
        return "bakery_dining"
    if re.search(r"咖啡", title):
        return "local_cafe"
    if re.search(r"洗洁|沐浴|清洁", title):
        return "cleaning_services"
    return "package_2"


def guess_expire_date(title: str) -> str:
    if re.search(r"菜|肉|奶|酸奶|水果|香蕉|鸡蛋|面包", title):
        return days_from_now(5)
    if re.search(r"药|维", title):
        return days_from_now(365)
    return days_from_now(180)


def parse_lightning_text(text: str) -> list[Item]:
    space_id, space_name = guess_space(text)
    location_match = re.search(r"放(?:在|进|到)?(.+?)(?:里|中|$)", text)
    location = location_match.group(1).strip(" ，,。") if location_match else "默认层架"
    item_text = re.sub(r"(?:，|,)?\s*(?:都)?放(?:在|进|到)?.*$", "", text)
    item_text = re.sub(r"^(买了|购入|新增|存入|录入|添加)", "", item_text).strip() or text
    parts = [part.strip() for part in re.split(r"[、和]", item_text) if part.strip()]

    consumed = bool(re.search(r"吃完|用完|扔|坏了|清掉|消耗", text))
    remaining = 0 if consumed else 45 if re.search(r"半|一点", text) else 100

    items: list[Item] = []
    for part in parts:
        match = re.match(r"^(\d+)\s*(袋|瓶|盒|个|件|包|罐|本|条|把|颗|斤|克|g|kg)?\s*(.+)$", part, re.I)
        count = int(match.group(1)) if match else 1
        unit = match.group(2) if match and match.group(2) else ("件" if space_name == "车库工具" else "个")
        title = (match.group(3) if match else part).strip()
        tag = "告急" if remaining < 20 else "较低" if remaining < 50 else "充足"
        items.append(
            Item(
                title=title,
                spaceId=space_id,
                spaceName=space_name,
                location=location,
                remainingPct=remaining,
                expireDate=guess_expire_date(title),
                tag=tag,
                count=count,
                unit=unit,
                icon=guess_icon(title, space_name),
                remark=f"由自然语言解析：“{text}”。",
            )
        )
    return items

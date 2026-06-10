import re
from datetime import date, timedelta

from app.models.schemas import ChatOperation, ChatResult, Item


SPACE_KEYWORDS = {
    "主厨房": "kitchen",
    "储藏间": "storage",
    "车库工具": "garage",
}


CATEGORY_KEYWORDS = {
    "蔬菜": ["菜", "生菜", "菠菜", "青菜", "油麦菜", "西红柿", "黄瓜", "土豆"],
    "水果": ["果", "香蕉", "苹果", "橘子", "西瓜", "葡萄"],
    "药品": ["药", "感冒", "维C", "维生素", "止痛", "胶囊"],
    "洗浴": ["沐浴", "洗澡", "洗发", "香皂", "洁面"],
}


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


def normalize_tag(remaining: int) -> str:
    if remaining < 20:
        return "告急"
    if remaining < 50:
        return "较低"
    return "充足"


def extract_target_title(text: str) -> str | None:
    cleaned = text.strip(" ，,。！？?；;")
    patterns = [
        r"把(.+?)(?:吃完|用完|扔掉|扔了|坏了|喝了一半|用了\d+个|用了\d+瓶|用了|换到|移到|挪到|放到|放进|放在)",
        r"(.+?)(?:吃完了|用完了|扔掉了|坏了，?扔掉|坏了|喝了一半|用了\d+个|用了\d+瓶|用了|换到|移到|挪到|放到|放进|放在)",
        r"(.+?)保质期(?:再)?延\s*(\d+)\s*天",
    ]
    for pattern in patterns:
        match = re.search(pattern, cleaned)
        if match:
            title = match.group(1).strip(" 把刚才我今天将，,。")
            return title or None
    return None


def extract_location_update(text: str) -> str | None:
    match = re.search(r"(?:换到|移到|挪到|放到|放进|放在)(.+)$", text)
    if not match:
        return None
    return match.group(1).strip(" ，,。里中") or None


def extract_expire_patch(text: str) -> dict[str, str] | None:
    days_match = re.search(r"保质期(?:再)?延\s*(\d+)\s*天", text)
    if days_match:
        return {"expireDate": days_from_now(int(days_match.group(1)))}
    date_match = re.search(r"(?:到期|保质期)(?:改到|改成|设为)?\s*(\d{4}-\d{2}-\d{2})", text)
    if date_match:
        return {"expireDate": date_match.group(1)}
    if "明天过期" in text:
        return {"expireDate": days_from_now(1)}
    return None


def extract_remaining_patch(text: str, item: Item | None = None) -> dict[str, int] | None:
    if re.search(r"吃完|用完", text):
        return {"remainingPct": 0, "count": 0}
    if re.search(r"一半|半", text):
        count = max(0, (item.count // 2) if item else 0)
        return {"remainingPct": 50, "count": count}
    percent_match = re.search(r"还剩\s*(\d{1,3})%", text)
    if percent_match:
        remaining = max(0, min(100, int(percent_match.group(1))))
        return {"remainingPct": remaining}
    count_match = re.search(r"用了\s*(\d+)\s*(个|瓶|袋|盒|包|件|把|颗)?", text)
    if count_match and item:
        used = int(count_match.group(1))
        remaining_count = max(0, item.count - used)
        remaining_pct = 0 if item.count <= 0 else max(0, round(remaining_count / item.count * 100))
        return {"count": remaining_count, "remainingPct": remaining_pct}
    return None


def extract_search_keyword(text: str) -> str:
    cleaned = re.sub(r"我家里|家里|还有什么|有什么|我的|放在哪了|放哪了|在哪|哪里|念一遍", "", text)
    return cleaned.strip(" ，,。！？?；;") or text.strip()


def infer_search_terms(text: str) -> list[str]:
    for label, keywords in CATEGORY_KEYWORDS.items():
        if label in text:
            return keywords
    keyword = extract_search_keyword(text)
    return [keyword] if keyword else []


def parse_lightning_text(text: str) -> list[Item]:
    space_id, space_name = guess_space(text)
    location_match = re.search(r"放(?:在|进|到)?(.+?)(?:里|中|$)", text)
    location = location_match.group(1).strip(" ，,。") if location_match else "默认层架"
    item_text = re.sub(r"(?:，|,)?\s*(?:都)?放(?:在|进|到)?.*$", "", text)
    item_text = re.sub(r"^(我今天|刚刚|刚才)?\s*(买了|购入|新增|存入|录入|添加)", "", item_text).strip() or text
    parts = [part.strip() for part in re.split(r"[、和]", item_text) if part.strip()]

    consumed = bool(re.search(r"吃完|用完|扔|坏了|清掉|消耗", text))
    remaining = 0 if consumed else 45 if re.search(r"半|一点", text) else 100

    items: list[Item] = []
    for part in parts:
        match = re.match(r"^(\d+)\s*(袋|瓶|盒|个|件|包|罐|本|条|把|颗|斤|克|g|kg)?\s*(.+)$", part, re.I)
        count = int(match.group(1)) if match else 1
        unit = match.group(2) if match and match.group(2) else ("件" if space_name == "车库工具" else "个")
        title = (match.group(3) if match else part).strip()
        tag = normalize_tag(remaining)
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


def build_chat_result(text: str) -> ChatResult:
    if any(word in text for word in ["买了", "购入", "新增", "存入", "录入", "添加"]):
        parsed = parse_lightning_text(text)
        if not parsed:
            return ChatResult(replyText="我没有识别出明确物品，可以换一种说法再试一次。")
        return ChatResult(
            intent="add",
            replyText=f"已识别出 {len(parsed)} 件物品，准备入库。",
            operations=[ChatOperation(type="add", item=item) for item in parsed],
        )

    if any(word in text for word in ["扔掉", "扔了", "坏了", "清掉"]):
        target = extract_target_title(text)
        return ChatResult(
            intent="remove",
            replyText="我会尝试将对应物品移出库存。",
            operations=[ChatOperation(type="remove", target=target, removeReason="discarded")],
        )

    if any(word in text for word in ["吃完", "用完", "用了", "喝了一半", "还剩", "一半"]):
        target = extract_target_title(text)
        return ChatResult(
            intent="consume",
            replyText="我会尝试更新该物品的消耗情况。",
            operations=[ChatOperation(type="consume", target=target)],
        )

    if any(word in text for word in ["换到", "移到", "挪到", "放到", "放进", "放在"]):
        target = extract_target_title(text)
        location = extract_location_update(text)
        if target and location and not any(word in text for word in ["买了", "新增", "录入", "添加"]):
            return ChatResult(
                intent="update_location",
                replyText="我会尝试更新该物品的位置。",
                operations=[ChatOperation(type="update", target=target, patch={"location": location})],
            )

    expire_patch = extract_expire_patch(text)
    if expire_patch:
        target = extract_target_title(text)
        return ChatResult(
            intent="update_expiry",
            replyText="我会尝试更新该物品的保质期。",
            operations=[ChatOperation(type="update", target=target, patch=expire_patch)],
        )

    if any(word in text for word in ["过期", "快坏", "临期", "告急"]):
        return ChatResult(intent="expiry_query", replyText="正在查询临期物品。")

    if any(word in text for word in ["在哪", "哪里", "放哪", "位置"]):
        return ChatResult(intent="location_query", replyText="正在查询物品位置。")

    if any(word in text for word in ["放了很久", "很久没动", "闲置"]):
        return ChatResult(intent="idle_query", replyText="正在查询可能长期闲置的物品。")

    if any(word in text for word in ["吃什么", "做什么", "菜谱", "做饭"]):
        return ChatResult(intent="recipe", replyText="正在整理可用食材并生成建议。")

    if any(word in text for word in ["还有什么", "什么菜", "感冒药", "洗澡用", "有什么"]):
        return ChatResult(intent="search_query", replyText="正在帮你搜索相关库存。")

    return ChatResult(intent="chat", replyText="我查到当前库存了，你可以让我录入、查位置、列临期或更新物品。")

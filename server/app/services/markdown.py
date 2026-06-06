from app.core.config import settings
from app.models.schemas import AppState, Item


def item_status(item: Item) -> str:
    if item.tag == "过期预警" or item.remainingPct < 20 or item.tag == "告急":
        return "danger"
    if item.remainingPct < 50 or item.tag == "较低":
        return "low"
    return "full"


def render_inventory_markdown(state: AppState) -> str:
    lines = [
        "# 松鼠筑巢库存报告",
        "",
        "| 物品 | 数量 | 状态 | 空间 | 位置 | 剩余 | 到期 | 备注 |",
        "| --- | ---: | --- | --- | --- | ---: | --- | --- |",
    ]

    for item in state.items:
        row = [
            item.title,
            f"{item.count}{item.unit}",
            item.tag or "",
            item.spaceName,
            item.location,
            f"{item.remainingPct}%",
            item.expireDate or "",
            item.remark or "",
        ]
        lines.append("| " + " | ".join(row) + " |")

    danger_items = [item for item in state.items if item_status(item) == "danger"]
    idle_items = [item for item in state.items if item.remainingPct >= 80 and item.tag == "充足"]
    lines.extend(["", "## 今日优先处理", ""])
    danger_lines = [
        f"- {item.title}：{item.spaceName}/{item.location}，剩余 {item.remainingPct}%，到期 {item.expireDate}"
        for item in danger_items
    ]
    lines.extend(danger_lines or ["- 暂无"])
    lines.extend(["", "## 可能长期闲置", ""])
    idle_lines = [f"- {item.title}：{item.spaceName}/{item.location}" for item in idle_items[:10]]
    lines.extend(idle_lines or ["- 暂无"])
    return "\n".join(lines) + "\n"


def sync_inventory_markdown(state: AppState) -> str:
    settings.storage_dir.mkdir(parents=True, exist_ok=True)
    content = render_inventory_markdown(state)
    settings.markdown_path.write_text(content, encoding="utf-8")
    return str(settings.markdown_path)

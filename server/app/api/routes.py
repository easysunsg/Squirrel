import logging
import uuid

from fastapi import APIRouter, HTTPException, Query

from app.core.config import settings
from app.db.sqlite import (
    connect,
    create_pending_confirmation,
    create_pending_consume,
    delete_item,
    delete_pending_confirmation,
    get_conversation_state,
    get_pending_confirmation,
    get_pending_consume,
    get_state,
    init_db,
    list_items,
    list_messages,
    replace_messages,
    replace_state,
    save_conversation_state,
    upsert_item,
)
from app.models.schemas import AppState, ChatRequest, ChatResult, ConfirmRequest, ConsumeConfirmRequest, Item, Message, RecipeRequest, TextRequest
from app.services.ai import ai_service
from app.services.markdown import item_status, sync_inventory_markdown
from app.services.vector_store import vector_store

router = APIRouter(prefix="/api")
logger = logging.getLogger(__name__)


def sync_outputs() -> AppState:
    with connect() as conn:
        state = get_state(conn)
    sync_inventory_markdown(state)
    vector_store.upsert_items(state.items)
    return state


def apply_item_patch(existing: Item, patch: dict) -> Item:
    data = existing.model_dump()
    data.update(patch)
    data["id"] = existing.id
    return Item.model_validate(data)


def match_items(inventory: list[Item], target: str | None) -> list[Item]:
    if not target:
        return []
    exact = [item for item in inventory if item.title == target]
    if exact:
        return exact
    partial = [item for item in inventory if target in item.title or item.title in target]
    if partial:
        return partial
    return [item for item in inventory if target in item.location or target in item.spaceName]


def build_candidate_suggestion(candidates: list[Item]) -> dict:
    return {
        "matches": [
            {
                "id": item.id,
                "title": item.title,
                "spaceName": item.spaceName,
                "location": item.location,
                "count": item.count,
                "remainingPct": item.remainingPct,
            }
            for item in candidates[:6]
        ]
    }


def execute_chat_operations(chat_result: ChatResult, conn, inventory: list[Item]) -> tuple[ChatResult, list[Item], list[str]]:
    updated_items: list[Item] = []
    deleted_ids: list[str] = []

    # === 拦截 add 操作，存 pending 不入库 ===
    add_ops = [op for op in chat_result.operations if op.type == "add" and op.item]
    if add_ops:
        pending_items = [op.item for op in add_ops]
        pending_id = create_pending_confirmation(conn, pending_items)
        chat_result.needsConfirmation = True
        chat_result.pendingId = pending_id
        chat_result.itemSuggestion = {
            "pendingId": pending_id,
            "items": [item.model_dump() for item in pending_items],
        }
        chat_result.replyText = f"已识别出 {len(pending_items)} 件物品，请确认后再入库。"
        non_add_ops = [op for op in chat_result.operations if op.type != "add"]
        if not non_add_ops:
            return chat_result, [], []
        chat_result.operations = non_add_ops

    # === 拦截 consume 操作：多候选或单候选都需要用户确认 ===
    consume_ops = [op for op in chat_result.operations if op.type in ("consume", "remove")]
    if consume_ops:
        # 如果 graph 已经返回了候选列表（多候选或无匹配），直接存 pending
        existing_matches = (chat_result.itemSuggestion or {}).get("matches")
        if existing_matches is not None:
            candidates = [Item.model_validate(m) for m in existing_matches]
            if candidates:
                op = consume_ops[0]
                context = {"consumeAll": op.consumeAll, "patch": op.patch}
                pending_id = create_pending_consume(conn, candidates, context)
                chat_result.pendingId = pending_id
                chat_result.itemSuggestion["pendingId"] = pending_id
            return chat_result, [], []

        # 单候选：graph 找到了唯一匹配，也需要用户确认后执行
        for operation in consume_ops:
            candidates = match_items(inventory, operation.target)
            if not candidates:
                return (
                    ChatResult(
                        intent=chat_result.intent,
                        replyText="我暂时没找到对应物品，请说得更具体一点。",
                        needsConfirmation=True,
                        itemSuggestion={"matches": []},
                    ),
                    [],
                    [],
                )
            if len(candidates) > 1:
                context = {"consumeAll": operation.consumeAll, "patch": operation.patch}
                pending_id = create_pending_consume(conn, candidates[:6], context)
                lines = [f"找到 {len(candidates)} 个匹配物品，请回复序号选择："]
                for i, item in enumerate(candidates[:6], 1):
                    unit_part = f"{item.count}{item.unit}" if item.count else ""
                    lines.append(f"{i}. {item.title} — {item.spaceName}/{item.location} ({unit_part})")
                if operation.consumeAll:
                    lines.append("回复「全部」将清除所有匹配项")
                reply_text = "\n".join(lines)
                return (
                    ChatResult(
                        intent=chat_result.intent,
                        replyText=reply_text,
                        needsConfirmation=True,
                        pendingId=pending_id,
                        itemSuggestion={
                            "pendingId": pending_id,
                            "matches": [item.model_dump() for item in candidates[:6]],
                            "consumeAll": operation.consumeAll,
                        },
                    ),
                    [],
                    [],
                )
            # 单候选也需要确认
            context = {"consumeAll": operation.consumeAll, "patch": operation.patch}
            pending_id = create_pending_consume(conn, candidates, context)
            item = candidates[0]
            unit_part = f"{item.count}{item.unit}" if item.count else ""
            reply_text = (
                f"找到「{item.title}」— {item.spaceName}/{item.location} "
                f"({unit_part}，剩余{item.remainingPct}%)，确认要操作吗？\n"
                f"回复「1」确认，或输入其他内容取消。"
            )
            return (
                ChatResult(
                    intent=chat_result.intent,
                    replyText=reply_text,
                    needsConfirmation=True,
                    pendingId=pending_id,
                    itemSuggestion={
                        "pendingId": pending_id,
                        "matches": [item.model_dump() for item in candidates],
                        "consumeAll": operation.consumeAll,
                    },
                ),
                [],
                [],
            )

    # === 其他操作（update 等）直接执行 ===
    for operation in chat_result.operations:
        candidates = match_items(inventory, operation.target)
        if not candidates:
            return (
                ChatResult(
                    intent=chat_result.intent,
                    replyText="我暂时没找到对应物品，请说得更具体一点。",
                    needsConfirmation=True,
                ),
                [],
                [],
            )
        if len(candidates) > 1:
            return (
                ChatResult(
                    intent=chat_result.intent,
                    replyText="我找到了多个候选物品，麻烦你说得更具体一点。",
                    itemSuggestion=build_candidate_suggestion(candidates),
                    needsConfirmation=True,
                ),
                [],
                [],
            )

        target_item = candidates[0]
        patch = operation.patch or {}
        updated = upsert_item(conn, apply_item_patch(target_item, patch))
        updated_items.append(updated)

    return chat_result, updated_items, deleted_ids


@router.get("/health")
def health():
    return {
        "ok": True,
        "databasePath": str(settings.database_path),
        "markdownPath": str(settings.markdown_path),
        "vectorStore": "chroma" if vector_store.enabled else "keyword-fallback",
    }


@router.get("/state", response_model=AppState)
def read_state():
    with connect() as conn:
        return get_state(conn)


@router.put("/state", response_model=AppState)
def write_state(patch: dict):
    with connect() as conn:
        current = get_state(conn).model_dump()
        current.update(patch)
        state = replace_state(conn, AppState.model_validate(current))
    sync_inventory_markdown(state)
    vector_store.upsert_items(state.items)
    return state


@router.get("/items")
def read_items(status: str = Query(default="all")):
    with connect() as conn:
        items = list_items(conn)
    if status != "all":
        items = [item for item in items if item_status(item) == status]
    return {"items": items}


@router.post("/items", response_model=Item, status_code=201)
def create_item(item: Item):
    logger.info(
        "Creating inventory item title=%r spaceId=%r spaceName=%r location=%r",
        item.title,
        item.spaceId,
        item.spaceName,
        item.location,
    )
    try:
        with connect() as conn:
            created = upsert_item(conn, item)
            state = get_state(conn)
        sync_inventory_markdown(state)
        vector_store.upsert_items([created])
        logger.info(
            "Created inventory item id=%r title=%r totalItems=%d",
            created.id,
            created.title,
            len(state.items),
        )
        return created
    except Exception:
        logger.exception("Failed to create inventory item title=%r", item.title)
        raise


@router.patch("/items/{item_id}", response_model=Item)
def patch_item(item_id: str, patch: dict):
    with connect() as conn:
        existing = next((item for item in list_items(conn) if item.id == item_id), None)
        if not existing:
            raise HTTPException(status_code=404, detail="Item not found")
        updated = upsert_item(conn, apply_item_patch(existing, patch))
        state = get_state(conn)
    sync_inventory_markdown(state)
    vector_store.upsert_items([updated])
    return updated


@router.delete("/items/expired")
def clear_expired():
    with connect() as conn:
        items = list_items(conn)
        expired = [item for item in items if item_status(item) == "danger"]
        for item in expired:
            if item.id:
                delete_item(conn, item.id)
                vector_store.delete_item(item.id)
        state = get_state(conn)
    sync_inventory_markdown(state)
    return {"ok": True, "removed": len(expired)}


@router.delete("/items/{item_id}")
def remove_item(item_id: str):
    with connect() as conn:
        removed = delete_item(conn, item_id)
        state = get_state(conn)
    if not removed:
        raise HTTPException(status_code=404, detail="Item not found")
    sync_inventory_markdown(state)
    vector_store.delete_item(item_id)
    return {"ok": True}


@router.post("/lightning")
def lightning(request: TextRequest):
    logger.info("Lightning parse requested textLength=%d text=%r", len(request.text), request.text)
    try:
        items = ai_service.parse_inventory_command(request.text)
        logger.info(
            "Lightning parse completed parsedCount=%d titles=%s",
            len(items),
            [item.title for item in items],
        )
        return {"items": items}
    except Exception:
        logger.exception("Lightning parse failed text=%r", request.text)
        raise


@router.post("/cli/add", status_code=201)
def cli_add(request: TextRequest):
    logger.info("CLI add requested textLength=%d text=%r", len(request.text), request.text)
    try:
        parsed = ai_service.parse_inventory_command(request.text)
        logger.info(
            "CLI add parsed parsedCount=%d titles=%s",
            len(parsed),
            [item.title for item in parsed],
        )
        with connect() as conn:
            created = [upsert_item(conn, item) for item in parsed]
            state = get_state(conn)
        sync_inventory_markdown(state)
        vector_store.upsert_items(created)
        logger.info(
            "CLI add completed createdCount=%d ids=%s totalItems=%d",
            len(created),
            [item.id for item in created],
            len(state.items),
        )
        return {"items": created}
    except Exception:
        logger.exception("CLI add failed text=%r", request.text)
        raise


@router.post("/chat")
def chat(request: ChatRequest):
    logger.info("Chat requested historyLength=%d", len(request.chatHistory) if request.chatHistory else 0)
    with connect() as conn:
        history = request.chatHistory or list_messages(conn)
        latest = history[-1].text if history else ""
        inventory = list_items(conn)

        # === 加载持久化的跨轮次状态 ===
        conv_state = get_conversation_state(conn)
        interaction_mode = conv_state["interaction_mode"]
        pending_selection = conv_state["pending_item_selection"]
        pending_operation = conv_state.get("pending_operation")
        last_added_item = conv_state.get("last_added_item")
        current_context_item = conv_state.get("current_context_item")

        # 将完整状态注入 graph
        graph_result = ai_service.chat(
            latest,
            inventory,
            interaction_mode=interaction_mode,
            pending_item_selection=pending_selection,
            pending_operation=pending_operation,
            last_added_item=last_added_item,
            current_context_item=current_context_item,
        )
        chat_result = graph_result.get("chat_result", ChatResult())

        # === 从 graph 返回的交互状态写回 SQLite ===
        new_mode = graph_result.get("interaction_mode") or "normal"
        new_selection = graph_result.get("pending_item_selection") or None
        new_operation = graph_result.get("pending_operation") or None
        new_last_added = graph_result.get("last_added_item") if "last_added_item" in graph_result else last_added_item
        new_context_item = graph_result.get("current_context_item") if "current_context_item" in graph_result else current_context_item
        save_conversation_state(conn, new_mode, new_selection, new_operation, new_last_added, new_context_item)

        # === 如果 graph 确认了物品选择，直接执行操作 ===
        if chat_result.confirmedItemId is not None:
            item_id = chat_result.confirmedItemId

            # 情况 1：属性修改（confirmedPatch）
            if chat_result.confirmedPatch:
                target_item = next((it for it in inventory if it.id == item_id), None)
                if not target_item:
                    current_items = list_items(conn)
                    target_item = next((it for it in current_items if it.id == item_id), None)
                if target_item:
                    upsert_item(conn, apply_item_patch(target_item, chat_result.confirmedPatch))
                    reply_text = chat_result.replyText or f"已更新「{target_item.title}」。"
                else:
                    reply_text = "该物品已不存在，可能已被其他操作处理。"
                chat_result.replyText = reply_text

            # 情况 2：全部清除
            elif chat_result.confirmedAllItems:
                deleted_titles: list[str] = []
                if pending_selection:
                    for sel in pending_selection:
                        sel_id = sel.get("id")
                        if sel_id:
                            delete_item(conn, sel_id)
                            deleted_titles.append(sel.get("title", ""))
                unique_titles = list(dict.fromkeys(deleted_titles))
                reply_text = f"已清除所有匹配物品：{'、'.join(unique_titles)}。" if unique_titles else "已批量清除。"
                chat_result.replyText = reply_text

            # 情况 3：消耗/删除单个物品
            else:
                target_item = next((it for it in inventory if it.id == item_id), None)
                if not target_item:
                    current_items = list_items(conn)
                    target_item = next((it for it in current_items if it.id == item_id), None)
                if target_item:
                    deduct_count = chat_result.confirmedDeductCount
                    if deduct_count is not None and deduct_count > 0:
                        if deduct_count >= target_item.count:
                            delete_item(conn, item_id)
                            reply_text = f"已消耗完「{target_item.title}」（{target_item.count}{target_item.unit}），已从库存移除。"
                        else:
                            new_count = target_item.count - deduct_count
                            new_pct = max(0, round(new_count / max(target_item.count, 1) * 100))
                            upsert_item(conn, apply_item_patch(target_item, {"count": new_count, "remainingPct": new_pct}))
                            reply_text = f"已消耗 {deduct_count}{target_item.unit}「{target_item.title}」，剩余 {new_count}{target_item.unit}。"
                    else:
                        if target_item.count > 1:
                            new_count = target_item.count - 1
                            new_pct = max(0, round(new_count / max(target_item.count, 1) * 100))
                            upsert_item(conn, apply_item_patch(target_item, {"count": new_count, "remainingPct": new_pct}))
                            reply_text = f"已消耗 1{target_item.unit}「{target_item.title}」，剩余 {new_count}{target_item.unit}。"
                        else:
                            delete_item(conn, item_id)
                            reply_text = f"已消耗完「{target_item.title}」，已从库存移除。"
                else:
                    reply_text = "该物品已不存在，可能已被其他操作处理。"
                chat_result.replyText = reply_text

            # 构造确认消息
            from uuid import uuid4
            confirm_message = Message(
                id=f"msg-consume-{uuid4().hex[:8]}",
                sender="assistant",
                text=reply_text,
                timestamp="刚刚",
            )
            history.append(confirm_message)
            replace_messages(conn, history)
            state = get_state(conn)

            sync_inventory_markdown(state)
            vector_store.upsert_items(state.items)

            return {
                "reply": reply_text,
                "messages": history,
                "items": state.items,
            }

        # === 剩余逻辑：原有的 execute_chat_operations + 消息存储 ===
        chat_result, updated_items, deleted_ids = execute_chat_operations(chat_result, conn, inventory)
        full_history = history.copy()
        assistant_message = Message(
            id=f"msg-ai-{uuid.uuid4().hex[:8]}",
            sender="assistant",
            text=chat_result.replyText,
            timestamp="刚刚",
            itemSuggestion=chat_result.itemSuggestion,
        )
        full_history.append(assistant_message)
        replace_messages(conn, full_history)
        state = get_state(conn)

    # === 有 pending 时不执行 sync_outputs ===
    if chat_result.pendingId:
        return {
            "reply": chat_result.replyText,
            "needsConfirmation": True,
            "itemSuggestion": chat_result.itemSuggestion,
            "pendingId": chat_result.pendingId,
            "messages": full_history,
            "items": state.items,
        }

    if updated_items or deleted_ids:
        sync_inventory_markdown(state)
        if updated_items:
            vector_store.upsert_items(updated_items)
        for item_id in deleted_ids:
            vector_store.delete_item(item_id)

    return {
        "reply": chat_result.replyText,
        "itemSuggestion": chat_result.itemSuggestion,
        "messages": full_history,
        "items": state.items,
    }


@router.post("/chat/confirm")
def confirm_items(request: ConfirmRequest):
    from uuid import uuid4

    logger.info("Confirming pending items pendingId=%s count=%d", request.pendingId, len(request.items))
    with connect() as conn:
        pending = get_pending_confirmation(conn, request.pendingId)
        if not pending:
            raise HTTPException(status_code=404, detail="确认请求已过期或不存在，请重新输入。")

        created = [upsert_item(conn, item) for item in request.items]
        delete_pending_confirmation(conn, request.pendingId)

        # 保存最近新增物品（支持近指代查询）
        if created:
            conv_state = get_conversation_state(conn)
            save_conversation_state(
                conn,
                interaction_mode=conv_state.get("interaction_mode", "normal"),
                pending_item_selection=conv_state.get("pending_item_selection"),
                pending_operation=conv_state.get("pending_operation"),
                last_added_item=created[-1].model_dump(),
            )

        state = get_state(conn)

    sync_inventory_markdown(state)
    vector_store.upsert_items(created)

    titles = "、".join(f"{item.title}×{item.count}" for item in created)
    reply_text = f"确认入库，已新增 {len(created)} 件物品：{titles}。"
    confirm_message = Message(
        id=f"msg-confirm-{uuid4().hex[:8]}",
        sender="assistant",
        text=reply_text,
        timestamp="刚刚",
    )
    with connect() as conn:
        all_messages = list_messages(conn)
        all_messages.append(confirm_message)
        replace_messages(conn, all_messages)

    return {
        "ok": True,
        "items": state.items,
        "messages": all_messages,
    }


@router.post("/chat/consume-confirm")
def confirm_consume(request: ConsumeConfirmRequest):
    from uuid import uuid4

    logger.info("Confirming consume pendingId=%s selectedIndex=%d", request.pendingId, request.selectedIndex)
    with connect() as conn:
        result = get_pending_consume(conn, request.pendingId)
        if not result:
            raise HTTPException(status_code=404, detail="确认请求已过期或不存在，请重新输入。")

        candidates, context = result
        if request.selectedIndex >= len(candidates):
            raise HTTPException(status_code=400, detail="选择的物品索引无效。")

        target_item = candidates[request.selectedIndex]
        consume_all = request.consumeAll or context.get("consumeAll", False)

        if consume_all:
            # 全部消耗/删除
            if target_item.id:
                delete_item(conn, target_item.id)
            reply_text = f"已清除「{target_item.title}」。"
        else:
            # 部分消耗
            patch = context.get("patch") or {}
            if request.count is not None:
                new_count = max(0, target_item.count - request.count)
                new_pct = 0 if target_item.count <= 0 else max(0, round(new_count / target_item.count * 100))
                patch = {"count": new_count, "remainingPct": new_pct}
            elif not patch:
                patch = {"remainingPct": 0, "count": 0}

            if patch.get("remainingPct", 100) == 0 and patch.get("count", 1) == 0:
                if target_item.id:
                    delete_item(conn, target_item.id)
                reply_text = f"已清除「{target_item.title}」。"
            else:
                upsert_item(conn, apply_item_patch(target_item, patch))
                remaining = patch.get("remainingPct", target_item.remainingPct)
                reply_text = f"已更新「{target_item.title}」，剩余 {remaining}%。"

        delete_pending_confirmation(conn, request.pendingId)
        state = get_state(conn)

    sync_inventory_markdown(state)
    vector_store.upsert_items(state.items)

    confirm_message = Message(
        id=f"msg-consume-{uuid4().hex[:8]}",
        sender="assistant",
        text=reply_text,
        timestamp="刚刚",
    )
    with connect() as conn:
        all_messages = list_messages(conn)
        all_messages.append(confirm_message)
        replace_messages(conn, all_messages)

    return {
        "ok": True,
        "items": state.items,
        "messages": all_messages,
    }


@router.get("/messages")
def read_messages():
    with connect() as conn:
        return {"messages": list_messages(conn)}


@router.put("/messages")
def write_messages(messages: list[Message]):
    with connect() as conn:
        replace_messages(conn, messages)
        stored = list_messages(conn)
    return {"messages": stored}


@router.delete("/messages")
def clear_messages():
    reset_message = Message(
        id="msg-init-reset",
        sender="assistant",
        text="聊天记录已经清空，我们可以重新开始。",
        timestamp="刚刚",
        type="welcome",
    )
    with connect() as conn:
        replace_messages(conn, [reset_message])
    return {"messages": [reset_message]}


@router.post("/recipe")
def recipe(request: RecipeRequest):
    with connect() as conn:
        inventory = request.inventory or list_items(conn)
    result = ai_service.recipe(request, inventory)
    return {"recipe_recommend": result.get("recipe_recommend"), "isFallback": result.get("isFallback", True), "fallbackText": result.get("fallbackText")}


@router.post("/export")
def export_inventory(format: str = "md"):
    if format != "md":
        raise HTTPException(status_code=400, detail="Only md export is supported")
    state = sync_outputs()
    return {"ok": True, "path": str(settings.markdown_path), "items": len(state.items)}


@router.get("/search")
def search(q: str):
    with connect() as conn:
        items = list_items(conn)
    return {"items": vector_store.search(q, items)}


init_db()

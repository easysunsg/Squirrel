import json
import logging
import uuid
from typing import Any, Generator

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ValidationError

from app.core.config import settings
from app.db.sqlite import (
    connect,
    create_pending_confirmation,
    create_pending_consume,
    delete_item,
    delete_items_batch,
    delete_pending_confirmation,
    get_conversation_state,
    get_pending_confirmation,
    get_pending_consume,
    get_state,
    init_db,
    join_all_items,
    list_items,
    list_messages,
    replace_messages,
    replace_state,
    save_conversation_state,
    upsert_item,
)
from app.models.schemas import AppState, ChatRequest, ChatResult, ConfirmRequest, ConsumeConfirmRequest, Item, Message, RecipeRequest, TextRequest
from app.services.ai import ai_service
from app.services.conflict_service import ConflictService
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


conflict_service = ConflictService()


def _materialize_db_operations(conn, db_ops: dict) -> tuple[list[Item], str | None, list[Item] | None]:
    """Route layer — pure DB plumbing, ZERO business logic.

    Takes db_operations dict from graph and materializes them into SQL writes.
    Returns (updated_items, pending_id, pending_items).
    """
    updated_items: list[Item] = []

    # upsert_items
    for item in db_ops.get("upsert_items", []):
        created = upsert_item(conn, item)
        updated_items.append(created)

    # delete_ids
    for item_id in db_ops.get("delete_ids", []):
        delete_item(conn, item_id)

    # pending_add — create pending confirmation records
    pending_items = db_ops.get("pending_add", [])
    pending_consume = db_ops.get("pending_consume", {})

    if pending_items:
        pending_id = create_pending_confirmation(conn, pending_items)
        # Return pending_id to caller so it can be attached to chat_result
        return updated_items, pending_id, pending_items

    if pending_consume:
        candidates = pending_consume.get("candidates", [])
        context = pending_consume.get("context", {})
        if candidates:
            pending_id = create_pending_consume(conn, candidates, context)
            return updated_items, pending_id, candidates

    return updated_items, None, None


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
    return StreamingResponse(
        _chat_sse(request),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


class PydanticEncoder(json.JSONEncoder):
    """JSON encoder that handles Pydantic BaseModel objects."""
    def default(self, obj):
        if isinstance(obj, BaseModel):
            return obj.model_dump()
        return super().default(obj)


def _chat_sse(request: ChatRequest) -> Generator[str, None, None]:
    """SSE generator yielding status/result/error events for /api/chat."""

    def _event(event_type: str, data: Any) -> str:
        return f"event: {event_type}\ndata: {json.dumps(data, ensure_ascii=False, cls=PydanticEncoder)}\n\n"

    try:
        yield _event("status", {"stage": "processing"})
        result = _process_chat(request)
        yield _event("status", {"stage": "complete"})
        yield _event("result", result)
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Chat SSE failed")
        yield _event("error", {"detail": str(e)})


def _process_chat(request: ChatRequest) -> dict:
    """Core chat processing — runs the graph, materializes db_operations, returns response dict."""
    with connect() as conn:
        history = request.chatHistory or list_messages(conn)
        latest = history[-1].text if history else ""
        inventory = join_all_items(conn)

        # === 加载持久化的跨轮次状态 ===
        conv_state = get_conversation_state(conn, request.userId)
        interaction_mode = conv_state["interaction_mode"]
        pending_selection = conv_state["pending_item_selection"]
        pending_operation = conv_state.get("pending_operation")
        last_added_item = conv_state.get("last_added_item")
        current_context_item = conv_state.get("current_context_item")

        if request.confirmation and pending_operation:
            latest = "确认" if request.confirmation.decision == "confirm" else "取消"
            if request.confirmation.items and pending_operation.get("type") == "add":
                pending_operation = {
                    **pending_operation,
                    "patch": {
                        **(pending_operation.get("patch") or {}),
                        "items_data": [item.model_dump() for item in request.confirmation.items],
                    },
                }

        # === 将完整状态注入 graph（所有业务逻辑都在 graph 中执行） ===
        graph_result = ai_service.chat(
            latest,
            inventory,
            interaction_mode=interaction_mode,
            pending_item_selection=pending_selection,
            pending_operation=pending_operation,
            last_added_item=last_added_item,
            current_context_item=current_context_item,
            current_user_id=request.userId,
            current_user_name=request.userName,
        )
        chat_result = graph_result.get("chat_result", ChatResult())
        if not chat_result.replyText.strip():
            logger.warning("Graph returned an empty chat reply; using fallback")
            chat_result.replyText = "收到，管家已为您处理完毕。"
        db_ops = graph_result.get("db_operations", {})

        # === 冲突检测（在物化之前执行） ===
        conflict_skus = getattr(chat_result, "conflictCheckSkus", [])
        for sku_title in conflict_skus:
            warning = conflict_service.check_recent_same_sku(
                conn, sku_title, request.userName, window_hours=3
            )
            if warning:
                warning_text = f"⚠️ {warning.warning_text}"
                chat_result.replyText = warning_text + "\n\n" + (chat_result.replyText or "")
                chat_result.needsConfirmation = True

        # === 从 graph 返回的交互状态写回 SQLite ===
        new_mode = graph_result.get("interaction_mode") or "normal"
        new_selection = graph_result.get("pending_item_selection") or None
        new_operation = graph_result.get("pending_operation") or None
        new_last_added = graph_result.get("last_added_item") if "last_added_item" in graph_result else last_added_item
        new_context_item = graph_result.get("current_context_item") if "current_context_item" in graph_result else current_context_item
        save_conversation_state(
            conn,
            new_mode,
            new_selection,
            new_operation,
            new_last_added,
            new_context_item,
            user_id=request.userId,
        )

        # === 物化 DB 操作（纯数据管道，无业务逻辑） ===
        updated_items, pending_id, pending_items = _materialize_db_operations(conn, db_ops)

        if updated_items and chat_result.intent == "add":
            created = updated_items[-1]
            new_last_added = created.model_dump()
            new_context_item = {
                "id": created.id,
                "title": created.title,
                "location": created.location,
                "spaceName": created.spaceName,
                "count": created.count,
                "unit": created.unit,
            }
            save_conversation_state(
                conn,
                "normal",
                None,
                None,
                new_last_added,
                new_context_item,
                user_id=request.userId,
            )

        if chat_result.confirmedItemIds or chat_result.confirmedItemId is not None:
            # confirmed 路径：已有 replyText，构造确认消息
            reply_text = chat_result.replyText or "操作已完成。"
            confirm_message = Message(
                id=f"msg-batch-{uuid.uuid4().hex[:8]}",
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

        # === pending 路径 ===
        if pending_id and pending_items is not None:
            chat_result.pendingId = pending_id
            if db_ops.get("pending_consume"):
                # Consume selection — send as matches for frontend inline buttons
                consume_ctx = db_ops["pending_consume"].get("context", {})
                chat_result.itemSuggestion = {
                    "pendingId": pending_id,
                    "matches": [
                        item.model_dump() if isinstance(item, BaseModel) else item
                        for item in pending_items
                    ],
                    "consumeAll": consume_ctx.get("consumeAll", False),
                }
            elif chat_result.itemSuggestion:
                chat_result.itemSuggestion["pendingId"] = pending_id
            else:
                chat_result.itemSuggestion = {
                    "pendingId": pending_id,
                    "items": [item.model_dump() for item in pending_items],
                }
            chat_result.needsConfirmation = True

        # === 构建消息 ===
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

    # === 有 pending 时不执行 sync_outputs（等用户确认） ===
    if chat_result.pendingId:
        return {
            "reply": chat_result.replyText,
            "needsConfirmation": True,
            "itemSuggestion": chat_result.itemSuggestion,
            "pendingId": chat_result.pendingId,
            "messages": full_history,
            "items": state.items,
        }

    if updated_items:
        sync_inventory_markdown(state)
        vector_store.upsert_items(updated_items)

    return {
        "reply": chat_result.replyText,
        "needsConfirmation": chat_result.needsConfirmation,
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
                current_context_item=created[-1].model_dump(),
            )

        state = get_state(conn)

    sync_inventory_markdown(state)
    vector_store.upsert_items(created)

    titles = "、".join(f"{item.title}×{item.count}{item.unit}" for item in created)
    reply_text = f"确认入库，已新增 {len(created)} 个批次：{titles}。"
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

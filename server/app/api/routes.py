from fastapi import APIRouter, HTTPException, Query

from app.core.config import settings
from app.db.sqlite import connect, delete_item, get_state, init_db, list_items, replace_state, upsert_item
from app.models.schemas import AppState, ChatRequest, Item, RecipeRequest, TextRequest
from app.services.ai import ai_service
from app.services.markdown import item_status, sync_inventory_markdown
from app.services.vector_store import vector_store

router = APIRouter(prefix="/api")


def sync_outputs() -> AppState:
    with connect() as conn:
        state = get_state(conn)
    sync_inventory_markdown(state)
    vector_store.upsert_items(state.items)
    return state


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
    with connect() as conn:
        created = upsert_item(conn, item)
        state = get_state(conn)
    sync_inventory_markdown(state)
    vector_store.upsert_items([created])
    return created


@router.patch("/items/{item_id}", response_model=Item)
def patch_item(item_id: str, patch: dict):
    with connect() as conn:
        existing = next((item for item in list_items(conn) if item.id == item_id), None)
        if not existing:
            raise HTTPException(status_code=404, detail="Item not found")
        data = existing.model_dump()
        data.update(patch)
        data["id"] = item_id
        updated = upsert_item(conn, Item.model_validate(data))
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
    return {"items": ai_service.parse_inventory_command(request.text)}


@router.post("/cli/add", status_code=201)
def cli_add(request: TextRequest):
    parsed = ai_service.parse_inventory_command(request.text)
    with connect() as conn:
        created = [upsert_item(conn, item) for item in parsed]
        state = get_state(conn)
    sync_inventory_markdown(state)
    vector_store.upsert_items(created)
    return {"items": created}


@router.post("/chat")
def chat(request: ChatRequest):
    latest = request.chatHistory[-1].text if request.chatHistory else ""
    with connect() as conn:
        inventory = request.currentInventory or list_items(conn)
    return {"text": ai_service.chat(latest, inventory), "cardData": None}


@router.post("/recipe")
def recipe(request: RecipeRequest):
    with connect() as conn:
        inventory = request.inventory or list_items(conn)
    return {"recipe": ai_service.recipe(request, inventory)}


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

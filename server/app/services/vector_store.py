from app.core.config import settings
from app.models.schemas import Item


class VectorStore:
    def __init__(self) -> None:
        self._collection = None
        if not settings.chroma_enabled:
            return
        try:
            import chromadb

            client = chromadb.PersistentClient(path=str(settings.chroma_path))
            self._collection = client.get_or_create_collection("squirrel_inventory")
        except Exception:
            self._collection = None

    @property
    def enabled(self) -> bool:
        return self._collection is not None

    def upsert_items(self, items: list[Item]) -> None:
        if not self._collection or not items:
            return
        try:
            self._collection.upsert(
                ids=[item.id or item.title for item in items],
                documents=[f"{item.title} {item.spaceName} {item.location} {item.remark or ''}" for item in items],
                metadatas=[
                    {
                        "title": item.title,
                        "spaceName": item.spaceName,
                        "location": item.location,
                    }
                    for item in items
                ],
            )
        except Exception:
            self._collection = None

    def delete_item(self, item_id: str) -> None:
        if not self._collection:
            return
        try:
            self._collection.delete(ids=[item_id])
        except Exception:
            self._collection = None

    def search(self, query: str, fallback_items: list[Item], limit: int = 8) -> list[Item]:
        if self._collection:
            try:
                result = self._collection.query(query_texts=[query], n_results=limit)
                ids = set(result.get("ids", [[]])[0])
                return [item for item in fallback_items if item.id in ids]
            except Exception:
                pass
        lowered = query.lower()
        return [
            item
            for item in fallback_items
            if (
                lowered in item.title.lower()
                or lowered in item.location.lower()
                or lowered in (item.remark or "").lower()
            )
        ][:limit]


vector_store = VectorStore()

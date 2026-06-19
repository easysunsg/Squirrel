from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import date, timedelta
from uuid import uuid4

from app.core.config import settings
from app.models.schemas import AppState, Item, Message, Space, SystemPreferences


def today_iso() -> str:
    return date.today().isoformat()


def days_from_now(days: int) -> str:
    return (date.today() + timedelta(days=days)).isoformat()


DEFAULT_SPACES = [
    Space(id="kitchen", name="主厨房", icon="kitchen", bgClass="bg-primary-fixed", textColor="text-primary"),
    Space(
        id="storage",
        name="储藏间",
        icon="shelves",
        bgClass="bg-tertiary-fixed",
        textColor="text-tertiary",
        badgeColor="bg-surface-container-high",
    ),
    Space(
        id="garage",
        name="车库工具",
        icon="garage",
        bgClass="bg-secondary-fixed",
        textColor="text-secondary",
        badgeColor="bg-surface-container-high",
    ),
]

DEFAULT_ITEMS = [
    Item(
        id="item-1",
        title="全麦面包",
        spaceId="kitchen",
        spaceName="主厨房",
        location="厨房二级柜",
        remainingPct=15,
        buyDate="2026-06-01",
        expireDate="2026-06-08",
        tag="告急",
        count=1,
        unit="袋",
        icon="bakery_dining",
        remark="每日早餐用，临近过期需尽快食用。",
    ),
    Item(
        id="item-2",
        title="五金工具箱",
        spaceId="garage",
        spaceName="车库工具",
        location="车库 A4 搁板",
        remainingPct=85,
        buyDate="2025-12-15",
        expireDate="2029-12-15",
        tag="充足",
        count=8,
        unit="件",
        icon="construction",
        remark="包含螺栓螺母，完备度较高。",
    ),
    Item(
        id="item-3",
        title="常备维C",
        spaceId="storage",
        spaceName="储藏间",
        location="药品箱 B",
        remainingPct=20,
        buyDate="2024-06-05",
        expireDate="2026-06-20",
        tag="过期预警",
        count=1,
        unit="瓶",
        icon="medication",
        remark="泡腾片形式，还有约15天过期。",
    ),
]

DEFAULT_MESSAGES = [
    Message(
        id="msg-1",
        sender="assistant",
        text="嘿！我是你的松鼠管家。今天想整理点什么？你可以发照片给我，或者直接告诉我。",
        type="welcome",
    ),
]


@contextmanager
def connect():
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(settings.database_path)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with connect() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS spaces (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                icon TEXT NOT NULL,
                bg_class TEXT NOT NULL,
                text_color TEXT NOT NULL,
                badge_color TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS items (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                category TEXT NOT NULL DEFAULT 'other',
                space_id TEXT NOT NULL,
                space_name TEXT NOT NULL,
                location TEXT NOT NULL,
                remaining_pct INTEGER NOT NULL,
                buy_date TEXT NOT NULL,
                expire_date TEXT NOT NULL,
                tag TEXT NOT NULL,
                count INTEGER NOT NULL,
                unit TEXT NOT NULL,
                remind_days_before INTEGER NOT NULL DEFAULT 5,
                tags TEXT,
                remark TEXT,
                icon TEXT NOT NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS messages (
                id TEXT PRIMARY KEY,
                sender TEXT NOT NULL,
                text TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                type TEXT NOT NULL,
                voice_duration TEXT,
                action_card TEXT,
                item_suggestion TEXT
            );

            CREATE TABLE IF NOT EXISTS preferences (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                data TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS app_meta (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS pending_confirmation (
                id TEXT PRIMARY KEY,
                items TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS conversation_state (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                interaction_mode TEXT NOT NULL DEFAULT 'normal',
                pending_item_selection TEXT
            );
            """
        )

        item_columns = {row["name"] for row in conn.execute("PRAGMA table_info(items)").fetchall()}
        if "category" not in item_columns:
            conn.execute("ALTER TABLE items ADD COLUMN category TEXT NOT NULL DEFAULT 'other'")
        if "remind_days_before" not in item_columns:
            conn.execute("ALTER TABLE items ADD COLUMN remind_days_before INTEGER NOT NULL DEFAULT 5")
        if "tags" not in item_columns:
            conn.execute("ALTER TABLE items ADD COLUMN tags TEXT")

        message_columns = {row["name"] for row in conn.execute("PRAGMA table_info(messages)").fetchall()}
        if "item_suggestion" not in message_columns:
            conn.execute("ALTER TABLE messages ADD COLUMN item_suggestion TEXT")

        pending_columns = {row["name"] for row in conn.execute("PRAGMA table_info(pending_confirmation)").fetchall()}
        if "type" not in pending_columns:
            conn.execute("ALTER TABLE pending_confirmation ADD COLUMN type TEXT NOT NULL DEFAULT 'add'")
        if "context" not in pending_columns:
            conn.execute("ALTER TABLE pending_confirmation ADD COLUMN context TEXT")

        if conn.execute("SELECT COUNT(*) FROM spaces").fetchone()[0] == 0:
            replace_spaces(conn, DEFAULT_SPACES)
        if conn.execute("SELECT COUNT(*) FROM items").fetchone()[0] == 0:
            for item in DEFAULT_ITEMS:
                upsert_item(conn, item)
        if conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0] == 0:
            replace_messages(conn, DEFAULT_MESSAGES)
        if conn.execute("SELECT COUNT(*) FROM preferences").fetchone()[0] == 0:
            set_preferences(conn, SystemPreferences())
        conn.execute("INSERT OR IGNORE INTO app_meta(key, value) VALUES('onboardingDone', 'true')")


def normalize_item(item: Item) -> Item:
    data = item.model_copy(deep=True)
    data.id = data.id or f"item-{uuid4().hex[:12]}"
    data.buyDate = data.buyDate or today_iso()
    data.expireDate = data.expireDate or ""
    if not data.tag:
        data.tag = "告急" if data.remainingPct < 20 else "较低" if data.remainingPct < 50 else "充足"
    if not data.spaceId:
        if data.spaceName == "车库工具":
            data.spaceId = "garage"
        elif data.spaceName == "储藏间":
            data.spaceId = "storage"
        else:
            data.spaceId = "kitchen"
    return data


def row_to_item(row: sqlite3.Row) -> Item:
    return Item(
        id=row["id"],
        title=row["title"],
        category=row["category"],
        spaceId=row["space_id"],
        spaceName=row["space_name"],
        location=row["location"],
        remainingPct=row["remaining_pct"],
        buyDate=row["buy_date"],
        expireDate=row["expire_date"],
        tag=row["tag"],
        count=row["count"],
        unit=row["unit"],
        remindDaysBefore=row["remind_days_before"],
        tags=json.loads(row["tags"]) if row["tags"] else [],
        remark=row["remark"],
        icon=row["icon"],
    )


def list_items(conn: sqlite3.Connection) -> list[Item]:
    rows = conn.execute("SELECT * FROM items ORDER BY created_at DESC, id DESC").fetchall()
    return [row_to_item(row) for row in rows]


def upsert_item(conn: sqlite3.Connection, item: Item) -> Item:
    item = normalize_item(item)
    conn.execute(
        """
        INSERT INTO items(
            id, title, category, space_id, space_name, location, remaining_pct,
            buy_date, expire_date, tag, count, unit, remind_days_before, tags, remark, icon
        )
        VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            title=excluded.title,
            category=excluded.category,
            space_id=excluded.space_id,
            space_name=excluded.space_name,
            location=excluded.location,
            remaining_pct=excluded.remaining_pct,
            buy_date=excluded.buy_date,
            expire_date=excluded.expire_date,
            tag=excluded.tag,
            count=excluded.count,
            unit=excluded.unit,
            remind_days_before=excluded.remind_days_before,
            tags=excluded.tags,
            remark=excluded.remark,
            icon=excluded.icon,
            updated_at=CURRENT_TIMESTAMP
        """,
        (
            item.id,
            item.title,
            item.category,
            item.spaceId,
            item.spaceName,
            item.location,
            item.remainingPct,
            item.buyDate,
            item.expireDate,
            item.tag,
            item.count,
            item.unit,
            item.remindDaysBefore,
            json.dumps(item.tags, ensure_ascii=False),
            item.remark,
            item.icon,
        ),
    )
    return item


def delete_item(conn: sqlite3.Connection, item_id: str) -> bool:
    cur = conn.execute("DELETE FROM items WHERE id = ?", (item_id,))
    return cur.rowcount > 0


def replace_spaces(conn: sqlite3.Connection, spaces: list[Space]) -> None:
    conn.execute("DELETE FROM spaces")
    for space in spaces:
        conn.execute(
            "INSERT INTO spaces(id, name, icon, bg_class, text_color, badge_color) VALUES(?, ?, ?, ?, ?, ?)",
            (space.id, space.name, space.icon, space.bgClass, space.textColor, space.badgeColor),
        )


def list_spaces(conn: sqlite3.Connection, items: list[Item]) -> list[Space]:
    rows = conn.execute("SELECT * FROM spaces ORDER BY rowid").fetchall()
    spaces = []
    for row in rows:
        space_items = [item for item in items if item.spaceId == row["id"] or item.spaceName == row["name"]]
        spaces.append(
            Space(
                id=row["id"],
                name=row["name"],
                icon=row["icon"],
                count=len(space_items),
                warnCount=len([item for item in space_items if item.tag in ("告急", "过期预警")]),
                bgClass=row["bg_class"],
                textColor=row["text_color"],
                badgeColor=row["badge_color"],
            )
        )
    return spaces


def replace_messages(conn: sqlite3.Connection, messages: list[Message]) -> None:
    conn.execute("DELETE FROM messages")
    for message in messages:
        action_card = json.dumps(message.actionCard, ensure_ascii=False) if message.actionCard else None
        item_suggestion = json.dumps(message.itemSuggestion, ensure_ascii=False) if message.itemSuggestion else None
        conn.execute(
            """
            REPLACE INTO messages(
                id, sender, text, timestamp, type, voice_duration, action_card, item_suggestion
            )
            VALUES(?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                message.id,
                message.sender,
                message.text,
                message.timestamp,
                message.type,
                message.voiceDuration,
                action_card,
                item_suggestion,
            ),
        )


def list_messages(conn: sqlite3.Connection) -> list[Message]:
    rows = conn.execute("SELECT * FROM messages ORDER BY rowid").fetchall()
    return [
        Message(
            id=row["id"],
            sender=row["sender"],
            text=row["text"],
            timestamp=row["timestamp"],
            type=row["type"],
            voiceDuration=row["voice_duration"],
            actionCard=json.loads(row["action_card"]) if row["action_card"] else None,
            itemSuggestion=json.loads(row["item_suggestion"]) if row["item_suggestion"] else None,
        )
        for row in rows
    ]


def get_preferences(conn: sqlite3.Connection) -> SystemPreferences:
    row = conn.execute("SELECT data FROM preferences WHERE id = 1").fetchone()
    return SystemPreferences.model_validate_json(row["data"]) if row else SystemPreferences()


def set_preferences(conn: sqlite3.Connection, preferences: SystemPreferences) -> None:
    conn.execute(
        "INSERT INTO preferences(id, data) VALUES(1, ?) ON CONFLICT(id) DO UPDATE SET data=excluded.data",
        (preferences.model_dump_json(),),
    )


def get_onboarding_done(conn: sqlite3.Connection) -> bool:
    row = conn.execute("SELECT value FROM app_meta WHERE key = 'onboardingDone'").fetchone()
    return row is None or row["value"] == "true"


def set_onboarding_done(conn: sqlite3.Connection, done: bool) -> None:
    conn.execute(
        """
        INSERT INTO app_meta(key, value)
        VALUES('onboardingDone', ?)
        ON CONFLICT(key) DO UPDATE SET value=excluded.value
        """,
        ("true" if done else "false",),
    )


def get_state(conn: sqlite3.Connection) -> AppState:
    items = list_items(conn)
    return AppState(
        onboardingDone=get_onboarding_done(conn),
        spaces=list_spaces(conn, items),
        items=items,
        messages=list_messages(conn),
        preferences=get_preferences(conn),
    )


def replace_state(conn: sqlite3.Connection, state: AppState) -> AppState:
    replace_spaces(conn, state.spaces)
    conn.execute("DELETE FROM items")
    for item in state.items:
        upsert_item(conn, item)
    replace_messages(conn, state.messages)
    set_preferences(conn, state.preferences)
    set_onboarding_done(conn, state.onboardingDone)
    return get_state(conn)


def create_pending_confirmation(conn: sqlite3.Connection, items: list[Item]) -> str:
    from datetime import datetime
    pending_id = f"pending-{uuid4().hex[:12]}"
    conn.execute(
        "INSERT INTO pending_confirmation(id, items, type, created_at) VALUES(?, ?, ?, ?)",
        (pending_id, json.dumps([item.model_dump() for item in items], ensure_ascii=False), "add", datetime.now().isoformat()),
    )
    return pending_id


def get_pending_confirmation(conn: sqlite3.Connection, pending_id: str) -> list[Item] | None:
    row = conn.execute(
        "SELECT items, created_at FROM pending_confirmation WHERE id = ?",
        (pending_id,),
    ).fetchone()
    if not row:
        return None
    # 惰性清理：超过 30 分钟视为过期
    from datetime import datetime, timedelta
    created = datetime.fromisoformat(row["created_at"])
    if datetime.now() - created > timedelta(minutes=30):
        conn.execute("DELETE FROM pending_confirmation WHERE id = ?", (pending_id,))
        return None
    data = json.loads(row["items"])
    return [Item.model_validate(item) for item in data]


def delete_pending_confirmation(conn: sqlite3.Connection, pending_id: str) -> bool:
    cur = conn.execute("DELETE FROM pending_confirmation WHERE id = ?", (pending_id,))
    return cur.rowcount > 0


def get_conversation_state(conn: sqlite3.Connection) -> dict:
    """Load the persistent conversation state (interaction_mode + pending_item_selection)."""
    row = conn.execute(
        "SELECT interaction_mode, pending_item_selection FROM conversation_state WHERE id = 1"
    ).fetchone()
    return {
        "interaction_mode": row["interaction_mode"] if row else "normal",
        "pending_item_selection": json.loads(row["pending_item_selection"]) if row and row["pending_item_selection"] else None,
    }


def save_conversation_state(conn: sqlite3.Connection, interaction_mode: str, pending_item_selection: list | None) -> None:
    """Save the persistent conversation state."""
    conn.execute(
        """INSERT INTO conversation_state(id, interaction_mode, pending_item_selection)
           VALUES(1, ?, ?)
           ON CONFLICT(id) DO UPDATE SET
               interaction_mode=excluded.interaction_mode,
               pending_item_selection=excluded.pending_item_selection""",
        (interaction_mode, json.dumps(pending_item_selection, ensure_ascii=False) if pending_item_selection else None),
    )


def cleanup_expired_pending(conn: sqlite3.Connection, ttl_minutes: int = 30) -> int:
    from datetime import datetime, timedelta
    cutoff = (datetime.now() - timedelta(minutes=ttl_minutes)).isoformat()
    cur = conn.execute("DELETE FROM pending_confirmation WHERE created_at < ?", (cutoff,))
    return cur.rowcount


def create_pending_consume(conn: sqlite3.Connection, candidates: list[Item], context: dict) -> str:
    from datetime import datetime
    pending_id = f"consume-{uuid4().hex[:12]}"
    conn.execute(
        "INSERT INTO pending_confirmation(id, items, type, context, created_at) VALUES(?, ?, ?, ?, ?)",
        (
            pending_id,
            json.dumps([item.model_dump() for item in candidates], ensure_ascii=False),
            "consume",
            json.dumps(context, ensure_ascii=False),
            datetime.now().isoformat(),
        ),
    )
    return pending_id


def get_pending_consume(conn: sqlite3.Connection, pending_id: str) -> tuple[list[Item], dict] | None:
    row = conn.execute(
        "SELECT items, type, context, created_at FROM pending_confirmation WHERE id = ?",
        (pending_id,),
    ).fetchone()
    if not row:
        return None
    if row["type"] != "consume":
        return None
    from datetime import datetime, timedelta
    created = datetime.fromisoformat(row["created_at"])
    if datetime.now() - created > timedelta(minutes=30):
        conn.execute("DELETE FROM pending_confirmation WHERE id = ?", (pending_id,))
        return None
    candidates = [Item.model_validate(item) for item in json.loads(row["items"])]
    context = json.loads(row["context"]) if row["context"] else {}
    return candidates, context

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import date, timedelta
from uuid import uuid4

from app.core.config import settings
from app.models.schemas import AppState, Item, ItemInstance, Message, SKU, Space, SpatialNode, SystemPreferences


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
                pending_item_selection TEXT,
                pending_operation TEXT,
                last_added_item TEXT,
                current_context_item TEXT
            );

            CREATE TABLE IF NOT EXISTS conversation_states (
                user_id TEXT PRIMARY KEY,
                interaction_mode TEXT NOT NULL DEFAULT 'normal',
                pending_item_selection TEXT,
                pending_operation TEXT,
                last_added_item TEXT,
                current_context_item TEXT
            );

            CREATE TABLE IF NOT EXISTS skus (
                sku_id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                category TEXT NOT NULL DEFAULT 'other',
                unit TEXT NOT NULL DEFAULT '个',
                remind_days_before INTEGER NOT NULL DEFAULT 5,
                tags TEXT,
                icon TEXT NOT NULL DEFAULT 'package_2',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS item_instances (
                instance_id TEXT PRIMARY KEY,
                sku_id TEXT NOT NULL REFERENCES skus(sku_id),
                space_id TEXT NOT NULL DEFAULT 'kitchen',
                location TEXT NOT NULL DEFAULT '默认层架',
                quantity INTEGER NOT NULL DEFAULT 1,
                remaining_pct INTEGER NOT NULL DEFAULT 100,
                buy_date TEXT,
                expire_date TEXT,
                is_opened INTEGER NOT NULL DEFAULT 0,
                opened_date TEXT,
                pao_days INTEGER NOT NULL DEFAULT 0,
                final_expiry_date TEXT,
                remark TEXT,
                belongs_to_slot_id TEXT REFERENCES spatial_nodes(node_id),
                last_modified_by TEXT NOT NULL DEFAULT 'system',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS spatial_nodes (
                node_id TEXT PRIMARY KEY,
                node_type TEXT NOT NULL CHECK(node_type IN ('Zone','Fixture','Container','Slot')),
                parent_id TEXT REFERENCES spatial_nodes(node_id),
                name TEXT NOT NULL,
                aliases TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS conversation_snapshots (
                snapshot_id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                graph_version INTEGER NOT NULL DEFAULT 0,
                execution_mode TEXT NOT NULL DEFAULT 'SUSPENDED',
                is_suspended INTEGER NOT NULL DEFAULT 1,
                suspension_reason TEXT,
                action_queue_snapshot TEXT,
                workspace_snapshot TEXT,
                loop_depth_snapshot INTEGER NOT NULL DEFAULT 0,
                missing_parameters TEXT,
                blocked_action_id TEXT,
                user_choice_options TEXT,
                raw_user_input TEXT,
                normalized_request TEXT,
                memory_state TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                expires_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_snapshots_session
                ON conversation_snapshots(session_id, graph_version);

            CREATE TABLE IF NOT EXISTS checkpoints (
                id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                graph_version INTEGER NOT NULL DEFAULT 0,
                node_name TEXT NOT NULL,
                state_snapshot TEXT NOT NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            );

            CREATE INDEX IF NOT EXISTS idx_checkpoints_session
                ON checkpoints(session_id, graph_version);

            CREATE TABLE IF NOT EXISTS policy_rules (
                rule_id TEXT PRIMARY KEY,
                rule_name TEXT NOT NULL,
                description TEXT,
                rule_type TEXT NOT NULL DEFAULT 'risk_control',
                priority INTEGER NOT NULL DEFAULT 100,
                conditions TEXT NOT NULL,
                action TEXT NOT NULL DEFAULT 'block',
                is_active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS idempotency_keys (
                key TEXT PRIMARY KEY,
                status TEXT NOT NULL DEFAULT 'PENDING',
                result_data TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                completed_at TEXT,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                expires_at TEXT NOT NULL
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

        # conversation_state table — add columns for pending_operation and last_added_item
        cs_columns = {row["name"] for row in conn.execute("PRAGMA table_info(conversation_state)").fetchall()}
        if "pending_operation" not in cs_columns:
            conn.execute("ALTER TABLE conversation_state ADD COLUMN pending_operation TEXT")
        if "last_added_item" not in cs_columns:
            conn.execute("ALTER TABLE conversation_state ADD COLUMN last_added_item TEXT")

        instance_columns = {row["name"] for row in conn.execute("PRAGMA table_info(item_instances)").fetchall()}
        if "remark" not in instance_columns:
            conn.execute("ALTER TABLE item_instances ADD COLUMN remark TEXT")
        conn.execute(
            """UPDATE item_instances
               SET remark = (SELECT items.remark FROM items WHERE items.id = item_instances.instance_id)
               WHERE remark IS NULL
                 AND EXISTS (SELECT 1 FROM items WHERE items.id = item_instances.instance_id)"""
        )

        # === 新表迁移：为旧 items 表中的数据填充 skus + item_instances ===
        sku_table_exists = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='skus'").fetchone()
        if sku_table_exists and conn.execute("SELECT COUNT(*) FROM item_instances").fetchone()[0] == 0:
            old_items = conn.execute("SELECT * FROM items").fetchall()
            for row in old_items:
                title = row["title"]
                # Create or find SKU
                existing_sku = conn.execute("SELECT sku_id FROM skus WHERE title = ?", (title,)).fetchone()
                if existing_sku:
                    sku_id = existing_sku["sku_id"]
                else:
                    sku_id = f"sku-{uuid4().hex[:12]}"
                    conn.execute(
                        """INSERT INTO skus(sku_id, title, category, unit, remind_days_before, tags, icon)
                           VALUES(?, ?, ?, ?, ?, ?, ?)""",
                        (sku_id, title, row["category"], row["unit"], row["remind_days_before"],
                         row["tags"], row["icon"]),
                    )
                # Create instance
                instance_id = row["id"]  # reuse old item ID as instance_id
                conn.execute(
                    """INSERT INTO item_instances(
                        instance_id, sku_id, space_id, location, quantity, remaining_pct,
                        buy_date, expire_date, remark, last_modified_by
                    ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (instance_id, sku_id, row["space_id"], row["location"], row["count"],
                     row["remaining_pct"], row["buy_date"], row["expire_date"], row["remark"], "system"),
                )

        # 种子空间节点
        if sku_table_exists and conn.execute("SELECT COUNT(*) FROM spatial_nodes").fetchone()[0] == 0:
            seed_spatial_nodes(conn)
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
    """Insert or update an item. Writes to both old `items` table (backward compat)
    and new `skus` + `item_instances` tables."""
    item = normalize_item(item)

    # === Write to old items table (backward compat) ===
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

    # === Write to new skus + item_instances tables ===
    get_or_create_sku(conn, item.title, category=item.category, unit=item.unit,
                      remind_days_before=item.remindDaysBefore, tags=item.tags,
                      icon=item.icon)
    sku_row = conn.execute("SELECT sku_id FROM skus WHERE title = ?", (item.title,)).fetchone()
    sku_id = sku_row["sku_id"] if sku_row else f"sku-{uuid4().hex[:12]}"

    instance_id = item.id or item.instanceId or f"inst-{uuid4().hex[:12]}"
    conn.execute(
        """INSERT INTO item_instances(
            instance_id, sku_id, space_id, location, quantity, remaining_pct,
            buy_date, expire_date, is_opened, opened_date, pao_days,
            final_expiry_date, remark, belongs_to_slot_id, last_modified_by
        ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(instance_id) DO UPDATE SET
            sku_id=excluded.sku_id,
            space_id=excluded.space_id,
            location=excluded.location,
            quantity=excluded.quantity,
            remaining_pct=excluded.remaining_pct,
            buy_date=excluded.buy_date,
            expire_date=excluded.expire_date,
            is_opened=excluded.is_opened,
            opened_date=excluded.opened_date,
            pao_days=excluded.pao_days,
            final_expiry_date=excluded.final_expiry_date,
            remark=excluded.remark,
            belongs_to_slot_id=excluded.belongs_to_slot_id,
            last_modified_by=excluded.last_modified_by,
            updated_at=CURRENT_TIMESTAMP""",
        (
            instance_id, sku_id,
            item.spaceId, item.location, item.count,
            item.remainingPct, item.buyDate, item.expireDate,
            1 if item.isOpened else 0, item.openedDate, item.paoDays,
            item.finalExpiryDate or item.expireDate, item.remark, item.belongsToSlotId,
            item.last_modified_by if hasattr(item, 'last_modified_by') else "system",
        ),
    )

    return item


def delete_item(conn: sqlite3.Connection, item_id: str) -> bool:
    """Delete an item by ID from both old and new tables."""
    cur = conn.execute("DELETE FROM items WHERE id = ?", (item_id,))
    conn.execute("DELETE FROM item_instances WHERE instance_id = ?", (item_id,))
    return cur.rowcount > 0


def delete_items_batch(conn: sqlite3.Connection, item_ids: list[str]) -> int:
    """Delete multiple items by ID. Returns total count of deleted rows."""
    total = 0
    for item_id in item_ids:
        cur = conn.execute("DELETE FROM items WHERE id = ?", (item_id,))
        conn.execute("DELETE FROM item_instances WHERE instance_id = ?", (item_id,))
        total += cur.rowcount
    return total


# ====================================================================
# SKU data access
# ====================================================================


def upsert_sku(conn: sqlite3.Connection, sku: SKU) -> SKU:
    """Insert or update a SKU record."""
    if not sku.sku_id:
        sku.sku_id = f"sku-{uuid4().hex[:12]}"
    conn.execute(
        """INSERT INTO skus(sku_id, title, category, unit, remind_days_before, tags, icon)
           VALUES(?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(sku_id) DO UPDATE SET
               title=excluded.title,
               category=excluded.category,
               unit=excluded.unit,
               remind_days_before=excluded.remind_days_before,
               tags=excluded.tags,
               icon=excluded.icon,
               updated_at=CURRENT_TIMESTAMP""",
        (sku.sku_id, sku.title, sku.category, sku.unit, sku.remind_days_before,
         json.dumps(sku.tags, ensure_ascii=False) if sku.tags else None, sku.icon),
    )
    return sku


def get_or_create_sku(conn: sqlite3.Connection, title: str, **defaults) -> SKU:
    """Find a SKU by title, or create one with optional defaults."""
    row = conn.execute("SELECT * FROM skus WHERE title = ?", (title,)).fetchone()
    if row:
        return _row_to_sku(row)
    sku = SKU(title=title, **defaults)
    return upsert_sku(conn, sku)


def _row_to_sku(row: sqlite3.Row) -> SKU:
    return SKU(
        sku_id=row["sku_id"],
        title=row["title"],
        category=row["category"],
        unit=row["unit"],
        remind_days_before=row["remind_days_before"],
        tags=json.loads(row["tags"]) if row["tags"] else [],
        icon=row["icon"],
        created_at=row["created_at"] or "",
        updated_at=row["updated_at"] or "",
    )


def list_skus(conn: sqlite3.Connection) -> list[SKU]:
    rows = conn.execute("SELECT * FROM skus ORDER BY title").fetchall()
    return [_row_to_sku(row) for row in rows]


# ====================================================================
# ItemInstance data access
# ====================================================================


def upsert_instance(conn: sqlite3.Connection, instance: ItemInstance) -> ItemInstance:
    """Insert or update an item instance."""
    if not instance.instance_id:
        instance.instance_id = f"inst-{uuid4().hex[:12]}"
    if instance.expire_date or instance.opened_date:
        instance.final_expiry_date = compute_final_expiry(instance)
    conn.execute(
        """INSERT INTO item_instances(
            instance_id, sku_id, space_id, location, quantity, remaining_pct,
            buy_date, expire_date, is_opened, opened_date, pao_days,
            final_expiry_date, remark, belongs_to_slot_id, last_modified_by
        ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(instance_id) DO UPDATE SET
            sku_id=excluded.sku_id,
            space_id=excluded.space_id,
            location=excluded.location,
            quantity=excluded.quantity,
            remaining_pct=excluded.remaining_pct,
            buy_date=excluded.buy_date,
            expire_date=excluded.expire_date,
            is_opened=excluded.is_opened,
            opened_date=excluded.opened_date,
            pao_days=excluded.pao_days,
            final_expiry_date=excluded.final_expiry_date,
            remark=excluded.remark,
            belongs_to_slot_id=excluded.belongs_to_slot_id,
            last_modified_by=excluded.last_modified_by,
            updated_at=CURRENT_TIMESTAMP""",
        (
            instance.instance_id, instance.sku_id,
            instance.space_id, instance.location, instance.quantity,
            instance.remaining_pct, instance.buy_date, instance.expire_date,
            1 if instance.is_opened else 0, instance.opened_date, instance.pao_days,
            instance.final_expiry_date, instance.remark, instance.belongs_to_slot_id,
            instance.last_modified_by,
        ),
    )
    return instance


def _row_to_instance(row: sqlite3.Row) -> ItemInstance:
    return ItemInstance(
        instance_id=row["instance_id"],
        sku_id=row["sku_id"],
        space_id=row["space_id"],
        location=row["location"],
        quantity=row["quantity"],
        remaining_pct=row["remaining_pct"],
        buy_date=row["buy_date"],
        expire_date=row["expire_date"],
        is_opened=bool(row["is_opened"]),
        opened_date=row["opened_date"],
        pao_days=row["pao_days"],
        final_expiry_date=row["final_expiry_date"],
        remark=row["remark"],
        belongs_to_slot_id=row["belongs_to_slot_id"],
        last_modified_by=row["last_modified_by"],
        created_at=row["created_at"] or "",
        updated_at=row["updated_at"] or "",
    )


def list_instances(conn: sqlite3.Connection) -> list[ItemInstance]:
    rows = conn.execute("SELECT * FROM item_instances ORDER BY created_at DESC, instance_id DESC").fetchall()
    return [_row_to_instance(row) for row in rows]


def find_instances_by_sku(conn: sqlite3.Connection, sku_id: str) -> list[ItemInstance]:
    rows = conn.execute(
        "SELECT * FROM item_instances WHERE sku_id = ? ORDER BY final_expiry_date ASC, buy_date ASC",
        (sku_id,),
    ).fetchall()
    return [_row_to_instance(row) for row in rows]


def find_instances_by_slot(conn: sqlite3.Connection, slot_id: str) -> list[ItemInstance]:
    rows = conn.execute(
        "SELECT * FROM item_instances WHERE belongs_to_slot_id = ? ORDER BY final_expiry_date ASC",
        (slot_id,),
    ).fetchall()
    return [_row_to_instance(row) for row in rows]


def delete_instance(conn: sqlite3.Connection, instance_id: str) -> bool:
    cur = conn.execute("DELETE FROM item_instances WHERE instance_id = ?", (instance_id,))
    return cur.rowcount > 0


def compute_final_expiry(instance: ItemInstance) -> str | None:
    """Compute final_expiry_date = min(expire_date, opened_date + pao_days)."""
    from datetime import datetime
    candidates: list[date] = []
    if instance.expire_date:
        try:
            candidates.append(datetime.strptime(instance.expire_date, "%Y-%m-%d").date())
        except (ValueError, TypeError):
            pass
    if instance.opened_date and instance.pao_days > 0:
        try:
            opened = datetime.strptime(instance.opened_date, "%Y-%m-%d").date()
            candidates.append(opened + timedelta(days=instance.pao_days))
        except (ValueError, TypeError):
            pass
    if not candidates:
        return instance.expire_date
    return min(candidates).isoformat()


# ====================================================================
# Joined view: SKU + Instance → flattened Item
# ====================================================================


def join_all_items(conn: sqlite3.Connection) -> list[Item]:
    """JOIN skus + item_instances → flat Item list (replaces list_items as primary read path)."""
    rows = conn.execute(
        """SELECT sku.sku_id, sku.title, sku.category, sku.unit,
                  sku.remind_days_before, sku.tags as sku_tags, sku.icon,
                  inst.instance_id, inst.space_id, inst.location,
                  inst.quantity, inst.remaining_pct, inst.buy_date,
                  inst.expire_date, inst.is_opened, inst.opened_date,
                  inst.pao_days, inst.final_expiry_date, inst.remark,
                  inst.belongs_to_slot_id, inst.last_modified_by
           FROM item_instances inst
           JOIN skus sku ON inst.sku_id = sku.sku_id
           ORDER BY inst.created_at DESC, inst.instance_id DESC""",
    ).fetchall()
    return [_join_row_to_item(row) for row in rows]


def _join_row_to_item(row: sqlite3.Row) -> Item:
    """Convert a joined row into a flat Item model."""
    from app.services.parser import guess_category, guess_icon
    quantity = row["quantity"]
    remaining_pct = row["remaining_pct"]
    tag = "告急" if remaining_pct < 20 else "较低" if remaining_pct < 50 else "充足"
    title = row["title"]
    # space_id → space_name mapping
    space_id = row["space_id"]
    space_name = _space_id_to_name(space_id)

    return Item(
        id=row["instance_id"],
        title=title,
        category=row["category"] or guess_category(title),
        spaceId=space_id,
        spaceName=space_name,
        location=row["location"],
        remainingPct=remaining_pct,
        buyDate=row["buy_date"],
        expireDate=row["expire_date"],
        tag=tag,
        count=quantity,
        unit=row["unit"],
        remindDaysBefore=row["remind_days_before"],
        tags=json.loads(row["sku_tags"]) if row["sku_tags"] else [],
        icon=row["icon"] or guess_icon(title, space_name),
        isOpened=bool(row["is_opened"]),
        openedDate=row["opened_date"],
        paoDays=row["pao_days"],
        finalExpiryDate=row["final_expiry_date"],
        remark=row["remark"],
        belongsToSlotId=row["belongs_to_slot_id"],
        skuId=row["sku_id"],
        instanceId=row["instance_id"],
    )


_SPACE_NAME_MAP = {
    "kitchen": "主厨房",
    "storage": "储藏间",
    "garage": "车库工具",
}


def _space_id_to_name(space_id: str) -> str:
    return _SPACE_NAME_MAP.get(space_id, space_id)


# ====================================================================
# SpatialNode data access
# ====================================================================


def create_spatial_node(conn: sqlite3.Connection, node: SpatialNode) -> SpatialNode:
    """Insert a spatial node."""
    if not node.node_id:
        node.node_id = f"sn-{uuid4().hex[:12]}"
    conn.execute(
        """INSERT INTO spatial_nodes(node_id, node_type, parent_id, name, aliases)
           VALUES(?, ?, ?, ?, ?)
           ON CONFLICT(node_id) DO UPDATE SET
               node_type=excluded.node_type,
               parent_id=excluded.parent_id,
               name=excluded.name,
               aliases=excluded.aliases""",
        (node.node_id, node.node_type, node.parent_id, node.name,
         json.dumps(node.aliases, ensure_ascii=False) if node.aliases else None),
    )
    return node


def _row_to_spatial_node(row: sqlite3.Row) -> SpatialNode:
    return SpatialNode(
        node_id=row["node_id"],
        node_type=row["node_type"],
        parent_id=row["parent_id"],
        name=row["name"],
        aliases=json.loads(row["aliases"]) if row["aliases"] else [],
        created_at=row["created_at"] or "",
    )


def find_node_by_alias(conn: sqlite3.Connection, alias: str) -> SpatialNode | None:
    """Find a spatial node by exact alias match (case-insensitive)."""
    all_nodes = conn.execute("SELECT * FROM spatial_nodes").fetchall()
    for row in all_nodes:
        if row["aliases"]:
            aliases = json.loads(row["aliases"])
            if any(alias.lower() == a.lower() for a in aliases):
                return _row_to_spatial_node(row)
        if alias.lower() == row["name"].lower():
            return _row_to_spatial_node(row)
    return None


def find_nodes_by_name_fragment(conn: sqlite3.Connection, fragment: str) -> list[SpatialNode]:
    """Find nodes where name or aliases contain the given fragment."""
    all_nodes = conn.execute("SELECT * FROM spatial_nodes").fetchall()
    results = []
    for row in all_nodes:
        if fragment.lower() in row["name"].lower():
            results.append(_row_to_spatial_node(row))
            continue
        if row["aliases"]:
            aliases = json.loads(row["aliases"])
            if any(fragment.lower() in a.lower() for a in aliases):
                results.append(_row_to_spatial_node(row))
    return results


def get_child_node_ids(conn: sqlite3.Connection, node_id: str) -> list[str]:
    """Get all descendant Slot node IDs for a given parent."""
    all_nodes = conn.execute("SELECT node_id, parent_id, node_type FROM spatial_nodes").fetchall()
    parent_map: dict[str, list[dict]] = {}
    for row in all_nodes:
        pid = row["parent_id"] or ""
        if pid not in parent_map:
            parent_map[pid] = []
        parent_map[pid].append({"id": row["node_id"], "type": row["node_type"]})

    result: list[str] = []
    stack = [node_id]
    while stack:
        current = stack.pop()
        for child in parent_map.get(current, []):
            if child["type"] == "Slot":
                result.append(child["id"])
            stack.append(child["id"])
    return result


def seed_spatial_nodes(conn: sqlite3.Connection) -> None:
    """Create default SpatialNode hierarchy from existing spaces."""
    from app.models.schemas import NodeType

    # Zone: kitchen
    kitchen_zone = SpatialNode(node_id="zone-kitchen", node_type="Zone", name="主厨房",
                                aliases=["厨房", "灶间", "厨房区域"])
    create_spatial_node(conn, kitchen_zone)
    _add_kitchen_nodes(conn, "zone-kitchen")

    # Zone: storage
    storage_zone = SpatialNode(node_id="zone-storage", node_type="Zone", name="储藏间",
                                aliases=["储藏室", "储物间", "杂物间"])
    create_spatial_node(conn, storage_zone)
    _add_storage_nodes(conn, "zone-storage")

    # Zone: garage
    garage_zone = SpatialNode(node_id="zone-garage", node_type="Zone", name="车库工具",
                               aliases=["车库", "工具间", "地下室"])
    create_spatial_node(conn, garage_zone)
    _add_garage_nodes(conn, "zone-garage")


def _add_kitchen_nodes(conn: sqlite3.Connection, parent_id: str) -> None:
    fridge = SpatialNode(node_id="fixture-fridge", node_type="Fixture", parent_id=parent_id,
                          name="冰箱", aliases=["冷藏", "冷冻", "冰柜", "雪柜"])
    create_spatial_node(conn, fridge)
    create_spatial_node(conn, SpatialNode(node_id="slot-fridge-top", node_type="Slot", parent_id=fridge.node_id,
                                           name="冰箱上层", aliases=["冰箱上层", "冷冻层", "上格"]))
    create_spatial_node(conn, SpatialNode(node_id="slot-fridge-mid", node_type="Slot", parent_id=fridge.node_id,
                                           name="冰箱中层", aliases=["冰箱中层", "冷藏层", "中格"]))
    create_spatial_node(conn, SpatialNode(node_id="slot-fridge-bottom", node_type="Slot", parent_id=fridge.node_id,
                                           name="冰箱下层", aliases=["冰箱下层", "保鲜层", "下格", "下面", "底下", "下方"]))

    cabinet = SpatialNode(node_id="fixture-cabinet", node_type="Fixture", parent_id=parent_id,
                           name="橱柜", aliases=["柜子", "储物柜", "吊柜"])
    create_spatial_node(conn, cabinet)
    create_spatial_node(conn, SpatialNode(node_id="slot-cabinet-top", node_type="Slot", parent_id=cabinet.node_id,
                                           name="橱柜上层", aliases=["橱柜上层", "吊柜上层", "上面"]))
    create_spatial_node(conn, SpatialNode(node_id="slot-cabinet-bottom", node_type="Slot", parent_id=cabinet.node_id,
                                           name="橱柜下层", aliases=["橱柜下层", "下面的抽屉", "下层", "抽屉"]))


def _add_storage_nodes(conn: sqlite3.Connection, parent_id: str) -> None:
    shelf = SpatialNode(node_id="fixture-storage-shelf", node_type="Fixture", parent_id=parent_id,
                         name="储物搁板", aliases=["搁板", "架子", "货架"])
    create_spatial_node(conn, shelf)
    create_spatial_node(conn, SpatialNode(node_id="slot-storage-a", node_type="Slot", parent_id=shelf.node_id,
                                           name="储物间 A 区", aliases=["A区", "A搁板", "左边"]))
    create_spatial_node(conn, SpatialNode(node_id="slot-storage-b", node_type="Slot", parent_id=shelf.node_id,
                                           name="储物间 B 区", aliases=["B区", "B搁板", "药品箱", "右边"]))


def _add_garage_nodes(conn: sqlite3.Connection, parent_id: str) -> None:
    rack = SpatialNode(node_id="fixture-garage-rack", node_type="Fixture", parent_id=parent_id,
                        name="车库货架", aliases=["工具架", "货架", "置物架"])
    create_spatial_node(conn, rack)
    create_spatial_node(conn, SpatialNode(node_id="slot-garage-a4", node_type="Slot", parent_id=rack.node_id,
                                           name="车库 A4 搁板", aliases=["A4", "A4搁板"]))
    create_spatial_node(conn, SpatialNode(node_id="slot-garage-b3", node_type="Slot", parent_id=rack.node_id,
                                           name="车库 B3 搁板", aliases=["B3", "B3搁板"]))


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
    items = join_all_items(conn)
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


def get_conversation_state(conn: sqlite3.Connection, user_id: str = "default_user") -> dict:
    """Load the persistent conversation state."""
    row = conn.execute(
        "SELECT interaction_mode, pending_item_selection, pending_operation, last_added_item, current_context_item FROM conversation_states WHERE user_id = ?",
        (user_id,),
    ).fetchone()
    return {
        "interaction_mode": row["interaction_mode"] if row else "normal",
        "pending_item_selection": json.loads(row["pending_item_selection"]) if row and row["pending_item_selection"] else None,
        "pending_operation": json.loads(row["pending_operation"]) if row and row["pending_operation"] else None,
        "last_added_item": json.loads(row["last_added_item"]) if row and row["last_added_item"] else None,
        "current_context_item": json.loads(row["current_context_item"]) if row and row["current_context_item"] else None,
    }


def save_conversation_state(
    conn: sqlite3.Connection,
    interaction_mode: str = "normal",
    pending_item_selection: list | None = None,
    pending_operation: dict | None = None,
    last_added_item: dict | None = None,
    current_context_item: dict | None = None,
    user_id: str = "default_user",
) -> None:
    """Save the persistent conversation state."""
    conn.execute(
        """INSERT INTO conversation_states(user_id, interaction_mode, pending_item_selection, pending_operation, last_added_item, current_context_item)
           VALUES(?, ?, ?, ?, ?, ?)
           ON CONFLICT(user_id) DO UPDATE SET
               interaction_mode=excluded.interaction_mode,
               pending_item_selection=excluded.pending_item_selection,
               pending_operation=excluded.pending_operation,
               last_added_item=excluded.last_added_item,
               current_context_item=excluded.current_context_item""",
        (
            user_id,
            interaction_mode,
            json.dumps(pending_item_selection, ensure_ascii=False) if pending_item_selection else None,
            json.dumps(pending_operation, ensure_ascii=False) if pending_operation else None,
            json.dumps(last_added_item, ensure_ascii=False) if last_added_item else None,
            json.dumps(current_context_item, ensure_ascii=False) if current_context_item else None,
        ),
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


# ====================================================================
# Snapshot persistence (Phase 1 - JSON serialization)
# ====================================================================


def save_snapshot(
    conn: sqlite3.Connection,
    snapshot_id: str,
    session_id: str,
    graph_version: int,
    snapshot_data: dict,
    ttl_minutes: int = 60,
) -> None:
    """Persist a conversation snapshot to the database.

    Args:
        conn: Database connection
        snapshot_id: Unique snapshot identifier
        session_id: Session identifier
        graph_version: Graph version at time of snapshot
        snapshot_data: Snapshot state data (must be JSON-serializable)
        ttl_minutes: Time-to-live in minutes
    """
    from datetime import datetime, timedelta
    expires_at = (datetime.now() + timedelta(minutes=ttl_minutes)).isoformat()
    now = datetime.now().isoformat()

    conn.execute(
        """INSERT INTO conversation_snapshots(
            snapshot_id, session_id, graph_version, execution_mode, is_suspended,
            suspension_reason, action_queue_snapshot, workspace_snapshot,
            loop_depth_snapshot, missing_parameters, blocked_action_id,
            user_choice_options, raw_user_input, normalized_request,
            memory_state, created_at, expires_at
        ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(snapshot_id) DO UPDATE SET
            graph_version=excluded.graph_version,
            is_suspended=excluded.is_suspended,
            suspension_reason=excluded.suspension_reason,
            action_queue_snapshot=excluded.action_queue_snapshot,
            workspace_snapshot=excluded.workspace_snapshot,
            loop_depth_snapshot=excluded.loop_depth_snapshot,
            missing_parameters=excluded.missing_parameters,
            blocked_action_id=excluded.blocked_action_id,
            user_choice_options=excluded.user_choice_options,
            raw_user_input=excluded.raw_user_input,
            normalized_request=excluded.normalized_request,
            memory_state=excluded.memory_state,
            expires_at=excluded.expires_at""",
        (
            snapshot_id,
            session_id,
            graph_version,
            snapshot_data.get("execution_mode", "SUSPENDED"),
            1 if snapshot_data.get("is_suspended", True) else 0,
            snapshot_data.get("suspension_reason"),
            json.dumps(snapshot_data.get("action_queue_snapshot", []), ensure_ascii=False, default=str),
            json.dumps(snapshot_data.get("workspace_snapshot", {}), ensure_ascii=False, default=str),
            snapshot_data.get("loop_depth_snapshot", 0),
            json.dumps(snapshot_data.get("missing_parameters", []), ensure_ascii=False),
            snapshot_data.get("blocked_action_id"),
            json.dumps(snapshot_data.get("user_choice_options", []), ensure_ascii=False),
            snapshot_data.get("raw_user_input", ""),
            json.dumps(snapshot_data.get("normalized_request", {}), ensure_ascii=False, default=str),
            json.dumps(snapshot_data.get("memory_state", {}), ensure_ascii=False, default=str),
            now,
            expires_at,
        ),
    )


def get_active_snapshot(conn: sqlite3.Connection, session_id: str) -> dict | None:
    """Get the most recent active (non-expired) snapshot for a session.

    Args:
        conn: Database connection
        session_id: Session identifier

    Returns:
        Snapshot dict if found and not expired, None otherwise
    """
    from datetime import datetime
    now = datetime.now().isoformat()

    row = conn.execute(
        """SELECT * FROM conversation_snapshots
           WHERE session_id = ? AND is_suspended = 1 AND expires_at > ?
           ORDER BY graph_version DESC LIMIT 1""",
        (session_id, now),
    ).fetchone()

    if not row:
        return None

    return {
        "snapshot_id": row["snapshot_id"],
        "session_id": row["session_id"],
        "graph_version": row["graph_version"],
        "execution_mode": row["execution_mode"],
        "is_suspended": bool(row["is_suspended"]),
        "suspension_reason": row["suspension_reason"],
        "action_queue_snapshot": json.loads(row["action_queue_snapshot"]) if row["action_queue_snapshot"] else [],
        "workspace_snapshot": json.loads(row["workspace_snapshot"]) if row["workspace_snapshot"] else {},
        "loop_depth_snapshot": row["loop_depth_snapshot"],
        "missing_parameters": json.loads(row["missing_parameters"]) if row["missing_parameters"] else [],
        "blocked_action_id": row["blocked_action_id"],
        "user_choice_options": json.loads(row["user_choice_options"]) if row["user_choice_options"] else [],
        "raw_user_input": row["raw_user_input"] or "",
        "normalized_request": json.loads(row["normalized_request"]) if row["normalized_request"] else {},
        "memory_state": json.loads(row["memory_state"]) if row["memory_state"] else {},
        "created_at": row["created_at"] or "",
        "expires_at": row["expires_at"] or "",
    }


def delete_snapshot(conn: sqlite3.Connection, snapshot_id: str) -> bool:
    """Delete a snapshot by ID.

    Returns:
        True if a row was deleted, False otherwise
    """
    cur = conn.execute("DELETE FROM conversation_snapshots WHERE snapshot_id = ?", (snapshot_id,))
    return cur.rowcount > 0


def cleanup_expired_snapshots(conn: sqlite3.Connection) -> int:
    """Delete all expired snapshots.

    Returns:
        Number of deleted rows
    """
    from datetime import datetime
    now = datetime.now().isoformat()
    cur = conn.execute("DELETE FROM conversation_snapshots WHERE expires_at < ?", (now,))
    return cur.rowcount


# ====================================================================
# Checkpoint persistence (Phase 6 - REPLAY support)
# ====================================================================


def save_checkpoint(
    conn: sqlite3.Connection,
    checkpoint_id: str,
    session_id: str,
    graph_version: int,
    node_name: str,
    state_snapshot: dict,
) -> None:
    """Persist an execution checkpoint.

    Args:
        conn: Database connection
        checkpoint_id: Unique checkpoint identifier
        session_id: Session identifier
        graph_version: Graph version at checkpoint
        node_name: Name of the node that created the checkpoint
        state_snapshot: JSON-serializable state snapshot
    """
    conn.execute(
        """INSERT OR REPLACE INTO checkpoints(
            id, session_id, graph_version, node_name, state_snapshot
        ) VALUES(?, ?, ?, ?, ?)""",
        (
            checkpoint_id,
            session_id,
            graph_version,
            node_name,
            json.dumps(state_snapshot, ensure_ascii=False, default=str),
        ),
    )


def get_checkpoint(conn: sqlite3.Connection, checkpoint_id: str) -> dict | None:
    """Retrieve a checkpoint by ID.

    Returns:
        Checkpoint dict or None if not found
    """
    cur = conn.execute(
        "SELECT * FROM checkpoints WHERE id = ?", (checkpoint_id,)
    )
    row = cur.fetchone()
    if row is None:
        return None
    return {
        "id": row[0],
        "session_id": row[1],
        "graph_version": row[2],
        "node_name": row[3],
        "state_snapshot": json.loads(row[4]),
        "created_at": row[5],
    }


def list_checkpoints(
    conn: sqlite3.Connection,
    session_id: str,
    limit: int = 20,
) -> list[dict]:
    """List checkpoints for a session, newest first.

    Returns:
        List of checkpoint dicts
    """
    cur = conn.execute(
        """SELECT * FROM checkpoints
         WHERE session_id = ?
         ORDER BY graph_version DESC
         LIMIT ?""",
        (session_id, limit),
    )
    results = []
    for row in cur.fetchall():
        results.append({
            "id": row[0],
            "session_id": row[1],
            "graph_version": row[2],
            "node_name": row[3],
            "state_snapshot": json.loads(row[4]),
            "created_at": row[5],
        })
    return results


def delete_checkpoint(conn: sqlite3.Connection, checkpoint_id: str) -> bool:
    """Delete a checkpoint.

    Returns:
        True if a row was deleted, False otherwise
    """
    cur = conn.execute("DELETE FROM checkpoints WHERE id = ?", (checkpoint_id,))
    return cur.rowcount > 0


def cleanup_expired_checkpoints(conn: sqlite3.Connection, ttl_minutes: int = 1440) -> int:
    """Delete checkpoints older than ttl_minutes.

    Returns:
        Number of deleted rows
    """
    from datetime import datetime, timedelta
    cutoff = (datetime.now() - timedelta(minutes=ttl_minutes)).isoformat()
    cur = conn.execute("DELETE FROM checkpoints WHERE created_at < ?", (cutoff,))
    return cur.rowcount

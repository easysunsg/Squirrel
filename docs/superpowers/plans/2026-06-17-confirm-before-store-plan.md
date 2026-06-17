# 树洞聊斋「先确认再入库」多轮对话实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 Squirrel 聊天助手增加"先确认再入库"的多轮对话机制，用户输入的物品解析后展示可编辑卡片，确认后才写入数据库。

**Architecture:** 后端利用 LangGraph 的 `add_node` 设置 `needsConfirmation`，路由层将解析结果存入 `pending_confirmation` 表（不入库），前端展示可编辑卡片，用户确认后调 `/api/chat/confirm` 批量入库。

**Tech Stack:** Python 3.12 FastAPI + SQLite + LangGraph / React 19 + TypeScript + Tailwind CSS

## Global Constraints

- 后端新增 `pending_confirmation` 表：`id TEXT PK`, `items TEXT(JSON)`, `created_at TEXT(ISO)`
- Pending 记录的 TTL 为 30 分钟，惰性清理（查询时过滤过期的）
- 前端 `ChatMessage.itemSuggestion` 扩展为 `{ pendingId: string, items: PendingItem[] }`
- 新增 `ConfirmRequest` Pydantic 模型：`pendingId: str`, `items: list[Item]`
- 新增 `POST /api/chat/confirm` 端点：验证 pending → upsert → 清理 → 返回
- 现有 `test_chat_add_persists_item` 测试需要更新为两轮流程
- `execute_chat_operations` 中 `type == "add"` 跳过 `upsert_item`，改为通过 `chat_result` 返回

---

### Task 1: 后端数据层 — pending_confirmation 表 + CRUD

**Files:**
- Modify: `server/app/db/sqlite.py:111-189`
- Test: `server/tests/test_graph.py` (新增测试函数)

**Interfaces:**
- Consumes: `app.models.schemas.Item` (已有)
- Produces:
  - `create_pending_confirmation(conn, items: list[Item]) -> str` — 返回 pendingId
  - `get_pending_confirmation(conn, pending_id: str) -> list[Item] | None`
  - `delete_pending_confirmation(conn, pending_id: str) -> bool`
  - `cleanup_expired_pending(conn, ttl_minutes: int = 30) -> int`

- [ ] **Step 1: 在 `init_db()` 中添加 `pending_confirmation` 表创建**

在 `server/app/db/sqlite.py` 的 `init_db()` 函数中，`conn.executescript(...)` 内末尾追加：

```python
CREATE TABLE IF NOT EXISTS pending_confirmation (
    id TEXT PRIMARY KEY,
    items TEXT NOT NULL,
    created_at TEXT NOT NULL
);
```

- [ ] **Step 2: 添加 4 个 CRUD 函数**

在 `server/app/db/sqlite.py` 末尾，`replace_state()` 函数之后新增：

```python
def create_pending_confirmation(conn: sqlite3.Connection, items: list[Item]) -> str:
    pending_id = f"pending-{uuid4().hex[:12]}"
    conn.execute(
        "INSERT INTO pending_confirmation(id, items, created_at) VALUES(?, ?, ?)",
        (pending_id, json.dumps([item.model_dump() for item in items], ensure_ascii=False), today_iso()),
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


def cleanup_expired_pending(conn: sqlite3.Connection, ttl_minutes: int = 30) -> int:
    from datetime import datetime, timedelta
    cutoff = (datetime.now() - timedelta(minutes=ttl_minutes)).isoformat()
    cur = conn.execute("DELETE FROM pending_confirmation WHERE created_at < ?", (cutoff,))
    return cur.rowcount
```

- [ ] **Step 3: 写测试**

在 `server/tests/test_graph.py` 末尾追加：

```python
from app.db.sqlite import connect, create_pending_confirmation, get_pending_confirmation, delete_pending_confirmation, cleanup_expired_pending
from app.models.schemas import Item


def test_create_and_get_pending():
    items = [Item(title="青椒", count=7, unit="个")]
    with connect() as conn:
        pending_id = create_pending_confirmation(conn, items)
        got = get_pending_confirmation(conn, pending_id)
    assert got is not None
    assert len(got) == 1
    assert got[0].title == "青椒"
    assert got[0].count == 7


def test_get_nonexistent_pending():
    with connect() as conn:
        got = get_pending_confirmation(conn, "pending-nonexistent")
    assert got is None


def test_delete_pending():
    items = [Item(title="牙膏", count=2)]
    with connect() as conn:
        pending_id = create_pending_confirmation(conn, items)
        deleted = delete_pending_confirmation(conn, pending_id)
    assert deleted is True


def test_cleanup_expired_pending():
    with connect() as conn:
        pending_id = f"pending-{uuid4().hex[:12]}"
        conn.execute(
            "INSERT INTO pending_confirmation(id, items, created_at) VALUES(?, ?, ?)",
            (pending_id, "[]", "2020-01-01"),
        )
        cleaned = cleanup_expired_pending(conn, ttl_minutes=30)
    assert cleaned >= 1
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd server && uv run pytest tests/test_graph.py::test_create_and_get_pending tests/test_graph.py::test_get_nonexistent_pending tests/test_graph.py::test_delete_pending tests/test_graph.py::test_cleanup_expired_pending -v`

Expected: 4 PASS

- [ ] **Step 5: Commit**

```bash
git add server/app/db/sqlite.py server/tests/test_graph.py
git commit -m "feat(db): add pending_confirmation table and CRUD functions"
```

---

### Task 2: 后端模型 — ChatResult.pendingId + ConfirmRequest

**Files:**
- Modify: `server/app/models/schemas.py:65-79`

**Interfaces:**
- Consumes: 无（纯数据模型）
- Produces:
  - `ChatResult.pendingId: str | None = None` — 新增字段
  - `class ConfirmRequest(BaseModel)` — `pendingId: str`, `items: list[Item]`

- [ ] **Step 1: ChatResult 增加 `pendingId` 字段**

在 `server/app/models/schemas.py` 中：

```python
class ChatResult(BaseModel):
    intent: ChatIntent = "chat"
    replyText: str = "我已经处理完这次请求。"
    operations: list[ChatOperation] = Field(default_factory=list)
    itemSuggestion: dict[str, Any] | None = None
    needsConfirmation: bool = False
    pendingId: str | None = None          # 新增
```

- [ ] **Step 2: 新增 `ConfirmRequest` 模型**

在 `ChatResult` 之后，`FrontendInventoryItem` 之前插入：

```python
class ConfirmRequest(BaseModel):
    pendingId: str
    items: list[Item]
```

- [ ] **Step 3: Commit**

```bash
git add server/app/models/schemas.py
git commit -m "feat(schemas): add pendingId to ChatResult and ConfirmRequest model"
```

---

### Task 3: 后端 Graph + Routes — 确认流程集成

**Files:**
- Modify: `server/app/services/graph.py:103-104`（add_node）
- Modify: `server/app/api/routes.py:69-113, 261-293`（execute_chat_operations + chat 端点 + 新 confirm 端点）
- Test: `server/tests/test_chat_api.py`（更新 + 新增测试）

**Interfaces:**
- Consumes: `create_pending_confirmation`, `get_pending_confirmation`, `delete_pending_confirmation`（来自 sqlite.py）
- Consumes: `ChatResult.pendingId`, `ConfirmRequest`（来自 schemas.py）
- Produces: `POST /api/chat/confirm` 端点

- [ ] **Step 1: 修改 `add_node` — 设置 needsConfirmation**

在 `server/app/services/graph.py` 中，`add_node` 函数：

```python
def add_node(state: SquirrelGraphState) -> SquirrelGraphState:
    chat_result = state["chat_result"]
    if chat_result.operations:
        item_count = len([op for op in chat_result.operations if op.type == "add" and op.item])
        if item_count > 0:
            chat_result.needsConfirmation = True
            chat_result.replyText = f"已识别出 {item_count} 件物品，请确认后再入库。"
    return {"chat_result": chat_result}
```

- [ ] **Step 2: 修改 `execute_chat_operations` — add 类型跳过入库**

在 `server/app/api/routes.py` 中：

```python
def execute_chat_operations(chat_result: ChatResult, conn, inventory: list[Item]) -> tuple[ChatResult, list[Item], list[str]]:
    # === 新增：拦截 add 操作，存 pending 不入库 ===
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
        # 仍有其他非 add 操作需要执行
        non_add_ops = [op for op in chat_result.operations if op.type != "add"]
        if not non_add_ops:
            return chat_result, [], []
        chat_result.operations = non_add_ops
    # === 原有逻辑继续处理非 add 操作 ===
    updated_items: list[Item] = []
    deleted_ids: list[str] = []

    for operation in chat_result.operations:
        # ... 保持不变（consume/remove/update 逻辑）
        # 注意：原有代码中第一个 if operation.type == "add" 的分支不再需要（已被上方拦截）
        # 如果有非 add 操作保留，它们的处理逻辑不变
```

- [ ] **Step 3: 修改 `/api/chat` 端点 — 处理确认响应**

在 `routes.py` 的 `chat` 端点中，调用 `execute_chat_operations` 后检查 `chat_result.pendingId`，若存在则跳过 `sync_outputs`：

```python
@router.post("/chat")
def chat(request: ChatRequest):
    with connect() as conn:
        history = request.chatHistory or list_messages(conn)
        latest = history[-1].text if history else ""
        inventory = list_items(conn)
        chat_result = ai_service.chat(latest, inventory)
        chat_result, updated_items, deleted_ids = execute_chat_operations(chat_result, conn, inventory)
        full_history = history.copy()
        assistant_message = Message(
            id=f"msg-ai-{len(history) + 1}",
            sender="assistant",
            text=chat_result.replyText,
            timestamp="刚刚",
            itemSuggestion=chat_result.itemSuggestion,
        )
        full_history.append(assistant_message)
        replace_messages(conn, full_history)
        state = get_state(conn)

    # === 新增：有 pending 时不执行 sync_outputs ===
    if chat_result.pendingId:
        return {
            "reply": chat_result.replyText,
            "needsConfirmation": True,
            "itemSuggestion": chat_result.itemSuggestion,
            "pendingId": chat_result.pendingId,
            "messages": full_history,
            "items": state.items,
        }

    # 原有 sync 逻辑
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
```

- [ ] **Step 4: 新增 `POST /api/chat/confirm` 端点**

在 `routes.py` 中 `chat` 端点之后：

```python
from uuid import uuid4

@router.post("/chat/confirm")
def confirm_items(request: ConfirmRequest):
    logger.info("Confirming pending items pendingId=%s count=%d", request.pendingId, len(request.items))
    with connect() as conn:
        pending = get_pending_confirmation(conn, request.pendingId)
        if not pending:
            raise HTTPException(status_code=404, detail="确认请求已过期或不存在，请重新输入。")
        
        created = [upsert_item(conn, item) for item in request.items]
        delete_pending_confirmation(conn, request.pendingId)
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
        "messages": all_messages + [confirm_message],
    }
```

- [ ] **Step 5: 更新现有测试 + 新增确认测试**

重写 `test_chat_add_persists_item` 为两轮流程，新增确认测试：

```python
def test_chat_add_returns_pending():
    """add 操作返回 pendingId 不直接入库"""
    response = client.post(
        "/api/chat",
        json={
            "messages": [
                {"id": "msg-user-1", "sender": "user", "text": "我今天买了一把油麦菜，放冰箱下层", "timestamp": "刚刚"}
            ]
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data.get("needsConfirmation") is True
    assert data.get("pendingId") is not None
    assert data["itemSuggestion"]["pendingId"] == data["pendingId"]
    assert len(data["itemSuggestion"]["items"]) >= 1

    # 验证未入库
    items = client.get("/api/items").json()["items"]
    assert not any(item["title"] == "油麦菜" for item in items)


def test_chat_add_then_confirm():
    """确认后物品才入库"""
    # 第一轮：解析
    chat_resp = client.post(
        "/api/chat",
        json={
            "messages": [
                {"id": "msg-user-1", "sender": "user", "text": "买了牛奶，放冰箱下层", "timestamp": "刚刚"}
            ]
        },
    )
    data = chat_resp.json()
    pending_id = data["pendingId"]
    pending_items = data["itemSuggestion"]["items"]
    # 修改数量再确认
    pending_items[0]["count"] = 2

    # 第二轮：确认
    confirm_resp = client.post(
        "/api/chat/confirm",
        json={"pendingId": pending_id, "items": pending_items},
    )
    assert confirm_resp.status_code == 200
    assert confirm_resp.json()["ok"] is True

    # 验证已入库
    items = client.get("/api/items").json()["items"]
    milk = next(item for item in items if item["title"] == "牛奶")
    assert milk["count"] == 2


def test_chat_confirm_expired_pending():
    """过期 pending 返回 404"""
    response = client.post(
        "/api/chat/confirm",
        json={"pendingId": "pending-nonexistent", "items": []},
    )
    assert response.status_code == 404


def test_chat_confirm_empty_items():
    """确认空列表 = 取消入库"""
    chat_resp = client.post(
        "/api/chat",
        json={
            "messages": [
                {"id": "msg-user-cancel", "sender": "user", "text": "买了鸡蛋，放冰箱", "timestamp": "刚刚"}
            ]
        },
    )
    data = chat_resp.json()
    pending_id = data["pendingId"]

    confirm_resp = client.post(
        "/api/chat/confirm",
        json={"pendingId": pending_id, "items": []},
    )
    assert confirm_resp.status_code == 200
    assert "新增 0 件" in confirm_resp.json()["messages"][-1]["text"]
```

- [ ] **Step 6: 运行测试**

Run: `cd server && uv run pytest tests/test_chat_api.py -v`

Expected: 所有测试 PASS（包括原有非 add 用例，如位置更新、删除、查询不变）

- [ ] **Step 7: 运行全部后端测试**

Run: `cd server && uv run pytest -v`

Expected: ALL PASS

- [ ] **Step 8: Commit**

```bash
git add server/app/services/graph.py server/app/api/routes.py server/tests/test_chat_api.py
git commit -m "feat(chat): add pending confirmation flow with /api/chat/confirm endpoint"
```

---

### Task 4: 前端类型 — PendingItem 接口扩展

**Files:**
- Modify: `squirrel/src/types.ts:29-43`

**Interfaces:**
- Consumes: 无
- Produces: `PendingItem` 接口、`ChatMessage.itemSuggestion` 类型扩展、`ChatApiResponse` 扩展

- [ ] **Step 1: 扩展 `ChatMessage.itemSuggestion` 类型**

```typescript
export interface ChatMessage {
  id: string;
  sender: 'user' | 'assistant';
  text: string;
  timestamp: string;
  itemSuggestion?: {
    pendingId?: string;
    items?: PendingItem[];
    matches?: Array<Record<string, unknown>>;
    [key: string]: unknown;
  };
}
```

- [ ] **Step 2: 新增 `PendingItem` 接口**

在 `InventoryItem` 接口之后：

```typescript
export interface PendingItem {
  title: string;
  count: number;
  unit: string;
  category: InventoryCategory;
  location: string;
  spaceName?: string;
  expireDate?: string;
  remark?: string;
}
```

- [ ] **Step 3: 扩展 `ChatApiResponse`**

```typescript
export interface ChatApiResponse {
  reply?: string;
  itemSuggestion?: {
    pendingId?: string;
    items?: PendingItem[];
    matches?: Array<Record<string, unknown>>;
  };
  messages?: ChatMessage[];
  items?: unknown[];
  needsConfirmation?: boolean;
  pendingId?: string;
}
```

- [ ] **Step 4: 验证 lint**

Run: `cd squirrel && npm run lint`

Expected: 无类型错误

- [ ] **Step 5: Commit**

```bash
git add squirrel/src/types.ts
git commit -m "feat(types): add PendingItem interface and extend ChatMessage/ChatApiResponse"
```

---

### Task 5: 前端组件 — PendingItemsCard.tsx

**Files:**
- Create: `squirrel/src/components/PendingItemsCard.tsx`

**Interfaces:**
- Consumes:
  - `pendingId: string`
  - `items: PendingItem[]`
  - `locations: string[]`（可用位置列表，来自用户设置）
  - `onConfirm: (pendingId: string, items: PendingItem[]) => void`
  - `onCancel: () => void`
- Produces: 渲染可编辑卡片列表、调用 onConfirm/onCancel

- [ ] **Step 1: 编写 PendingItemsCard 组件**

```tsx
import React, { useState } from "react";
import { Check, X, Plus, Minus } from "lucide-react";
import { PendingItem, InventoryCategory } from "../types";

interface PendingItemsCardProps {
  pendingId: string;
  items: PendingItem[];
  locations: string[];
  onConfirm: (pendingId: string, items: PendingItem[]) => void;
  onCancel: () => void;
}

const CATEGORY_OPTIONS: { value: InventoryCategory; label: string }[] = [
  { value: "food", label: "食材美食" },
  { value: "medicine", label: "健康药箱" },
  { value: "electronics", label: "电器外设" },
  { value: "cosmetics", label: "面容护理" },
  { value: "book", label: "林间书阁" },
  { value: "other", label: "金秋杂物" },
];

const UNIT_OPTIONS = ["个", "袋", "瓶", "盒", "包", "罐", "本", "条", "把", "颗", "斤", "箱"];

export const PendingItemsCard: React.FC<PendingItemsCardProps> = ({
  pendingId,
  items: initialItems,
  locations,
  onConfirm,
  onCancel,
}) => {
  const [items, setItems] = useState<PendingItem[]>(initialItems);

  const updateItem = (index: number, patch: Partial<PendingItem>) => {
    setItems((prev) =>
      prev.map((item, i) => (i === index ? { ...item, ...patch } : item))
    );
  };

  const removeItem = (index: number) => {
    setItems((prev) => prev.filter((_, i) => i !== index));
  };

  return (
    <div className="border-2 border-on-background rounded-2xl bg-white shadow-[2px_3px_0_0_#1b1c1c] overflow-hidden">
      <div className="px-4 py-3 border-b-2 border-on-background bg-[#fff3cd] font-display font-bold text-sm flex items-center gap-2">
        <span>🧐</span>
        <span>已识别物品，请确认后再入库</span>
      </div>

      <div className="divide-y-2 divide-on-background/10">
        {items.map((item, index) => (
          <div key={index} className="p-3 space-y-2">
            <div className="flex items-center justify-between gap-2">
              {/* 名称 */}
              <input
                type="text"
                value={item.title}
                onChange={(e) => updateItem(index, { title: e.target.value })}
                className="flex-1 font-display font-bold text-sm border-2 border-on-background/30 rounded-lg px-2 py-1 focus:border-on-background focus:outline-none"
              />
              <button
                onClick={() => removeItem(index)}
                className="p-1 rounded-lg hover:bg-red-50 text-red-500"
                title="移除该项"
              >
                <X size={16} />
              </button>
            </div>

            <div className="flex flex-wrap gap-2">
              {/* 数量 */}
              <div className="flex items-center border-2 border-on-background/30 rounded-lg overflow-hidden">
                <button
                  onClick={() => updateItem(index, { count: Math.max(0, item.count - 1) })}
                  className="p-1.5 hover:bg-surface disabled:opacity-30"
                  disabled={item.count <= 0}
                >
                  <Minus size={14} />
                </button>
                <input
                  type="number"
                  value={item.count}
                  min={0}
                  onChange={(e) => updateItem(index, { count: Math.max(0, parseInt(e.target.value) || 0) })}
                  className="w-12 text-center text-sm border-x-2 border-on-background/30 py-1 focus:outline-none"
                />
                <button
                  onClick={() => updateItem(index, { count: item.count + 1 })}
                  className="p-1.5 hover:bg-surface"
                >
                  <Plus size={14} />
                </button>
              </div>

              {/* 单位 */}
              <select
                value={item.unit}
                onChange={(e) => updateItem(index, { unit: e.target.value })}
                className="text-sm border-2 border-on-background/30 rounded-lg px-2 py-1 focus:border-on-background focus:outline-none"
              >
                {UNIT_OPTIONS.map((u) => (
                  <option key={u} value={u}>{u}</option>
                ))}
              </select>

              {/* 分类 */}
              <select
                value={item.category}
                onChange={(e) => updateItem(index, { category: e.target.value as InventoryCategory })}
                className="text-sm border-2 border-on-background/30 rounded-lg px-2 py-1 focus:border-on-background focus:outline-none"
              >
                {CATEGORY_OPTIONS.map((c) => (
                  <option key={c.value} value={c.value}>{c.label}</option>
                ))}
              </select>

              {/* 位置 */}
              <select
                value={item.location}
                onChange={(e) => updateItem(index, { location: e.target.value })}
                className="text-sm border-2 border-on-background/30 rounded-lg px-2 py-1 focus:border-on-background focus:outline-none"
              >
                {locations.map((loc) => (
                  <option key={loc} value={loc}>{loc}</option>
                ))}
              </select>
            </div>
          </div>
        ))}
      </div>

      <div className="px-4 py-3 border-t-2 border-on-background bg-surface flex justify-end gap-2">
        <button
          onClick={onCancel}
          className="px-4 py-2 border-2 border-on-background rounded-xl text-sm font-bold hover:bg-red-50"
        >
          取消
        </button>
        <button
          onClick={() => onConfirm(pendingId, items)}
          disabled={items.length === 0}
          className="px-4 py-2 bg-primary text-white border-2 border-on-background rounded-xl text-sm font-bold hover:bg-opacity-90 disabled:opacity-50 flex items-center gap-1.5"
        >
          <Check size={16} />
          确认入库 ({items.length} 件)
        </button>
      </div>
    </div>
  );
};
```

- [ ] **Step 2: 验证 lint**

Run: `cd squirrel && npm run lint`

Expected: 无类型错误

- [ ] **Step 3: Commit**

```bash
git add squirrel/src/components/PendingItemsCard.tsx
git commit -m "feat(ui): add PendingItemsCard component for editable item confirmation"
```

---

### Task 6: 前端集成 — App.tsx + ChatTab.tsx

**Files:**
- Modify: `squirrel/src/App.tsx`
- Modify: `squirrel/src/components/ChatTab.tsx`

**Interfaces:**
- Consumes: `PendingItemsCard` 组件、`PendingItem` 接口、扩展后的 `ChatApiResponse`

- [ ] **Step 1: App.tsx 新增 pendingConfirmation 状态和 handleConfirmItems**

在 `App.tsx` 顶部导入区新增 `PendingItem`：

```typescript
import { AppSettings, ChatApiResponse, ChatMessage, DrawerActionType, InventoryCategory, InventoryItem, PendingItem } from "./types";
```

在状态声明区域新增：

```typescript
const [pendingConfirmation, setPendingConfirmation] = useState<PendingConfirmation | null>(null);
```

需要定义 `PendingConfirmation` 接口，在 App.tsx 函数外或函数内：

```typescript
// 函数外部（App.tsx 顶部类型声明区域）
interface PendingConfirmation {
  pendingId: string;
  items: PendingItem[];
}
```

在 `handleSendChatMessage` 中，处理响应的部分：

```typescript
const handleSendChatMessage = async (text: string) => {
  const userMessage = createChatMessage("user", text);
  const nextMessages = [...messages, userMessage];
  setMessages(nextMessages);
  setChatError(null);
  setIsSendingMessage(true);

  try {
    const response = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        chatHistory: nextMessages,
        personality: settings.squirrelPersonality,
        habits: settings.dietaryHabits,
        locations: settings.selectedLocations,
      }),
    });

    if (!response.ok) throw new Error(`Failed to send chat message: ${response.status}`);
    const data = (await response.json()) as ChatApiResponse;

    // === 新增：待确认流程 ===
    if (data.needsConfirmation && data.itemSuggestion?.items && data.pendingId) {
      setPendingConfirmation({
        pendingId: data.pendingId,
        items: data.itemSuggestion.items.map((item: Record<string, unknown>) => ({
          title: (item.title as string) || "",
          count: (item.count as number) || 1,
          unit: (item.unit as string) || "个",
          category: (item.category as InventoryCategory) || "other",
          location: (item.location as string) || settings.selectedLocations[0] || "默认层架",
          spaceName: item.spaceName as string | undefined,
          expireDate: item.expireDate as string | undefined,
          remark: item.remark as string | undefined,
        })),
      });
      appendChatMessage(createChatMessage("assistant", data.reply || `已识别出物品，请确认后再入库。`));
      return;
    }

    // 原有逻辑
    if (Array.isArray(data.items)) {
      const serverItems = normalizeServerItems(data.items);
      saveItemsToStorage(serverItems);
    }
    if (Array.isArray(data.messages)) {
      setMessages(normalizeMessageList(data.messages));
      return;
    }
    if (data.reply) {
      appendChatMessage(createChatMessage("assistant", data.reply, data.itemSuggestion));
      return;
    }

    throw new Error("Chat response did not include messages or reply");
  } catch (error) {
    console.error("Failed to send chat message", error);
    setChatError("后端暂时不可用，已使用本地回复。");
    setMessages([...nextMessages, createFallbackReply(text, settings, items)]);
  } finally {
    setIsSendingMessage(false);
  }
};
```

新增 `handleConfirmItems` 和 `handleCancelConfirm`：

```typescript
const handleConfirmItems = async (pendingId: string, items: PendingItem[]) => {
  setIsSendingMessage(true);
  try {
    const response = await fetch("/api/chat/confirm", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        pendingId,
        items: items.map((item) => ({
          title: item.title,
          count: item.count,
          unit: item.unit,
          category: item.category,
          location: item.location,
          spaceName: item.spaceName || item.location,
          spaceId: undefined,
          remainingPct: 100,
          expireDate: item.expireDate || new Date(Date.now() + 180 * 86400000).toISOString().split("T")[0],
          remindDaysBefore: 5,
          tags: [],
          remark: item.remark || null,
          icon: "package_2",
        })),
      }),
    });

    if (!response.ok) {
      throw new Error(await response.text());
    }

    const data = await response.json();
    setPendingConfirmation(null);

    if (Array.isArray(data.items)) {
      saveItemsToStorage(normalizeServerItems(data.items));
    }
    if (Array.isArray(data.messages)) {
      setMessages(normalizeMessageList(data.messages));
    }
  } catch (error) {
    console.error("Failed to confirm items", error);
    setChatError("确认入库失败，请重试。");
    setPendingConfirmation(null);
  } finally {
    setIsSendingMessage(false);
  }
};

const handleCancelConfirm = () => {
  setPendingConfirmation(null);
  appendChatMessage(createChatMessage("assistant", "已取消入库。"));
};
```

修改 `ChatTab` props 传递：

```typescript
{activeTab === "chat" && (
  <ChatTab
    settings={settings}
    items={items}
    preinput={chatPreinput}
    onClearPreinput={() => setChatPreinput("")}
    onSaveNewItem={handleSaveItem}
    onSendMessage={handleSendChatMessage}
    onAppendLocalMessage={appendChatMessage}
    onClearChatHistory={() => { void handleClearChatHistory(); }}
    messages={messages}
    isSendingMessage={isSendingMessage}
    chatError={chatError}
    pendingConfirmation={pendingConfirmation}
    onConfirmItems={handleConfirmItems}
    onCancelConfirm={handleCancelConfirm}
    locations={settings.selectedLocations}
  />
)}
```

- [ ] **Step 2: 修改 ChatTab.tsx — 接收并渲染 PendingItemsCard**

在 `ChatTab.tsx` 的 ChatProps 接口中新增 props：

```typescript
import { PendingItemsCard } from "./PendingItemsCard";
// ... 其他导入

interface ChatProps {
  // ... 已有 props
  pendingConfirmation: { pendingId: string; items: PendingItem[] } | null;
  onConfirmItems: (pendingId: string, items: PendingItem[]) => void;
  onCancelConfirm: () => void;
  locations: string[];
}
```

函数参数中解构新增的 props：

```typescript
export const ChatTab: React.FC<ChatProps> = ({
  // ... 已有
  pendingConfirmation,
  onConfirmItems,
  onCancelConfirm,
  locations,
}) => {
```

在消息列表底部，`messagesEndRef` 之前插入确认卡片：

```typescript
{/* 待确认物品卡片 */}
{pendingConfirmation && (
  <div className="flex justify-center">
    <div className="w-full max-w-md">
      <PendingItemsCard
        pendingId={pendingConfirmation.pendingId}
        items={pendingConfirmation.items}
        locations={locations}
        onConfirm={onConfirmItems}
        onCancel={onCancelConfirm}
      />
    </div>
  </div>
)}
```

- [ ] **Step 3: 验证 lint**

Run: `cd squirrel && npm run lint`

Expected: 无类型错误

- [ ] **Step 4: Commit**

```bash
git add squirrel/src/App.tsx squirrel/src/components/ChatTab.tsx
git commit -m "feat(chat): integrate pending confirmation flow in frontend"
```

---

### Task 7: 集成测试完善

**Files:**
- Modify: `server/tests/test_chat_api.py`

- [ ] **Step 1: 添加完整的确认流程集成测试**

在 `server/tests/test_chat_api.py` 末尾：

```python
def test_multi_item_pending_confirm():
    """多物品确认流程"""
    chat_resp = client.post(
        "/api/chat",
        json={
            "messages": [
                {"id": "msg-multi", "sender": "user", "text": "七个青椒、两个牙膏、一个西瓜、五个玉米", "timestamp": "刚刚"}
            ]
        },
    )
    assert chat_resp.status_code == 200
    data = chat_resp.json()
    assert data["needsConfirmation"] is True
    assert len(data["itemSuggestion"]["items"]) == 4

    # 确认前验证无新物品入库
    items_before = client.get("/api/items").json()["items"]
    titles_before = [item["title"] for item in items_before]
    for t in ["青椒", "牙膏", "西瓜", "玉米"]:
        assert t not in titles_before

    # 确认入库（修改青椒数量为 3）
    pending_items = data["itemSuggestion"]["items"]
    pending_items[0]["count"] = 3
    confirm_resp = client.post(
        "/api/chat/confirm",
        json={"pendingId": data["pendingId"], "items": pending_items},
    )
    assert confirm_resp.status_code == 200

    # 验证已入库
    items_after = client.get("/api/items").json()["items"]
    titles_after = [item["title"] for item in items_after]
    for t in ["青椒", "牙膏", "西瓜", "玉米"]:
        assert t in titles_after
    pepper = next(item for item in items_after if item["title"] == "青椒")
    assert pepper["count"] == 3


def test_pending_does_not_affect_other_operations():
    """待确认流程不影响其他操作（如查询）"""
    response = client.post(
        "/api/chat",
        json={
            "messages": [
                {"id": "msg-query", "sender": "user", "text": "我家里还有什么蔬菜？", "timestamp": "刚刚"}
            ]
        },
    )
    assert response.status_code == 200
    assert response.json().get("needsConfirmation") is not True
```

- [ ] **Step 2: 运行测试**

Run: `cd server && uv run pytest tests/test_chat_api.py -v`

Expected: ALL PASS

- [ ] **Step 3: 运行全部后端测试**

Run: `cd server && uv run pytest -v`

Expected: ALL PASS

- [ ] **Step 4: Commit**

```bash
git add server/tests/test_chat_api.py
git commit -m "test(chat): add integration tests for pending confirmation flow"
```

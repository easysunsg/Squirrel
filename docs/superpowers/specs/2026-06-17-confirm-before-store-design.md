# 树洞聊斋「先确认再入库」多轮对话设计

## 1. 背景与问题

### 当前流程

```
用户发送 ("七个青椒🫑、两个牙膏、一个西瓜、五个玉米")
  → /api/chat
    → graph: classify_intent → add_node
      → parse_lightning_text → 解析出 4 件物品
      → execute_chat_operations → upsert_item → 直接入库
    → 返回 "已识别出 4 件物品，准备入库。"
```

**痛点**：解析结果直接入库，用户无修改/确认机会。当 LLM 或规则解析不准确时，用户必须手动去库存页编辑或删除。

### 目标

- 解析结果先展示给用户确认（聊天框内联可编辑卡片）
- 用户修改后点「确认入库」才真正落库
- 充分发挥 LangGraph 的多轮对话能力

---

## 2. 设计方案 B：LangGraph 状态图多轮确认

### 2.1 总览

将现有单轮 `classify → add → execute → save` 拆分为两轮：

```
第 1 轮 (用户输入原始文本):
  START → classify_intent → add_node → [挂起，返回 needsConfirmation=true]

第 2 轮 (用户确认/修改后发送确认):
  POST /api/chat/confirm → 检查 pending → upsert_item → 返回最终结果
```

### 2.2 新增数据层

#### `pending_confirmation` 表

```sql
CREATE TABLE pending_confirmation (
    id TEXT PRIMARY KEY,        -- 如 "pending-{uuid}"
    items TEXT NOT NULL,        -- JSON: list[Item]
    created_at TEXT NOT NULL    -- ISO 时间戳
);
```

**清理策略**：确认成功后立即删除；查询时自动过滤超过 30 分钟的记录（惰性清理）。

#### `server/app/db/sqlite.py` — 新增函数

```python
def create_pending_confirmation(conn, items: list[Item]) -> str
def get_pending_confirmation(conn, pending_id: str) -> list[Item] | None
def delete_pending_confirmation(conn, pending_id: str) -> bool
def cleanup_expired_pending(conn, ttl_minutes: int = 30) -> int
```

#### `ChatResult` 增加字段 (`server/app/models/schemas.py`)

```python
class ChatResult(BaseModel):
    intent: ChatIntent = "chat"
    replyText: str = "我已经处理完这次请求。"
    operations: list[ChatOperation] = Field(default_factory=list)
    itemSuggestion: dict[str, Any] | None = None
    needsConfirmation: bool = False
    pendingId: str | None = None                      # 新增
```

`itemSuggestion` 格式调整：

```python
# 确认场景
itemSuggestion = {
    "pendingId": "pending-xxx",
    "items": [
        {"name": "青椒", "count": 7, "unit": "个", "location": "默认层架", ...},
        {"name": "牙膏", "count": 2, "unit": "个", "location": "默认层架", ...},
    ]
}
```

#### 新增 `ConfirmRequest` (`server/app/models/schemas.py`)

```python
class ConfirmRequest(BaseModel):
    pendingId: str
    items: list[Item]
```

---

## 3. LangGraph 图结构变化

### 当前图

```
START → classify_intent → add → END
                        → consume → END
                        → ... → END
```

### 新图

```
第 1 轮 (chat):
START → classify_intent → add (解析, 存 pending, 返回 needsConfirmation=true)
                         → END
                        ├→ consume → END
                        ├→ ... → END

第 2 轮 (confirm):
POST /api/chat/confirm → 验证 pending → upsert_item → 清理 pending → 返回
(不经过 langgraph，直接操作数据库)
```

**为什么 confirm 不经过 LangGraph**：当前设计每次 `/api/chat` 独立 invoke graph，graph 是无状态的。引入有状态的 session 管理来支持多轮对话会使复杂度大幅增加。确认操作本质是纯数据操作（验证 → 写入 → 清理），独立路由更简单可靠。

**关键变化**：

1. **`add_node` 重写** — 解析物品后存入 `pending_confirmation` 表，设置 `needsConfirmation=true` 和 `pendingId`，不执行任何入库操作。graph 执行到此结束，等客户端调 `/api/chat/confirm`。
2. **新增 `save_node`** — 仅在无状态 graph 内标记作用，实际确认入库由 `/api/chat/confirm` 端点完成。`add_node` 返回后直接走 `add → END`。

---

## 4. 后端 API 变化

### `/api/chat` — 修改 (`routes.py:262`)

`execute_chat_operations` 中 `type == "add"` **跳过入库**，改为累积到 pending 列表：
`/api/chat` 内：调用 graph 后若 `chat_result.pendingId` 存在，直接返回确认响应，不执行 `sync_outputs`。

### 新增 `POST /api/chat/confirm`

```python
@router.post("/chat/confirm")
def confirm_items(request: ConfirmRequest):
    with connect() as conn:
        pending = get_pending_confirmation(conn, request.pendingId)
        if not pending:
            raise HTTPException(status_code=404, detail="确认请求已过期，请重新输入")
        created = [upsert_item(conn, item) for item in request.items]
        delete_pending_confirmation(conn, request.pendingId)

    state = sync_outputs()
    return {
        "ok": True,
        "items": state.items,
        "messages": [
            {
                "id": f"msg-confirm-{uuid4()}",
                "sender": "assistant",
                "text": f"确认入库，已新增 {len(created)} 件物品。",
                "timestamp": "刚刚",
            }
        ],
    }
```

---

## 5. 前端变化

### 5.1 数据层 (`squirrel/src/types.ts`)

```typescript
export interface ChatMessage {
  id: string;
  sender: 'user' | 'assistant';
  text: string;
  timestamp: string;
  itemSuggestion?: {
    pendingId: string;
    items: PendingItem[];
  };
}

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

### 5.2 状态管理 (`squirrel/src/App.tsx`)

新增 `pendingConfirmation` 状态，在 `handleSendChatMessage` 中判断响应是否有 `needsConfirmation`，有则设置该状态而非追加普通消息；新增 `handleConfirmItems` 函数调 `/api/chat/confirm`。

### 5.3 新增组件 `PendingItemsCard.tsx`

可编辑卡片列表，每个卡片包含可编辑字段：名称（文本）、数量（数字+加减按钮）、单位（下拉）、位置（下拉）、分类（下拉）。底部「确认入库」和「取消」按钮。

---

## 6. 完整数据流

### 第 1 轮

```
用户输入 → POST /api/chat → classify_intent → add_node
  → parse_lightning_text → 4 items
  → create_pending_confirmation → pendingId
  → 返回: { needsConfirmation: true, itemSuggestion: { pendingId, items } }

前端渲染 PendingItemsCard：4 张可编辑卡片
用户编辑后点「确认入库」
```

### 第 2 轮

```
POST /api/chat/confirm { pendingId, items }
  → 验证 pendingId → 批量 upsert_item → 清理 pending
  → 返回: { ok: true, items, messages }

前端更新库存 + 追加确认消息
```

---

## 7. 边界情况

| 场景 | 处理 |
|---|---|
| Pending 过期（>30 分钟） | confirm 返回 404，前端提示「确认已过期，请重新输入」 |
| 用户发新消息而非确认 | 新消息不带 pendingId，走正常路由；pending 仍在 TTL 内有效 |
| 确认时删除所有物品 | 允许空列表，反馈「已取消入库」 |
| 同 pendingId 重复确认 | 第二次返回 404（首次已删除） |
| 确认时后端重启 | pending 存 SQLite 不丢，重启后仍可确认 |
| 解析结果为空 | 直接返回「未识别到物品」，不走确认流程 |
| 位置不在设置中 | 确认时自动创建对应 space（沿用 upsert 逻辑） |

---

## 8. 文件改动清单

### 后端（5 个文件）

| 文件 | 改动 |
|---|---|
| `server/app/models/schemas.py` | `ChatResult` 加 `pendingId`；新增 `ConfirmRequest` |
| `server/app/db/sqlite.py` | 新增 `pending_confirmation` 表 + CRUD |
| `server/app/services/graph.py` | `add_node` 改存 pending；新增 `save_node` |
| `server/app/api/routes.py` | `execute_chat_operations` 跳过 add；新增 `/chat/confirm` |

### 前端（4 个文件）

| 文件 | 改动 |
|---|---|
| `squirrel/src/types.ts` | 扩展 `ChatMessage.itemSuggestion`；新增 `PendingItem` |
| `squirrel/src/App.tsx` | 新增 `pendingConfirmation` 状态；`handleConfirmItems` |
| `squirrel/src/components/ChatTab.tsx` | 嵌入 `PendingItemsCard` |
| `squirrel/src/components/PendingItemsCard.tsx` | **新建** 可编辑卡片组件 |

---

## 9. 实现顺序

1. 后端数据层 — `pending_confirmation` 表 + CRUD
2. 后端模型 — `ConfirmRequest` + `ChatResult.pendingId`
3. 后端 Graph 修改 — `add_node` 改存 pending，新增 `save_node`
4. 后端路由修改 — 跳过 add 入库，新增 `/api/chat/confirm`
5. 前端类型 — `PendingItem` 接口扩展
6. 前端状态 — `App.tsx` 确认流处理
7. 前端组件 — `PendingItemsCard.tsx`
8. 集成测试 — 全链路确认流程验证

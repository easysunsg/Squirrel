# 🐿️ 松鼠库存管家 — 智能家居库存管理

> 像松鼠一样精于囤积，但再也不会忘记你的"坚果"藏在哪里。

[English](./README.md) | **中文**

## 项目简介

松鼠库存管家是一款本地优先、AI 驱动的家居库存管理工具。帮你追踪家里有什么、放在哪里、什么时候过期——让每一件物品都不被浪费。

### 核心功能

- **自然语言录入** — 直接说"买了3袋螺蛳粉，放客厅箱子里"，AI 自动解析入库。
- **智能过期预警** — 三色卡片提醒：🔴 已过期、🟡 即将过期、⚪ 长期闲置。
- **位置记忆** — 再也不用翻箱倒柜找东西。
- **AI 对话助手** — 问"家里还有什么蔬菜？"或"冰箱里的菜能做什么？"
- **Markdown 同步** — 库存自动生成 `inventory.md`，可在 Obsidian、Notion 或任意编辑器中查看。
- **多端使用** — Web 界面、命令行工具、API 接口，随你选择。

## 技术栈

| 层级 | 技术 |
|------|------|
| 后端 | Python 3.12 + FastAPI |
| 数据库 | SQLite + Chroma 向量数据库（语义搜索） |
| 前端 | React 19 + Vite + Tailwind CSS |
| 命令行 | Go 1.22 + Cobra |
| 部署 | Docker + Nginx 反向代理 |

## 快速开始

### Docker Compose（推荐）

```bash
docker compose up --build
```

浏览器打开 `http://localhost:5685`。

Compose 文件会自动启动后端、构建前端，并通过 Nginx 反向代理将所有服务统一到一个端口。

### 本地开发

#### 后端

```bash
cd server
uv sync
uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

#### 前端

```bash
cd squirrel
npm install
npm run dev
```

#### 命令行工具

```bash
go run ./cli --help
go run ./cli add "3袋薯片，放厨房柜子里"
go run ./cli list --status=danger
```

## 配置说明

### 环境变量

后端环境变量（在 `server/.env` 或 Docker 中设置）：

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `SQUIRREL_DATA_DIR` | `../data` | SQLite 数据库目录 |
| `SQUIRREL_STORAGE_DIR` | `../storage` | Markdown 导出目录 |
| `AI_PROVIDER` | `mock` | AI 提供商：`openai`、`ollama`、`local`、`mock` |
| `AI_BASE_URL` | — | OpenAI 兼容 API 地址 |
| `AI_API_KEY` | — | API 密钥 |
| `AI_MODEL` | — | 模型名称（如 `gpt-4o-mini`） |

### AI 提供商

松鼠兼容所有 OpenAI 格式的 API：

- **OpenAI / Claude** — 设置 provider 为 `openai`，配置 base URL 和密钥。
- **Ollama（本地）** — 设置 provider 为 `ollama`，运行 Qwen 或 Llama3 等本地模型。
- **Mock** — 基于规则的解析器，无需 AI 服务即可测试。

## 项目结构

```
Squirrel/
├── server/          # Python FastAPI 后端
│   ├── app/
│   │   ├── api/     # API 路由
│   │   ├── core/    # 配置管理
│   │   ├── db/      # SQLite 数据库
│   │   ├── models/  # Pydantic 数据模型
│   │   └── services/# AI、解析器、Markdown、向量存储
│   └── tests/
├── squirrel/        # React 前端
│   ├── src/
│   │   ├── components/
│   │   ├── api.ts
│   │   └── types.ts
│   └── nginx.conf
├── cli/             # Go 命令行工具
│   └── main.go
├── data/            # 运行时数据（SQLite、Chroma）
├── storage/         # Markdown 导出
└── docker-compose.yml
```

## API 接口

所有接口位于 `/api` 路径下：

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/api/state` | 获取完整应用状态 |
| `POST` | `/api/items` | 添加库存物品 |
| `PUT` | `/api/items/:id` | 更新物品 |
| `DELETE` | `/api/items/:id` | 删除物品 |
| `POST` | `/api/chat` | 与 AI 助手对话 |
| `POST` | `/api/chat/confirm` | 确认待执行操作 |
| `GET` | `/api/search` | 搜索库存 |
| `GET` | `/api/export/markdown` | 导出 Markdown 库存报告 |

## 开源协议

MIT

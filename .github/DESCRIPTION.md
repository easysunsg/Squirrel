## GitHub About (仓库简介)

**一行描述（填入 GitHub About 栏）：**

```
本地优先的智能家居库存管理器 — AI 驱动自然语言录入，告别翻箱倒柜和过期浪费
```

**英文版：**

```
Local-first smart home inventory manager — AI-powered natural language entry, never lose track of what you have
```

---

## GitHub Topics（推荐标签）

```
inventory-management  home-assistant  ai-powered  fastapi  react  sqlite
natural-language  smart-home  self-hosted  docker  cli  markdown
```

---

## Pinned README 开头（放在 README.md 最顶部的徽章区）

```markdown
<div align="center">

# 🐿️ Squirrel — 松鼠库存管家

**像松鼠一样精于囤积，但再也不会忘记你的"坚果"藏在哪里。**

[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Python 3.12+](https://img.shields.io/badge/Python-3.12+-blue.svg)](https://python.org)
[![React 19](https://img.shields.io/badge/React-19-61DAFB.svg)](https://react.dev)
[![Docker](https://img.shields.io/badge/Docker-Ready-2496ED.svg)](docker-compose.yml)

[English](./README.md) · [中文](./README.zh-CN.md) · [快速开始](#快速开始)

</div>
```

---

## Release 介绍模板（首个版本发布时用）

```markdown
## 🎉 v0.1.0 — 初始发布

松鼠库存管家的第一个可用版本！

### ✨ 功能亮点

- 🗣️ **自然语言录入** — "买了3袋螺蛳粉，放客厅箱子里"，AI 自动解析入库
- 🔴🟡⚪ **三色过期预警** — 红卡（已过期）、黄卡（即将过期）、灰卡（长期闲置）
- 📍 **位置记忆** — 再也不用翻箱倒柜
- 💬 **AI 对话助手** — 问"冰箱里的菜能做什么？"
- 📝 **Markdown 同步** — 库存自动生成 `inventory.md`，兼容 Obsidian / Notion
- 🖥️ **多端使用** — Web UI + CLI + API
- 🐳 **一键部署** — `docker compose up --build` 即可运行

### 🛠️ 技术栈

FastAPI + SQLite + Chroma + React 19 + Vite + Tailwind CSS + Go CLI

### 🚀 快速开始

```bash
docker compose up --build
# 打开 http://localhost:5685
```

详细文档请查看 [README.md](./README.md)
```

---

## GitHub Pages / Wiki 首页文案

```markdown
# 为什么需要松鼠库存管家？

你有没有过这样的经历：

- 🛒 批量采购后，过几天就忘了买了什么
- 📦 囤货时随手一塞，用的时候翻箱倒柜
- 🥬 食材放到过期才发现，造成浪费
- 🤔 满屋物资，却总觉得"没什么可用的"

**松鼠库存管家**就是为了解决这些问题而生的。

## 设计理念

> **主动提醒、一眼看懂、极简不费脑**

- **不靠手动填表** — 说人话就能录入，AI 帮你解析
- **不靠记忆** — 到期自动提醒，位置帮你记着
- **不靠复杂工具** — 一个端口搞定一切，数据就在你的硬盘上

## 谁适合用？

- 🏠 **家庭用户** — 管理冰箱、储物柜、药品箱
- 🧑‍💻 **极客/程序员** — CLI 工具 + API，可集成到任何自动化流程
- 📦 **NAS 爱好者** — 本地部署，数据完全掌控
- 🤷 **懒人** — 说一句话就搞定，连 App 都不用打开
```

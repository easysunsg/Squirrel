"""Conflict resolution, confirmation, query, and response nodes."""

import logging
from datetime import datetime
from typing import Any, Dict, List, Literal
from uuid import uuid4

from app.models.state import (
    ExtendedGraphState,
    PendingOperation,
)
from app.services.cache import get_recipe_cache, set_recipe_cache
from app.services.llm import llm_service
from app.services.markdown import item_status
from app.services.parser import (
    parse_multi_selection,
)

logger = logging.getLogger(__name__)

from app.services.graph_utils import (
    _build_candidate_entries,
    _build_candidate_lines,
    _build_context_item,
    _build_multi_consume_allocation,
    _build_multi_consume_reply,
    _build_multi_remove_reply,
    _build_multi_update_reply,
    _calc_expire_days,
    _match_items_3tier,
    match_search_items,
)


# ==============================
# 节点 3: Conflict & Batch Resolver
# ==============================

def conflict_batch_resolver_node(state: ExtendedGraphState) -> Dict[str, Any]:
    """【核心大脑】FIFO 批次锁定、多义性识别、防囤货拦截。"""
    intent = state.get("intent", "")
    entities = state.get("extracted_entities", {})
    inventory = state.get("inventory", [])
    current_user = state.get("current_user")
    user_name = current_user.user_name if current_user else "主人"

    target_name = entities.get("target")
    if not target_name:
        # 从 add 的 items 中提取
        items_data = entities.get("items", [])
        if items_data:
            first = items_data[0] if isinstance(items_data[0], dict) else {}
            target_name = first.get("title", "")
        if not target_name:
            return {"reply_text": "管家听到您想操作物资，但没听清具体的物品名字，能再说一遍吗？"}

    candidates = _match_items_3tier(inventory, target_name)
    req_count = 1.0
    patch_data = entities.get("patch") or {}
    if "deductCount" in patch_data:
        try:
            req_count = float(patch_data["deductCount"])
        except (ValueError, TypeError):
            req_count = 1.0

    if intent in ("consume", "remove") and not candidates:
        return {
            "interaction_mode": "normal",
            "reply_text": f"查了一下库存，咱们家现在好像没有「{target_name}」呢，是不是记错名字啦？",
        }

    # ----- ADD 意图 -----
    if intent == "add":
        items_data = entities.get("items", [])
        split_source = entities.get("split_source")
        total_count = sum(float(item.get("count", 1)) for item in items_data if isinstance(item, dict))
        pending_patch = {"count": total_count or 1, "items_data": items_data}
        if isinstance(split_source, dict):
            pending_patch["split_source"] = split_source
        pending_op = PendingOperation(
            type="add",
            target_sku_title=target_name,
            patch=pending_patch,
        )
        summary = "、".join(
            f"{item.get('title', target_name)} {item.get('count', 1)}{item.get('unit', '件')}，存放在{item.get('location', '默认层架')}"
            for item in items_data if isinstance(item, dict)
        )
        return {
            "interaction_mode": "pending_confirm",
            "pending_item_selection": items_data,
            "pending_operation": pending_op,
            "reply_text": f"识别到：{summary}。确认入库吗？请回复「确认」或「取消」。",
        }

    if intent == "shopping_add":
        return {
            "interaction_mode": "normal",
            "reply_text": state.get("reply_text", ""),
        }

    # ----- CONSUME / REMOVE 意图 -----
    if intent in ("consume", "remove"):
        # 多义性消解
        if len(candidates) > 1:
            # 按临期升序 + 数量降序排序
            candidates.sort(
                key=lambda it: (_calc_expire_days(it) if _calc_expire_days(it) is not None else 9999, -it.count))
            candidates = candidates[:6]
            selection = _build_candidate_entries(candidates)
            lines = _build_candidate_lines(candidates, target_name)

            ded_patch = entities.get("patch") or {}
            pending_op = PendingOperation(
                type=intent,
                target_sku_title=target_name,
                patch=ded_patch,
            )
            return {
                "interaction_mode": "pending_selection",
                "pending_item_selection": selection,
                "pending_operation": pending_op,
                "reply_text": "\n".join(lines),
                "current_context_item": None,
            }

        # 单候选：FIFO 锁定
        target_item = candidates[0]
        ded_patch = entities.get("patch") or {}
        pending_op = PendingOperation(
            type=intent,
            target_sku_title=target_item.title,
            patch=ded_patch,
            source_batch_ids=[target_item.id] if target_item.id else [],
        )
        ctx_item = _build_context_item(target_item)
        logger.info("[Resolver] FIFO 锁定单品: %s", target_item.id)

        return {
            "interaction_mode": "pending_selection",
            "pending_item_selection": [_build_candidate_entries([target_item])[0]],
            "pending_operation": pending_op,
            "current_context_item": ctx_item,
            "reply_text": f"找到「{target_item.title}」— {target_item.spaceName}/{target_item.location} ({target_item.count}{target_item.unit})，确认要操作吗？",
        }

    # ----- UPDATE 意图 -----
    if intent in ("update_location", "update_expiry", "update_remaining"):
        patch = entities.get("patch", {})
        if not candidates:
            return {"reply_text": f"没有找到「{target_name}」相关的物品。"}
        if len(candidates) > 1:
            candidates = candidates[:6]
            selection = _build_candidate_entries(candidates)
            lines = _build_candidate_lines(candidates, target_name)
            pending_op = PendingOperation(
                type=intent,
                target_sku_title=target_name,
                patch=patch,
            )
            return {
                "interaction_mode": "pending_selection",
                "pending_item_selection": selection,
                "pending_operation": pending_op,
                "reply_text": "\n".join(lines),
            }
        # 单候选直接确认
        item = candidates[0]
        return {
            "confirmed_item_id": item.id,
            "confirmed_patch": patch,
            "reply_text": f"已更新「{item.title}」。",
            "current_context_item": _build_context_item(item),
        }

    return {}


def route_after_resolver(state: ExtendedGraphState) -> Literal["execute", "pending"]:
    """【条件路由】clean → mutation_executor / pending → post_process。"""
    mode = state.get("interaction_mode", "normal")
    if mode in ("pending_selection", "pending_confirm"):
        return "pending"
    return "execute"


# ==============================
# 节点 4: Pending Confirmation Handler
# ==============================

def confirm_subgraph_handler_node(state: ExtendedGraphState) -> Dict[str, Any]:
    """【确认处理器】处理用户对候选列表的确认/取消/多选等。"""
    text = state.get("raw_text_input", "").strip()
    selection = state.get("pending_item_selection", [])
    pending_op = state.get("pending_operation")
    inventory = state.get("inventory", [])

    if state.get("interaction_mode") == "pending_confirm":
        cancel_keywords = {"取消", "退出", "算了", "不要了", "不入库"}
        if any(keyword in text for keyword in cancel_keywords):
            return {
                "interaction_mode": "normal",
                "pending_item_selection": [],
                "pending_operation": None,
                "reply_text": "已取消入库。",
            }
        confirm_keywords = {"确认", "确定", "入库", "确认入库", "没问题", "可以"}
        if text not in confirm_keywords:
            return {
                "interaction_mode": "pending_confirm",
                "pending_item_selection": selection,
                "pending_operation": pending_op,
                "reply_text": "请回复「确认」完成入库，或回复「取消」。",
            }
        return {
            "intent": pending_op.type if pending_op else "chat",
            "interaction_mode": "normal",
            "pending_item_selection": [],
            "pending_operation": pending_op,
            "reply_text": "",
        }

    if not text:
        return {
            "interaction_mode": "pending_selection",
            "reply_text": f"请输入序号（1-{len(selection)}）或回复「取消」退出。",
        }

    # 取消
    cancel_keywords = {"取消", "退出", "不选了", "算了", "不要了"}
    if any(kw in text for kw in cancel_keywords):
        return {
            "interaction_mode": "normal",
            "pending_item_selection": [],
            "pending_operation": None,
            "reply_text": "已取消选择，有什么其他需要帮忙的吗？",
        }

    # 全部选择
    if text in ("全部", "所有", "全选"):
        if not selection:
            return {"reply_text": "没有可操作的物品。", "interaction_mode": "normal"}
        item_ids = [s.get("id") for s in selection if s.get("id")]

        op_type = pending_op.type if pending_op else "remove"
        patch = pending_op.patch if pending_op else {}

        # 根据原意图分流，保留原有的 operation 语义
        if op_type.startswith("update_"):
            return {
                "interaction_mode": "normal",
                "pending_item_selection": [],
                "pending_operation": None,
                "confirmed_item_ids": item_ids,
                "confirmed_patch": patch,
                "reply_text": _build_multi_update_reply(selection, op_type, patch),
            }
        if op_type == "consume":
            total_deduct = patch.get("deductCount")
            allocation = _build_multi_consume_allocation(selection, total_deduct)
            return {
                "interaction_mode": "normal",
                "pending_item_selection": [],
                "pending_operation": PendingOperation(
                    type="consume",
                    target_sku_title=pending_op.target_sku_title if pending_op else "",
                    patch={"deductCounts": allocation},
                    source_batch_ids=item_ids,
                ),
                "confirmed_item_ids": item_ids,
                "reply_text": _build_multi_consume_reply(selection, allocation),
            }
        # remove 默认
        return {
            "interaction_mode": "normal",
            "pending_item_selection": [],
            "pending_operation": None,
            "confirmed_item_ids": item_ids,
            "reply_text": _build_multi_remove_reply(selection),
        }

    # 解析序号
    parsed = parse_multi_selection(text, len(selection))
    if not isinstance(parsed, list) or len(parsed) == 0:
        return {
            "interaction_mode": "pending_selection",
            "reply_text": f"请输入有效序号（1-{len(selection)}），或回复「取消」退出。",
            "pending_item_selection": selection,
            "pending_operation": pending_op,
        }

    valid_indices = [i for i in parsed if 0 <= i < len(selection)]
    if not valid_indices:
        return {
            "interaction_mode": "pending_selection",
            "reply_text": f"序号超出范围，请输入 1~{len(selection)} 之间的数字。",
            "pending_item_selection": selection,
            "pending_operation": pending_op,
        }

    selected_items = [selection[i] for i in valid_indices]
    op_type = pending_op.type if pending_op else "consume"

    # --- 单选（取消 text.isdigit() 限制，完全以 valid_indices 解析结果为准） ---
    if len(valid_indices) == 1:
        sel = selected_items[0]
        item_id = sel.get("id")
        if op_type.startswith("update_"):
            patch = pending_op.patch if pending_op else {}
            return {
                "interaction_mode": "normal",
                "pending_item_selection": [],
                "pending_operation": None,
                "confirmed_item_id": item_id,
                "confirmed_patch": patch,
                "reply_text": f"已确认选择。",
            }
        # consume/remove 单选
        return {
            "interaction_mode": "normal",
            "pending_item_selection": [],
            "pending_operation": PendingOperation(
                type=op_type,
                target_sku_title=sel.get("title", ""),
                patch=(pending_op.patch if pending_op else {}),
                source_batch_ids=[item_id] if item_id else [],
            ),
            # The executor owns the final outcome text after mutation logs are produced.
            "reply_text": "",
        }

    # --- 多选 ---
    item_ids = [s.get("id") for s in selected_items if s.get("id")]

    if op_type.startswith("update_"):
        patch = pending_op.patch if pending_op else {}
        return {
            "interaction_mode": "normal",
            "pending_item_selection": [],
            "pending_operation": None,
            "confirmed_item_ids": item_ids,
            "confirmed_patch": patch,
            "reply_text": _build_multi_update_reply(selected_items, op_type, patch),
        }

    if op_type == "remove":
        return {
            "interaction_mode": "normal",
            "pending_item_selection": [],
            "pending_operation": None,
            "confirmed_item_ids": item_ids,
            "reply_text": _build_multi_remove_reply(selected_items),
        }

    # 默认：consume 多选
    total_deduct = (pending_op.patch or {}).get("deductCount") if pending_op else None
    allocation = _build_multi_consume_allocation(selected_items, total_deduct)
    reply_text = _build_multi_consume_reply(selected_items, allocation)

    return {
        "interaction_mode": "normal",
        "pending_item_selection": [],
        "pending_operation": PendingOperation(
            type="consume",
            target_sku_title="",
            patch={"deductCounts": allocation},
            source_batch_ids=list(allocation.keys()),
        ),
        "reply_text": reply_text,
    }


def route_after_confirm(state: ExtendedGraphState) -> Literal["success", "cancel"]:
    """【条件路由】确认成功 → mutation_executor / 取消 → post_process。"""
    mode = state.get("interaction_mode", "normal")
    if mode in ("pending_selection", "pending_confirm"):
        return "cancel"  # 保持在 pending_selection -> post_process 刷新状态
    return "success"


# ==============================
# 节点 5: Mutation Executor
# ==============================

def mutation_executor_node(state: ExtendedGraphState) -> Dict[str, Any]:
    """【原子事务执行】生成 mutation_logs（不写 DB）。"""
    pending_op = state.get("pending_operation")
    current_user = state.get("current_user")
    inventory = state.get("inventory", [])
    confirmed_item_id = state.get("confirmed_item_id")
    confirmed_item_ids = state.get("confirmed_item_ids", [])
    confirmed_patch = state.get("confirmed_patch")
    user_id = current_user.user_id if current_user else "default"
    user_name = current_user.user_name if current_user else "主人"

    new_logs: List[Dict[str, Any]] = []
    reply_text = state.get("reply_text", "")
    pending_add_items: List[Dict[str, Any]] = []  # 用于返回给 adapter 层
    next_last_added = state.get("last_added_item")
    next_context_item = state.get("current_context_item")
    # --- 处理来自 confirm_handler 的单选 ID ---
    if confirmed_item_id and confirmed_patch:
        # update 操作：通过 patch 直接修改
        target = next((it for it in inventory if it.id == confirmed_item_id), None)
        if target:
            new_logs.append({
                "event_id": f"evt_{datetime.now().timestamp()}",
                "op_type": "update",
                "target_instance_id": confirmed_item_id,
                "sku_title": target.title,
                "patch": confirmed_patch,
                "delta": 0,
                "operator_id": user_id,
                "operator_name": user_name,
                "timestamp": datetime.now().isoformat(),
            })
        return {
            "mutation_logs": new_logs,
            "interaction_mode": "normal",
            "pending_operation": None,
            "pending_item_selection": [],
        }

    if confirmed_item_ids:
        # 批量操作（移除/清除）
        for item_id in confirmed_item_ids:
            target = next((it for it in inventory if it.id == item_id), None)
            if confirmed_patch:
                new_logs.append({
                    "event_id": f"evt_{datetime.now().timestamp()}",
                    "op_type": "update",
                    "target_instance_id": item_id,
                    "sku_title": target.title if target else "",
                    "patch": confirmed_patch,
                    "delta": 0,
                    "operator_id": user_id,
                    "operator_name": user_name,
                    "timestamp": datetime.now().isoformat(),
                })
            else:
                new_logs.append({
                    "event_id": f"evt_{datetime.now().timestamp()}",
                    "op_type": "remove",
                    "target_instance_id": item_id,
                    "sku_title": target.title if target else "",
                    "delta": -(target.count if target else 1),
                    "operator_id": user_id,
                    "operator_name": user_name,
                    "timestamp": datetime.now().isoformat(),
                })
        return {
            "mutation_logs": new_logs,
            "interaction_mode": "normal",
            "pending_operation": None,
            "pending_item_selection": [],
        }

    # --- 处理 pending_operation ---
    if not pending_op:
        logger.warning("[Executor] 没有待执行的挂起事务")
        return {}

    logger.info("[Executor] 处理挂起事务: %s -> %s", pending_op.type, pending_op.target_sku_title)

    if pending_op.type == "add":
        add_count = pending_op.patch.get("count", 1.0)
        items_data = pending_op.patch.get("items_data", [])
        split_source = pending_op.patch.get("split_source")
        if isinstance(split_source, dict) and split_source.get("id"):
            new_logs.append({
                "event_id": f"evt_{datetime.now().timestamp()}_split",
                "op_type": "consume",
                "target_instance_id": split_source["id"],
                "sku_title": split_source.get("title", ""),
                "delta": -int(split_source.get("count", 0)),
                "operator_id": user_id,
                "operator_name": user_name,
                "timestamp": datetime.now().isoformat(),
            })
        for item_dict in items_data:
            new_logs.append({
                "event_id": f"evt_{datetime.now().timestamp()}",
                "op_type": "add",
                "target_instance_id": f"new_{uuid4().hex[:12]}",
                "sku_title": item_dict.get("title", pending_op.target_sku_title),
                "delta": item_dict.get("count", add_count),
                "item_data": item_dict,
                "operator_id": user_id,
                "operator_name": user_name,
                "timestamp": datetime.now().isoformat(),
            })
        if not reply_text:
            summary = "、".join(
                f"{item.get('title', pending_op.target_sku_title)} {item.get('count', 1)}{item.get('unit', '件')}"
                for item in items_data
            )
            reply_text = f"已确认入库：{summary}。"

        # 🚨 修复：不直接修改 state，而是将增量数据放入返回字典，让 LangGraph 统一调度更新
        pending_add_items = items_data
        if items_data:
            next_last_added = items_data[-1]
            next_context_item = {
                "id": items_data[-1].get("id"),
                "title": items_data[-1].get("title", pending_op.target_sku_title),
                "location": items_data[-1].get("location", "默认层架"),
                "spaceName": items_data[-1].get("spaceName", ""),
                "count": items_data[-1].get("count", 1),
                "unit": items_data[-1].get("unit", "件"),
            }

    elif pending_op.type in ("consume", "remove"):
        deduct_count = pending_op.patch.get("deductCount", 1.0)
        affected_items: list[tuple[Item, int]] = []

        # 支持多选分摊模式（deductCounts）
        deduct_counts = pending_op.patch.get("deductCounts", {})
        for batch_id in pending_op.source_batch_ids:
            target = next((it for it in inventory if it.id == batch_id), None)
            actual_deduct = 1
            if deduct_counts and isinstance(deduct_counts, dict):
                actual_deduct = deduct_counts.get(batch_id, 1)
            elif isinstance(deduct_count, (int, float)):
                actual_deduct = int(deduct_count)
            if target:
                affected_items.append((target, actual_deduct))
            new_logs.append({
                "event_id": f"evt_{datetime.now().timestamp()}",
                "op_type": pending_op.type,
                "target_instance_id": batch_id,
                "sku_title": pending_op.target_sku_title,
                "delta": -actual_deduct,
                "operator_id": user_id,
                "operator_name": user_name,
                "timestamp": datetime.now().isoformat(),
            })

        if not reply_text:
            if pending_op.type == "remove" and affected_items:
                summary = "、".join(
                    f"「{item.title}」{item.count}{item.unit}" for item, _ in affected_items
                )
                reply_text = f"已从库存移除：{summary}。"
            elif affected_items:
                summary = "、".join(
                    f"「{item.title}」{deduct}{item.unit}" for item, deduct in affected_items
                )
                reply_text = f"已扣减库存：{summary}。"
            else:
                reply_text = f"没有找到可处理的「{pending_op.target_sku_title}」。"

    return {
        "mutation_logs": new_logs,
        "interaction_mode": "normal",
        "pending_operation": None,
        "pending_item_selection": [],
        "reply_text": reply_text,
        "pending_add_items": pending_add_items,
        "last_added_item": next_last_added,
        "current_context_item": next_context_item,
    }


# ==============================
# 节点 6: Query & Recipe Handler
# ==============================

def query_handler_node(state: ExtendedGraphState) -> Dict[str, Any]:
    """【查询与菜谱】处理所有只读请求，使用 current_context_item 继承时空记忆。"""
    intent = state.get("intent", "")
    entities = state.get("extracted_entities", {})
    inventory = state.get("inventory", [])
    current_context = state.get("current_context_item")
    user_pref = state.get("user_preference", "无特殊要求")
    reminder_time = state.get("reminder_time", "")

    # 跨轮次记忆回溯
    target_item_title = entities.get("target")
    target_location = "指定位置"
    if not target_item_title and current_context:
        target_item_title = current_context.get("title")
        target_location = current_context.get("location", "现有储物区")
        logger.info("[Query/Recipe] 触发上下文继承: title=%s location=%s", target_item_title, target_location)

    # ------ expiry_query ------
    if intent == "expiry_query":
        danger = [item for item in inventory if item_status(item) == "danger"]
        if not danger:
            return {"reply_text": "当前没有红色告急或过期预警物品。"}
        summary = "、".join(f"{item.title}（{item.spaceName}/{item.location}）" for item in danger[:6])
        return {"reply_text": f"现在最需要优先处理的是：{summary}。"}

    # ------ location_query ------
    if intent == "location_query":
        text = state.get("raw_text_input", "")
        candidates = [
            item for item in inventory
            if item.title in text or text in item.title or item.location in text or item.spaceName in text
        ]
        if not candidates:
            return {"reply_text": "我暂时没在库存里精确匹配到位置，可以试试输入更具体的物品名。"}
        item = candidates[0]
        ctx = _build_context_item(item) if len(candidates) == 1 else None
        return {
            "reply_text": f"{item.title} 在 {item.spaceName} / {item.location}，当前剩余 {item.remainingPct}%。",
            "current_context_item": ctx,
        }

    # ------ quantity_query ------
    if intent == "quantity_query":
        # 1. 优先从上游大模型提取的实体里拿
        query = entities.get("target")

        # 2. 如果上游没拿到，尝试从跨轮上下文记忆里继承
        if not query and current_context:
            query = current_context.get("title")

        # 3. 如果还是没有，才用正则 parser 兜底
        if not query:
            text = state.get("raw_text_input", "")
            from app.services.parser import extract_search_keyword
            query = extract_search_keyword(text)

        raw_text = state.get("raw_text_input", "")
        mentioned_titles = {item.title for item in inventory if item.title and item.title in raw_text}
        if mentioned_titles:
            # Specific variants win over their base name: 无糖可乐 over 可乐.
            query = max(mentioned_titles, key=len)

        logger.info("[Query Handler] 数量查询关键词锁定为: %s", query)

        # A base product query includes named variants, e.g. 可乐 + 无糖可乐.
        candidates = [
            item for item in inventory
            if query and (item.title == query or item.title.endswith(query))
        ]
        if not candidates:
            candidates = _match_items_3tier(inventory, query)
        if not candidates:
            return {"reply_text": f"没有找到「{query or '指定物品'}」相关信息。"}

        unit_totals: dict[str, int] = {}
        for item in candidates:
            unit_totals[item.unit] = unit_totals.get(item.unit, 0) + item.count
        total_summary = "、".join(f"{count}{unit}" for unit, count in unit_totals.items())
        location_summary = "、".join(
            f"{item.title} {item.count}{item.unit}（{item.spaceName}/{item.location}）"
            for item in candidates
        )
        context_item = _build_context_item(candidates[0]) if len(candidates) == 1 else None
        return {
            "reply_text": f"家里共有「{query}」{total_summary}：{location_summary}。",
            "current_context_item": context_item,
        }

    # ------ search_query ------
    if intent == "search_query":
        text = state.get("raw_text_input", "")
        exclude_id = current_context.get("id") if "别的" in text and current_context else None
        exclude_title = current_context.get("title") if "别的" in text and current_context else None
        results = match_search_items(
            text,
            inventory,
            exclude_item_id=exclude_id,
            exclude_title=exclude_title,
            extracted_constraints=entities.get("search_constraints"),
        )
        if not results:
            location = next(
                (term for term in ("冷藏层", "冷冻层", "冰箱上层", "冰箱下层", "冰箱中层", "柜子") if term in text),
                "库存",
            )
            if "盘装" in text and "生鲜" in text:
                category = "盘装生鲜"
            elif "饮料" in text:
                category = "饮料"
            else:
                category = "符合条件的物品"
            excluded = f"除了「{exclude_title}」，" if exclude_title else ""
            other = "其他" if any(term in text for term in ("别的", "其他")) else ""
            return {"reply_text": f"{location}里{excluded}没有找到{other}{category}。"}
        summary = "、".join(f"{item.title}（{item.spaceName}/{item.location}）" for item in results[:6])
        return {"reply_text": f"搜索到以下物品：{summary}。"}

    # ------ idle_query ------
    if intent == "idle_query":
        idle = [
            item for item in inventory
            if item.remainingPct >= 80 and item_status(item) == "full"
        ]
        idle.sort(key=lambda it: (it.buyDate or ""))
        if not idle:
            return {"reply_text": "当前没有明显长期闲置的物品。"}
        summary = "、".join(f"{item.title}（{item.spaceName}/{item.location}）" for item in idle[:6])
        return {"reply_text": f"这些物品可能放了比较久：{summary}。"}

    # ------ recipe ------
    if intent == "recipe":
        if not target_item_title:
            return {"reply_text": "您是想用哪些快过期的食材来生成菜单呢？可以随手拍张照片或者直接告诉管家哦。"}

        expiring_list = []
        for item in inventory:
            if item.category != "food":
                continue
            st = item_status(item)
            expire_days = _calc_expire_days(item)
            if st != "full" or (item.expireDate and expire_days is not None and expire_days <= 7):
                expiring_list.append({
                    "name": item.title,
                    "quantity": item.count,
                    "unit": item.unit,
                    "expire_days": expire_days or 0,
                })
        expiring_list.sort(key=lambda x: (x["expire_days"], -x["quantity"]))
        expiring_list = expiring_list[:10]

        cached = get_recipe_cache(expiring_list, user_pref, reminder_time)
        if cached:
            return {
                "reply_text": cached.get("recipe_recommend", {}).get("intro", "菜谱已生成"),
                "recipe_recommendation": cached,
            }

        result = llm_service.generate_expiring_recipe(expiring_list, user_pref)
        if not result.get("isFallback") and result.get("recipe_recommend"):
            set_recipe_cache(expiring_list, user_pref, result, reminder_time)

        if result.get("isFallback") and result.get("fallbackText"):
            reply = result["fallbackText"]
        elif result.get("recipe_recommend"):
            reply = result["recipe_recommend"].get("intro", "菜谱已生成")
        else:
            reply = "暂无足够的食材信息生成菜谱，请先添加一些食材到库存吧。"

        return {
            "reply_text": reply,
            "recipe_recommendation": result,
        }

    # ------ chat ------
    if intent == "chat":
        context_parts = [f"库存总数：{len(inventory)} 件"]
        danger = [item for item in inventory if item_status(item) == "danger"]
        if danger:
            context_parts.append(f"临期/告急：{len(danger)} 件")
        context = "；".join(context_parts)
        if llm_service.enabled:
            try:
                reply = llm_service.chat_reply(state.get("raw_text_input", ""), context)
                return {"reply_text": reply}
            except Exception:
                logger.exception("LLM chat failed, falling back")
        return {"reply_text": f"我查到当前共有 {len(inventory)} 件库存。你可以让我录入、查位置、列临期或生成菜谱。"}

    return {"reply_text": "收到，管家已为您处理完毕。"}


# ==============================
# 节点 7: Central Post Process
# ==============================

def post_process_node(state: ExtendedGraphState) -> Dict[str, Any]:
    """【统一出口】轻量透传 — 已迁移到 response_generator_node。"""
    return {
        "reply_text": state.get("reply_text", "收到，管家已为您处理完毕。"),
        "current_context_item": state.get("current_context_item"),
    }

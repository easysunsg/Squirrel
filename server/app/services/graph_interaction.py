"""Conflict resolution, confirmation, query, and response nodes."""

import logging
from datetime import date, datetime
from typing import Any, Dict, List, Literal, Optional
from uuid import uuid4

from app.db.sqlite import get_active_snapshot, save_snapshot, save_checkpoint, get_checkpoint
from app.models.schemas import ChatOperation, ChatResult, Item, RecipeRequest
from app.models.state import (
    ActionStatus,
    AgentAction,
    ExtendedGraphState,
    PendingOperation,
    UserContext,
    EventType, SystemEvent, generate_idempotency_key, mutation_log_to_event,
    merge_audit_logs,
    version_conflict_check,
)
from app.services.planner import plan_actions
from app.services.capabilities import CapabilityRegistry
from app.services.idempotency import idempotency_service
from app.services.event_bus import event_bus
from app.services.cache import get_recipe_cache, set_recipe_cache
from app.services.llm import llm_service
from app.services.markdown import item_status
from app.services.parser import (
    build_chat_result,
    days_from_now,
    extract_expire_patch,
    extract_location_update,
    extract_target_title,
    extract_remaining_patch,
    extract_search_keyword,
    infer_search_terms,
    parse_lightning_text,
    parse_multi_selection,
)
from app.services.spatial_service import spatial_service
from app.services.vector_store import vector_store

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
    _is_pronoun_or_garbage_target,
    _match_items_3tier,
    match_search_items,
    summarize_titles,
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
        # 创建 PendingOperation 供 mutation_executor 使用
        add_count = float(entities.get("item_count", 1))
        pending_op = PendingOperation(
            type="add",
            target_sku_title=target_name,
            patch={"count": add_count, "items_data": items_data},
        )
        return {
            "pending_operation": pending_op,
            "reply_text": state.get("reply_text", ""),
        }

    # ----- CONSUME / REMOVE 意图 -----
    if intent in ("consume", "remove"):
        # 多义性消解
        if len(candidates) > 1:
            # 按临期升序 + 数量降序排序
            candidates.sort(key=lambda it: (_calc_expire_days(it) if _calc_expire_days(it) is not None else 9999, -it.count))
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
    if mode == "pending_selection":
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
            "reply_text": f"已确认选择：{sel.get('title', '')}。正在为您处理...",
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
    if mode == "pending_selection":
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
            reply_text = f"登记成功！已帮您将物品录入系统。"

        # 🚨 修复：不直接修改 state，而是将增量数据放入返回字典，让 LangGraph 统一调度更新
        pending_add_items = items_data

    elif pending_op.type in ("consume", "remove"):
        deduct_count = pending_op.patch.get("deductCount", 1.0)

        # 支持多选分摊模式（deductCounts）
        deduct_counts = pending_op.patch.get("deductCounts", {})
        for batch_id in pending_op.source_batch_ids:
            target = next((it for it in inventory if it.id == batch_id), None)
            actual_deduct = 1
            if deduct_counts and isinstance(deduct_counts, dict):
                actual_deduct = deduct_counts.get(batch_id, 1)
            elif isinstance(deduct_count, (int, float)):
                actual_deduct = int(deduct_count)
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
            reply_text = f"好滴{user_name}，已帮您处理了 **{pending_op.target_sku_title}**。"

    return {
        "mutation_logs": new_logs,
        "interaction_mode": "normal",
        "pending_operation": None,
        "pending_item_selection": [],
        "reply_text": reply_text,
        "pending_add_items": pending_add_items,
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

        logger.info("[Query Handler] 数量查询关键词锁定为: %s", query)

        candidates = _match_items_3tier(inventory, query)
        if not candidates:
            return {"reply_text": f"没有找到「{query or '指定物品'}」相关信息。"}
        item = candidates[0]
        return {
            "reply_text": f"「{item.title}」还剩 {item.count}{item.unit}，在 {item.spaceName}{item.location}。",
            "current_context_item": _build_context_item(item),
        }

    # ------ search_query ------
    if intent == "search_query":
        text = state.get("raw_text_input", "")
        exclude_id = current_context.get("id") if "别的" in text and current_context else None
        results = match_search_items(text, inventory, exclude_item_id=exclude_id)
        if not results:
            return {"reply_text": "没有找到匹配的物品。"}
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



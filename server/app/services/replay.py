"""REPLAY 模式执行引擎 — 基于 Checkpoint 的回放与审计。

支持 REPLAY 模式下的执行回放，用于系统容灾和审计场景。
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

from app.db.sqlite import connect, list_checkpoints, get_checkpoint

logger = logging.getLogger(__name__)


class ReplayEngine:
    """REPLAY 模式执行引擎。

    职责：
    1. 加载指定会话的检查点链
    2. 从指定检查点开始回放执行路径
    3. 提供检查点浏览和审计能力
    """

    def __init__(self, session_id: str = "default_session") -> None:
        self.session_id = session_id
        self._checkpoints: List[Dict[str, Any]] = []

    def load_checkpoints(self, limit: int = 50) -> List[Dict[str, Any]]:
        """加载指定会话的所有检查点，按 graph_version 降序排列。

        Args:
            limit: 最大返回数量

        Returns:
            检查点字典列表
        """
        with connect() as conn:
            self._checkpoints = list_checkpoints(conn, self.session_id, limit=limit)
        logger.info(
            "[ReplayEngine] 加载了 %d 个检查点 (session=%s)",
            len(self._checkpoints), self.session_id,
        )
        return self._checkpoints

    def get_checkpoint_by_id(self, checkpoint_id: str) -> Optional[Dict[str, Any]]:
        """按 ID 获取指定检查点。"""
        with connect() as conn:
            return get_checkpoint(conn, checkpoint_id)

    def get_latest_checkpoint(self) -> Optional[Dict[str, Any]]:
        """获取最新检查点。

        需要先调用 load_checkpoints() 加载检查点列表。
        """
        return self._checkpoints[0] if self._checkpoints else None

    def replay_from_checkpoint(
        self,
        checkpoint_id: str,
    ) -> Dict[str, Any]:
        """从指定检查点回放执行路径。

        当前实现返回检查点中的 state_snapshot，
        后续可扩展为实际的图节点重放逻辑。

        Returns:
            回放结果字典
        """
        checkpoint = self.get_checkpoint_by_id(checkpoint_id)
        if checkpoint is None:
            raise ValueError(f"检查点不存在: {checkpoint_id}")

        snapshot = checkpoint.get("state_snapshot", {})
        logger.info(
            "[ReplayEngine] 回放检查点 %s (version=%d, node=%s)",
            checkpoint_id, checkpoint["graph_version"], checkpoint["node_name"],
        )

        return {
            "replayed": True,
            "checkpoint_id": checkpoint_id,
            "graph_version": checkpoint["graph_version"],
            "node_name": checkpoint["node_name"],
            "state_snapshot": snapshot,
        }

    def fast_forward(
        self,
        target_version: int,
    ) -> List[Dict[str, Any]]:
        """快进到指定 graph_version。

        返回从当前到目标版本之间所有检查点的 state_snapshot 列表。

        Args:
            target_version: 目标 graph_version

        Returns:
            快进路径上的所有状态快照
        """
        if not self._checkpoints:
            self.load_checkpoints()

        snapshots = []
        for cp in sorted(self._checkpoints, key=lambda x: x["graph_version"]):
            if cp["graph_version"] <= target_version:
                snapshots.append(cp["state_snapshot"])
        logger.info(
            "[ReplayEngine] 快进到 version=%d, 经过 %d 个检查点",
            target_version, len(snapshots),
        )
        return snapshots


# 模块级单例
replay_engine = ReplayEngine()

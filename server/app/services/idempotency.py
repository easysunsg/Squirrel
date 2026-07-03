"""幂等锁服务 — 防止重复执行。

基于 DB UNIQUE INDEX 实现 SETNX 语义。
"""

import json
import logging
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

from app.models.state import ActionStatus, generate_idempotency_key

logger = logging.getLogger(__name__)


class IdempotencyService:
    """幂等锁服务。

    使用 DB 唯一索引实现幂等校验：
    - 执行前检查 idempotency_key 是否存在且为 SUCCESS → 返回缓存结果
    - 不存在 → 插入新记录并执行
    - 存在但为 PENDING/RUNNING → 拒绝（防止并发）
    - 存在但为 FAILED → 允许重试
    """

    def __init__(self):
        self._local_cache: Dict[str, dict] = {}

    def check_and_acquire(
        self,
        key: str,
        conn,
        ttl_minutes: int = 30,
    ) -> tuple[bool, Optional[dict]]:
        """检查并获取幂等锁。

        Args:
            key: idempotency_key
            conn: DB 连接
            ttl_minutes: 锁 TTL

        Returns:
            (can_execute, cached_result)
            can_execute=True → 可以执行，调用方需在完成后调用 complete()
            can_execute=False → 已有缓存结果，返回 cached_result
        """
        row = conn.execute(
            "SELECT status, result_data, expires_at FROM idempotency_keys WHERE key = ?",
            (key,),
        ).fetchone()

        if row:
            status = row["status"]
            # 已成功完成 → 返回缓存结果
            if status == "SUCCESS":
                result_data = json.loads(row["result_data"]) if row["result_data"] else {}
                logger.info("[Idempotency] 命中幂等缓存 key=%s", key[:20])
                return False, result_data

            # 正在执行中 → 拒绝并发
            if status in ("PENDING", "RUNNING"):
                logger.warning("[Idempotency] 并发冲突 key=%s status=%s", key[:20], status)
                return False, {"error": "操作正在执行中，请稍后重试"}

            # FAILED → 允许重试
            logger.info("[Idempotency] 重试失败操作 key=%s", key[:20])

        # 插入新记录
        now = datetime.now().isoformat()
        expires = (datetime.now() + timedelta(minutes=ttl_minutes)).isoformat()
        conn.execute(
            """INSERT INTO idempotency_keys(key, status, created_at, expires_at)
               VALUES(?, ?, ?, ?)
               ON CONFLICT(key) DO UPDATE SET
                   status=excluded.status,
                   expires_at=excluded.expires_at
                   WHERE status = 'FAILED'""",
            (key, "PENDING", now, expires),
        )
        return True, None

    def complete(self, key: str, conn, result: dict, status: str = "SUCCESS") -> None:
        """标记幂等锁为已完成。

        Args:
            key: idempotency_key
            conn: DB 连接
            result: 执行结果（将被缓存）
            status: SUCCESS 或 FAILED
        """
        now = datetime.now().isoformat()
        conn.execute(
            """UPDATE idempotency_keys
               SET status = ?, result_data = ?, completed_at = ?, updated_at = ?
               WHERE key = ?""",
            (status, json.dumps(result, ensure_ascii=False, default=str), now, now, key),
        )
        logger.info("[Idempotency] 完成 key=%s status=%s", key[:20], status)

    def cleanup_expired(self, conn, ttl_minutes: int = 60) -> int:
        """清理过期记录。"""
        cutoff = (datetime.now() - timedelta(minutes=ttl_minutes)).isoformat()
        cur = conn.execute("DELETE FROM idempotency_keys WHERE expires_at < ?", (cutoff,))
        return cur.rowcount


idempotency_service = IdempotencyService()
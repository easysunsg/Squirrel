"""Conflict detection service for multi-tenant SKU collision warnings."""

import logging
from datetime import datetime, timedelta

from app.models.schemas import ConflictWarning

logger = logging.getLogger(__name__)


class ConflictService:
    """Check for recent SKU operations by other users to warn about duplicate purchases."""

    def check_recent_same_sku(
        self,
        conn,
        sku_title: str,
        current_user: str,
        window_hours: int = 3,
    ) -> ConflictWarning | None:
        """Check if another user recently operated on the same SKU.

        Returns ConflictWarning if another user has added/operated on the same
        SKU within the time window, None otherwise.
        """
        cutoff = (datetime.now() - timedelta(hours=window_hours)).isoformat()
        rows = conn.execute(
            """SELECT ii.last_modified_by, ii.created_at, sku.title
               FROM item_instances ii
               JOIN skus sku ON ii.sku_id = sku.sku_id
               WHERE sku.title = ?
                 AND ii.last_modified_by != ?
                 AND ii.created_at >= ?""",
            (sku_title, current_user, cutoff),
        ).fetchall()

        if not rows:
            return None

        row = rows[0]
        other_user = row["last_modified_by"]
        created_at_str = row["created_at"] or ""

        # Calculate how long ago
        try:
            created_at = datetime.fromisoformat(created_at_str)
            hours_ago = round((datetime.now() - created_at).total_seconds() / 3600, 1)
            if hours_ago < 1:
                time_str = f"{int(hours_ago * 60)}分钟前"
            else:
                time_str = f"{int(hours_ago)}小时前"
        except (ValueError, TypeError):
            hours_ago = 0.0
            time_str = "近期"

        warning_text = (
            f"先别买！{other_user}在{time_str}已购买{sku_title}，"
            f"确认还需要再买吗？"
        )

        return ConflictWarning(
            other_user=other_user,
            sku_title=sku_title,
            action_type="add",
            time_ago_hours=hours_ago,
            warning_text=warning_text,
        )


conflict_service = ConflictService()
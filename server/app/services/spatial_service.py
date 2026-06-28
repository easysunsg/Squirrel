"""Spatial node service — resolve natural-language location references to slot IDs."""

import logging

from app.db.sqlite import connect, find_node_by_alias, find_nodes_by_name_fragment, get_child_node_ids

logger = logging.getLogger(__name__)


class SpatialService:
    """Resolve user's natural-language location mentions to SpatialNode slot IDs."""

    def resolve_location_to_slots(self, text: str) -> list[str]:
        """Extract location references from text, match against SpatialNode names/aliases,
        and return matching Slot node IDs.

        Strategy:
        1. Extract location-like phrases from the text
        2. Try exact match on node name or aliases
        3. Try fragment match
        4. If a non-Slot node matches (Zone/Fixture/Container), expand to all descendant Slots
        """
        if not text:
            return []

        phrases = self._extract_location_phrases(text)
        if not phrases:
            return []

        slot_ids: set[str] = set()
        with connect() as conn:
            for phrase in phrases:
                node = find_node_by_alias(conn, phrase)
                if node:
                    if node.node_type == "Slot":
                        slot_ids.add(node.node_id)
                    else:
                        descendants = get_child_node_ids(conn, node.node_id)
                        slot_ids.update(descendants)
                    continue

                nodes = find_nodes_by_name_fragment(conn, phrase)
                for n in nodes:
                    if n.node_type == "Slot":
                        slot_ids.add(n.node_id)
                    else:
                        slot_ids.update(get_child_node_ids(conn, n.node_id))

        return list(slot_ids)

    def _extract_location_phrases(self, text: str) -> list[str]:
        """Extract location-like phrases from Chinese text."""
        import re

        LOCATION_KEYWORDS = [
            "冰箱下层", "冰箱中层", "冰箱上层",
            "橱柜下层", "橱柜上层", "下面的抽屉",
            "储物间 A 区", "储物间 B 区", "药品箱",
            "车库 A4 搁板", "车库 B3 搁板",
            "冰箱", "橱柜", "搁板", "架子", "货架",
            "厨房", "储藏间", "车库",
            "下层", "上层", "中层", "抽屉",
        ]

        found = []
        for kw in LOCATION_KEYWORDS:
            if kw in text:
                found.append(kw)

        match = re.search(r"放(?:在|到|进)?(.+?)(?:里|中|上|下|$)", text)
        if match:
            loc = match.group(1).strip(" ，,。的")
            if loc and loc not in found:
                found.append(loc)

        return found


spatial_service = SpatialService()
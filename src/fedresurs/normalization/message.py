from __future__ import annotations

from typing import Any

from fedresurs.normalization.hashing import canonical_json, content_hash
from fedresurs.timeutil import to_msk_iso


def normalize_message(item: dict[str, Any], trade_guid: str) -> dict[str, Any] | None:
    guid = item.get("guid")
    if not guid:
        return None

    normalized: dict[str, Any] = {
        "guid": guid,
        "trade_guid": trade_guid,
        "event_time": to_msk_iso(item.get("eventTime")),
        "number": item.get("number"),
        "date_publish": to_msk_iso(item.get("datePublish")),
        "type": item.get("type"),
        "is_annulled": int(bool(item.get("isAnnuled"))),
        "is_locked": int(bool(item.get("isLocked"))),
        "text_html": None,
        "text_plain": None,
        "files_json": canonical_json(item.get("files") or []),
    }
    normalized["content_hash"] = content_hash(normalized)
    return normalized

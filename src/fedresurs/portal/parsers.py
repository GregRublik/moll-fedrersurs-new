from __future__ import annotations

import json
from typing import Any


class PortalParseError(Exception):
    pass


def parse_json(text: str) -> dict[str, Any] | list[Any]:
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise PortalParseError(f"response is not JSON: {text[:120]!r}") from exc
    if not isinstance(payload, (dict, list)):
        raise PortalParseError(f"unexpected JSON root: {type(payload).__name__}")
    return payload


def extract_page(payload: dict[str, Any] | list[Any]) -> tuple[list[dict[str, Any]], int | None]:
    """Return (items, found) for list endpoints.

    Some endpoints return a bare list, most return {"pageData": [...], "found": N}.
    """
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)], len(payload)

    page = payload.get("pageData")
    if page is None:
        raise PortalParseError("response has no 'pageData'")
    if not isinstance(page, list):
        raise PortalParseError("'pageData' is not a list")

    found = payload.get("found")
    if isinstance(found, bool):
        found = None
    elif isinstance(found, (int, float)):
        found = int(found)
    else:
        found = None

    return [item for item in page if isinstance(item, dict)], found

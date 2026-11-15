from __future__ import annotations

import html
import re
from decimal import Decimal, InvalidOperation

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def strip_html(value: str | None) -> str | None:
    if not value:
        return None
    text = _TAG_RE.sub(" ", value)
    text = html.unescape(text)
    return _WS_RE.sub(" ", text).strip() or None


def money(value: object) -> str | None:
    """Canonical decimal string, 2 places; never float."""
    if value is None or value == "":
        return None
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return format(amount.quantize(Decimal("0.01")), "f")


def number_text(value: object) -> str | None:
    if value is None or value == "":
        return None
    return str(value).strip()

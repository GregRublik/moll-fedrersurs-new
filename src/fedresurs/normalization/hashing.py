from __future__ import annotations

import hashlib
import json
from typing import Any


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def content_hash(normalized: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_json(normalized).encode("utf-8")).hexdigest()

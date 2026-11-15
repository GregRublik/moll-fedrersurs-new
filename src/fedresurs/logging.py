from __future__ import annotations

import json
import logging
import re
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from config import settings

_REDACT = re.compile(r"(/rest/\d+/)[^/\s\"']+")


class RedactFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = _REDACT.sub(r"\1***", record.msg)
        return True


class JsonFormatter(logging.Formatter):
    EXTRA = (
        "run_id",
        "window_id",
        "stage",
        "entity_type",
        "entity_key",
        "endpoint",
        "attempt",
        "duration_ms",
        "http_status",
        "outcome",
        "error_code",
    )

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for key in self.EXTRA:
            value = getattr(record, key, None)
            if value is not None:
                payload[key] = value
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def setup_logging(level: str | None = None, log_dir: Path | None = None) -> None:
    level = (level or settings.app.log_level).upper()
    log_dir = Path(log_dir or settings.app.log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)

    formatter = JsonFormatter()
    redact = RedactFilter()

    stream = logging.StreamHandler(sys.stdout)
    stream.setFormatter(formatter)

    file_handler = RotatingFileHandler(
        log_dir / "fedresurs.jsonl", maxBytes=20_000_000, backupCount=5, encoding="utf-8"
    )
    file_handler.setFormatter(formatter)

    root = logging.getLogger()
    root.handlers.clear()
    for handler in (stream, file_handler):
        handler.addFilter(redact)
        root.addHandler(handler)
    root.setLevel(level)

from __future__ import annotations

from enum import StrEnum


class EntityType(StrEnum):
    BIDDING = "bidding"
    LOT = "lot"
    MESSAGE = "message"


class Outcome(StrEnum):
    OK = "ok"
    NO_DATA = "no_data"
    TRUNCATED = "truncated"
    HTTP_ERROR = "http_error"
    QRATOR_BLOCK = "qrator_block"
    PARSE_ERROR = "parse_error"
    INCOMPLETE = "incomplete"


class WindowKind(StrEnum):
    FEED = "feed"
    SWEEP = "sweep"
    REFRESH = "refresh"
    LATE_SCAN = "late_scan"


class WindowStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    INCOMPLETE = "incomplete"
    SPLIT = "split"
    FAILED = "failed"


class SyncStatus(StrEnum):
    PENDING = "pending"
    SYNCED = "synced"
    FAILED = "failed"
    SKIPPED = "skipped"


class SyncOperation(StrEnum):
    CREATE = "create"
    UPDATE = "update"
    CLOSE = "close"
    NOOP = "noop"


class SyncJobStatus(StrEnum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    DONE = "done"
    FAILED = "failed"
    SKIPPED = "skipped"


class SourceState(StrEnum):
    ACTIVE = "active"
    MISSING = "missing"
    CLOSED = "closed"


class FilterDecision(StrEnum):
    INCLUDE = "include"
    EXCLUDE = "exclude"
    REVIEW = "review"


class ClassificationSource(StrEnum):
    CLASSIFIER = "classifier"
    TEXT = "text"
    SHOWCASE = "showcase"
    OVERRIDE = "override"
    REVIEW = "review"
    UNMATCHED = "unmatched"


class ErrorType(StrEnum):
    SOURCE_BLOCKED = "source_blocked"
    SOURCE_HTTP_ERROR = "source_http_error"
    SOURCE_PARSE_ERROR = "source_parse_error"
    TRUNCATED_WINDOW = "truncated_window"
    INCOMPLETE_WINDOW = "incomplete_window"
    BITRIX_TRANSPORT_ERROR = "bitrix_transport_error"
    BITRIX_API_ERROR = "bitrix_api_error"
    VALIDATION_ERROR = "validation_error"
    PROFILE_LOCKED = "profile_locked"
    MANUAL_INTERVENTION_REQUIRED = "manual_intervention_required"


XML_ID_PREFIX = {
    EntityType.BIDDING: "fdrs:1078:",
    EntityType.LOT: "fdrs:1120:",
}

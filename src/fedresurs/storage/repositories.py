from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

import aiosqlite

from fedresurs.storage.db import Database
from fedresurs.timeutil import now_msk


def now_iso() -> str:
    return now_msk().isoformat()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def diff_json(old_text: str | None, new_text: str | None) -> list[str]:
    try:
        old = json.loads(old_text) if old_text else {}
    except json.JSONDecodeError:
        old = {}
    try:
        new = json.loads(new_text) if new_text else {}
    except json.JSONDecodeError:
        new = {}
    if not isinstance(old, dict) or not isinstance(new, dict):
        return []
    return sorted(key for key in old.keys() | new.keys() if old.get(key) != new.get(key))


@dataclass(slots=True)
class UpsertResult:
    entity_key: str
    is_new: bool
    changed: bool
    changed_fields: list[str] = field(default_factory=list)


BIDDING_COLUMNS = [
    "guid",
    "number",
    "trade_type_code",
    "trade_type_name",
    "status",
    "price_form",
    "is_rebidding",
    "debtor_name",
    "debtor_inn",
    "debtor_ogrn",
    "debtor_region",
    "organizer_name",
    "organizer_inn",
    "manager_name",
    "manager_inn",
    "manager_snils",
    "manager_address",
    "manager_email",
    "sro_name",
    "sro_inn",
    "sro_ogrn",
    "sro_address",
    "application_rules",
    "additional_text",
    "announcement_text",
    "publisher_json",
    "case_number",
    "court",
    "platform_name",
    "platform_url",
    "trade_start_at",
    "trade_end_at",
    "application_start_at",
    "application_end_at",
    "published_at",
    "updated_at_source",
    "source_url",
    "message_url",
    "is_candidate",
    "match_score",
    "match_reasons_json",
    "filter_version",
    "classification_source",
    "source_state",
    "content_hash",
    "normalized_json",
]

LOT_COLUMNS = [
    "trade_guid",
    "lot_number",
    "ordinal",
    "lot_key",
    "status_code",
    "status_name",
    "start_price",
    "current_price",
    "min_price",
    "deposit",
    "advance_percent",
    "price_reduction_json",
    "classifiers_json",
    "trade_object_html",
    "trade_object_text",
    "sale_agreement",
    "payment_info",
    "is_public_offer",
    "is_candidate",
    "match_score",
    "match_reasons_json",
    "classification_source",
    "content_hash",
    "normalized_json",
]

BIDDING_DEFAULTS = {"is_rebidding": 0, "is_candidate": 0, "source_state": "active"}
LOT_DEFAULTS = {"is_public_offer": 0, "is_candidate": 0}
MESSAGE_DEFAULTS = {"is_annulled": 0, "is_locked": 0}


def _values_for(data: dict[str, Any], columns: list[str], defaults: dict[str, Any]) -> list[Any]:
    return [data.get(col, defaults.get(col)) for col in columns]


MESSAGE_COLUMNS = [
    "guid",
    "trade_guid",
    "event_time",
    "number",
    "date_publish",
    "type",
    "is_annulled",
    "is_locked",
    "text_html",
    "text_plain",
    "files_json",
    "content_hash",
]


class _BaseRepo:
    def __init__(self, db: Database) -> None:
        self.db = db

    async def _record_version(
        self,
        entity_type: str,
        entity_key: str,
        content_hash: str,
        changed_fields: list[str],
        snapshot: str | None,
        fetched_at: str,
    ) -> None:
        row = await self.db.fetchone(
            "SELECT COALESCE(MAX(version_no), 0) + 1 AS next FROM entity_versions "
            "WHERE entity_type = ? AND entity_key = ?",
            (entity_type, entity_key),
        )
        next_no = row["next"] if row else 1
        await self.db.execute(
            """
            INSERT OR IGNORE INTO entity_versions
                (entity_type, entity_key, version_no, content_hash, changed_fields_json, snapshot_json, fetched_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                entity_type,
                entity_key,
                next_no,
                content_hash,
                json.dumps(changed_fields, ensure_ascii=False),
                snapshot,
                fetched_at,
            ),
        )


class BiddingRepo(_BaseRepo):
    async def get(self, guid: str) -> aiosqlite.Row | None:
        return await self.db.fetchone("SELECT * FROM biddings WHERE guid = ?", (guid,))

    async def upsert(self, data: dict[str, Any]) -> UpsertResult:
        guid = data["guid"]
        now = now_iso()
        async with self.db.transaction():
            existing = await self.db.fetchone(
                "SELECT content_hash, normalized_json FROM biddings WHERE guid = ?", (guid,)
            )
            if existing is None:
                columns = [*BIDDING_COLUMNS, "first_seen_at", "last_seen_at", "sync_status"]
                values = _values_for(data, BIDDING_COLUMNS, BIDDING_DEFAULTS) + [now, now, "pending"]
                await self.db.execute(
                    f"INSERT INTO biddings ({', '.join(columns)}) VALUES ({', '.join('?' for _ in columns)})",
                    values,
                )
                await self._record_version(
                    "bidding", guid, data["content_hash"], sorted(data), data.get("normalized_json"), now
                )
                return UpsertResult(guid, True, True, sorted(data))

            if existing["content_hash"] == data["content_hash"]:
                await self.db.execute("UPDATE biddings SET last_seen_at = ? WHERE guid = ?", (now, guid))
                return UpsertResult(guid, False, False, [])

            changed = diff_json(existing["normalized_json"], data.get("normalized_json"))
            update_columns = [col for col in BIDDING_COLUMNS if col != "guid"]
            assignments = ", ".join(f"{col} = ?" for col in update_columns)
            values = _values_for(data, update_columns, BIDDING_DEFAULTS) + [now, guid]
            await self.db.execute(
                f"UPDATE biddings SET {assignments}, last_seen_at = ?, sync_status = 'pending' WHERE guid = ?",
                values,
            )
            await self._record_version(
                "bidding", guid, data["content_hash"], changed, data.get("normalized_json"), now
            )
            return UpsertResult(guid, False, True, changed)

    async def mark_details_fetched(self, guid: str) -> None:
        await self.db.execute("UPDATE biddings SET details_fetched_at = ? WHERE guid = ?", (now_iso(), guid))

    async def mark_lots_fetched(self, guid: str) -> None:
        await self.db.execute("UPDATE biddings SET lots_fetched_at = ? WHERE guid = ?", (now_iso(), guid))

    async def mark_messages_fetched(self, guid: str) -> None:
        await self.db.execute("UPDATE biddings SET messages_fetched_at = ? WHERE guid = ?", (now_iso(), guid))

    async def list_candidates(self, limit: int = 500) -> list[aiosqlite.Row]:
        return await self.db.fetchall(
            """
            SELECT * FROM biddings
            WHERE is_candidate = 1
              AND (details_fetched_at IS NULL OR lots_fetched_at IS NULL
                   OR messages_fetched_at IS NULL)
            ORDER BY published_at DESC LIMIT ?
            """,
            (limit,),
        )

    async def list_for_sync(
        self,
        limit: int = 500,
        *,
        guid: str | None = None,
        include_synced: bool = False,
    ) -> list[aiosqlite.Row]:
        clauses: list[str] = []
        params: list[Any] = []
        if not include_synced:
            clauses.append("sync_status = 'pending'")
        if guid is not None:
            clauses.append("guid = ?")
            params.append(guid)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(limit)
        return await self.db.fetchall(
            f"SELECT * FROM biddings {where} ORDER BY last_seen_at LIMIT ?",
            params,
        )

    async def set_synced(self, guid: str, bitrix_id: int, synced_hash: str) -> None:
        await self.db.execute(
            "UPDATE biddings SET sync_status = 'synced', bitrix_id = ?, bitrix_synced_hash = ?, "
            "bitrix_synced_at = ?, sync_error = NULL WHERE guid = ?",
            (bitrix_id, synced_hash, now_iso(), guid),
        )

    async def set_sync_failed(self, guid: str, error: str) -> None:
        await self.db.execute(
            "UPDATE biddings SET sync_status = 'failed', sync_error = ?, "
            "sync_attempts = sync_attempts + 1 WHERE guid = ?",
            (error[:2000], guid),
        )


class LotRepo(_BaseRepo):
    async def get(self, lot_key: str) -> aiosqlite.Row | None:
        return await self.db.fetchone("SELECT * FROM lots WHERE lot_key = ?", (lot_key,))

    async def list_by_trade(self, trade_guid: str) -> list[aiosqlite.Row]:
        return await self.db.fetchall(
            "SELECT * FROM lots WHERE trade_guid = ? ORDER BY ordinal, lot_number", (trade_guid,)
        )

    async def upsert(self, data: dict[str, Any]) -> UpsertResult:
        lot_key = data["lot_key"]
        now = now_iso()
        async with self.db.transaction():
            existing = await self.db.fetchone(
                "SELECT content_hash, normalized_json FROM lots WHERE lot_key = ?", (lot_key,)
            )
            if existing is None:
                columns = [*LOT_COLUMNS, "first_seen_at", "last_seen_at", "sync_status"]
                values = _values_for(data, LOT_COLUMNS, LOT_DEFAULTS) + [now, now, "pending"]
                await self.db.execute(
                    f"INSERT INTO lots ({', '.join(columns)}) VALUES ({', '.join('?' for _ in columns)})",
                    values,
                )
                await self._record_version(
                    "lot", lot_key, data["content_hash"], sorted(data), data.get("normalized_json"), now
                )
                return UpsertResult(lot_key, True, True, sorted(data))

            if existing["content_hash"] == data["content_hash"]:
                await self.db.execute("UPDATE lots SET last_seen_at = ? WHERE lot_key = ?", (now, lot_key))
                return UpsertResult(lot_key, False, False, [])

            changed = diff_json(existing["normalized_json"], data.get("normalized_json"))
            update_columns = [col for col in LOT_COLUMNS if col != "lot_key"]
            assignments = ", ".join(f"{col} = ?" for col in update_columns)
            values = _values_for(data, update_columns, LOT_DEFAULTS) + [now, lot_key]
            await self.db.execute(
                f"UPDATE lots SET {assignments}, last_seen_at = ?, sync_status = 'pending' WHERE lot_key = ?",
                values,
            )
            await self._record_version(
                "lot", lot_key, data["content_hash"], changed, data.get("normalized_json"), now
            )
            return UpsertResult(lot_key, False, True, changed)

    async def mark_missing(self, lot_key: str) -> None:
        await self.db.execute(
            "UPDATE lots SET is_deleted_at_source = 1, missing_since = ? WHERE lot_key = ?",
            (now_iso(), lot_key),
        )

    async def list_for_sync(
        self,
        limit: int = 500,
        *,
        trade_guid: str | None = None,
        include_synced: bool = False,
    ) -> list[aiosqlite.Row]:
        clauses: list[str] = []
        params: list[Any] = []
        if not include_synced:
            clauses.append("sync_status = 'pending'")
        if trade_guid is not None:
            clauses.append("trade_guid = ?")
            params.append(trade_guid)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(limit)
        return await self.db.fetchall(
            f"SELECT * FROM lots {where} ORDER BY first_seen_at LIMIT ?",
            params,
        )

    async def set_synced(self, lot_key: str, bitrix_id: int, synced_hash: str) -> None:
        await self.db.execute(
            "UPDATE lots SET sync_status = 'synced', bitrix_id = ?, bitrix_synced_hash = ?, "
            "bitrix_synced_at = ?, sync_error = NULL WHERE lot_key = ?",
            (bitrix_id, synced_hash, now_iso(), lot_key),
        )

    async def set_sync_failed(self, lot_key: str, error: str) -> None:
        await self.db.execute(
            "UPDATE lots SET sync_status = 'failed', sync_error = ?, "
            "sync_attempts = sync_attempts + 1 WHERE lot_key = ?",
            (error[:2000], lot_key),
        )


class MessageRepo(_BaseRepo):
    async def upsert(self, data: dict[str, Any]) -> UpsertResult:
        guid = data["guid"]
        now = now_iso()
        async with self.db.transaction():
            existing = await self.db.fetchone(
                "SELECT content_hash FROM messages WHERE guid = ?", (guid,)
            )
            if existing is None:
                columns = [*MESSAGE_COLUMNS, "first_seen_at"]
                values = _values_for(data, MESSAGE_COLUMNS, MESSAGE_DEFAULTS) + [now]
                await self.db.execute(
                    f"INSERT INTO messages ({', '.join(columns)}) VALUES ({', '.join('?' for _ in columns)})",
                    values,
                )
                return UpsertResult(guid, True, True, sorted(data))
            if existing["content_hash"] == data["content_hash"]:
                return UpsertResult(guid, False, False, [])
            update_columns = [col for col in MESSAGE_COLUMNS if col != "guid"]
            assignments = ", ".join(f"{col} = ?" for col in update_columns)
            values = _values_for(data, update_columns, MESSAGE_DEFAULTS) + [guid]
            await self.db.execute(f"UPDATE messages SET {assignments} WHERE guid = ?", values)
            return UpsertResult(guid, False, True, [])


class WindowRepo:
    def __init__(self, db: Database) -> None:
        self.db = db

    async def get_or_create(
        self,
        *,
        kind: str,
        date_from: str,
        date_to: str,
        filter_hash: str,
        run_id: int | None = None,
        trade_type: str | None = None,
        search_string: str | None = None,
        parent_window_id: int | None = None,
        depth: int = 0,
    ) -> int:
        async with self.db.transaction():
            await self.db.execute(
                """
                INSERT OR IGNORE INTO collection_windows
                    (run_id, kind, date_from, date_to, filter_hash, trade_type, search_string,
                     parent_window_id, depth, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending')
                """,
                (run_id, kind, date_from, date_to, filter_hash, trade_type, search_string,
                 parent_window_id, depth),
            )
            row = await self.db.fetchone(
                """
                SELECT id FROM collection_windows
                WHERE kind = ? AND date_from = ? AND date_to = ? AND filter_hash = ?
                  AND COALESCE(parent_window_id, 0) = COALESCE(?, 0)
                """,
                (kind, date_from, date_to, filter_hash, parent_window_id),
            )
            if row is None:
                raise RuntimeError("failed to create or find collection window")
            return int(row["id"])

    async def mark_running(self, window_id: int) -> None:
        await self.db.execute(
            "UPDATE collection_windows SET status = 'running', started_at = ?, "
            "attempts = attempts + 1 WHERE id = ?",
            (now_iso(), window_id),
        )

    async def finish(
        self,
        window_id: int,
        *,
        status: str,
        outcome: str | None,
        found: int | None,
        collected: int,
        pages: int,
        last_offset: int,
        error_message: str | None = None,
    ) -> None:
        await self.db.execute(
            """
            UPDATE collection_windows
            SET status = ?, outcome = ?, found = ?, distinct_collected = ?, pages_loaded = ?,
                last_offset = ?, error_message = ?, finished_at = ?
            WHERE id = ?
            """,
            (status, outcome, found, collected, pages, last_offset, error_message, now_iso(), window_id),
        )

    async def add_sighting(self, window_id: int, guid: str, offset: int) -> None:
        await self.db.execute(
            "INSERT OR IGNORE INTO window_sightings(window_id, guid, offset_seen, seen_at) "
            "VALUES (?, ?, ?, ?)",
            (window_id, guid, offset, now_iso()),
        )

    async def pending(self, limit: int = 20) -> list[aiosqlite.Row]:
        return await self.db.fetchall(
            "SELECT * FROM collection_windows WHERE status IN ('pending', 'incomplete') "
            "ORDER BY id LIMIT ?",
            (limit,),
        )

    async def count_by_status(self) -> list[aiosqlite.Row]:
        return await self.db.fetchall(
            "SELECT status, outcome, COUNT(*) AS cnt FROM collection_windows GROUP BY status, outcome"
        )


class RawRepo:
    def __init__(self, db: Database) -> None:
        self.db = db

    async def save(
        self,
        *,
        entity_type: str,
        entity_key: str,
        endpoint: str,
        payload: Any,
        http_status: int | None,
        run_id: int | None = None,
        is_error: bool = False,
    ) -> None:
        text = payload if isinstance(payload, str) else canonical_json(payload)
        content_hash = sha256_text(text)
        await self.db.execute(
            """
            INSERT OR IGNORE INTO raw_payloads
                (entity_type, entity_key, endpoint, run_id, fetched_at, http_status,
                 content_hash, payload, payload_bytes, is_error)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (entity_type, entity_key, endpoint, run_id, now_iso(), http_status,
             content_hash, text, len(text.encode("utf-8")), int(is_error)),
        )


class FetchLogRepo:
    def __init__(self, db: Database) -> None:
        self.db = db

    async def log(
        self,
        *,
        endpoint: str,
        started_at: str,
        duration_ms: int,
        http_status: int | None,
        outcome: str,
        attempt: int = 1,
        run_id: int | None = None,
        window_id: int | None = None,
        entity_type: str | None = None,
        entity_key: str | None = None,
        error_code: str | None = None,
        size: int | None = None,
    ) -> None:
        await self.db.execute(
            """
            INSERT INTO fetch_log
                (run_id, window_id, entity_type, entity_key, endpoint, started_at, duration_ms,
                 attempt, http_status, outcome, error_code, bytes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (run_id, window_id, entity_type, entity_key, endpoint, started_at, duration_ms,
             attempt, http_status, outcome, error_code, size),
        )


class ErrorRepo:
    def __init__(self, db: Database) -> None:
        self.db = db

    async def add(
        self,
        *,
        error_type: str,
        message: str,
        stage: str | None = None,
        error_code: str | None = None,
        run_id: int | None = None,
        window_id: int | None = None,
        entity_type: str | None = None,
        entity_key: str | None = None,
        context: Any = None,
    ) -> int:
        cursor = await self.db.execute(
            """
            INSERT INTO errors
                (run_id, window_id, stage, entity_type, entity_key, error_type,
                 error_code, message, context_json, occurred_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (run_id, window_id, stage, entity_type, entity_key, error_type,
             error_code, message[:4000], canonical_json(context) if context is not None else None,
             now_iso()),
        )
        return int(cursor.lastrowid or 0)

    async def unresolved(self, limit: int = 100) -> list[aiosqlite.Row]:
        return await self.db.fetchall(
            "SELECT * FROM errors WHERE resolved_at IS NULL ORDER BY id DESC LIMIT ?", (limit,)
        )


class SyncJobRepo:
    def __init__(self, db: Database) -> None:
        self.db = db

    async def enqueue(
        self,
        *,
        entity_type: str,
        entity_key: str,
        operation: str,
        payload_hash: str,
        depends_on_job_id: int | None = None,
    ) -> int:
        now = now_iso()
        async with self.db.transaction():
            await self.db.execute(
                """
                INSERT OR IGNORE INTO sync_jobs
                    (entity_type, entity_key, operation, payload_hash, depends_on_job_id,
                     status, attempts, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, 'pending', 0, ?, ?)
                """,
                (entity_type, entity_key, operation, payload_hash, depends_on_job_id, now, now),
            )
            row = await self.db.fetchone(
                "SELECT id FROM sync_jobs WHERE entity_type = ? AND entity_key = ? "
                "AND operation = ? AND payload_hash = ?",
                (entity_type, entity_key, operation, payload_hash),
            )
            if row is None:
                raise RuntimeError("failed to enqueue sync job")
            return int(row["id"])

    async def claim_ready(self, limit: int = 50) -> list[aiosqlite.Row]:
        now = now_iso()
        async with self.db.transaction():
            rows = await self.db.fetchall(
                """
                SELECT * FROM sync_jobs
                WHERE status = 'pending'
                  AND (next_attempt_at IS NULL OR next_attempt_at <= ?)
                  AND (depends_on_job_id IS NULL OR depends_on_job_id IN
                       (SELECT id FROM sync_jobs WHERE status = 'done'))
                ORDER BY id LIMIT ?
                """,
                (now, limit),
            )
            for row in rows:
                await self.db.execute(
                    "UPDATE sync_jobs SET status = 'in_progress', attempts = attempts + 1, "
                    "updated_at = ? WHERE id = ?",
                    (now, row["id"]),
                )
            return rows

    async def complete(self, job_id: int, bitrix_id: int | None) -> None:
        now = now_iso()
        await self.db.execute(
            "UPDATE sync_jobs SET status = 'done', bitrix_id = ?, finished_at = ?, "
            "updated_at = ?, last_error = NULL WHERE id = ?",
            (bitrix_id, now, now, job_id),
        )

    async def fail(self, job_id: int, error: str, retry_at: str | None) -> None:
        now = now_iso()
        status = "pending" if retry_at else "failed"
        await self.db.execute(
            "UPDATE sync_jobs SET status = ?, next_attempt_at = ?, last_error = ?, "
            "updated_at = ?, finished_at = CASE WHEN ? = 'failed' THEN ? ELSE finished_at END "
            "WHERE id = ?",
            (status, retry_at, error[:4000], now, status, now, job_id),
        )


class BitrixMapRepo:
    def __init__(self, db: Database) -> None:
        self.db = db

    async def set(
        self, *, entity_type: str, entity_key: str, bitrix_entity_type_id: int,
        bitrix_id: int, xml_id: str,
    ) -> None:
        now = now_iso()
        await self.db.execute(
            """
            INSERT INTO bitrix_id_map
                (entity_type, entity_key, bitrix_entity_type_id, bitrix_id, xml_id, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(entity_type, entity_key) DO UPDATE SET
                bitrix_entity_type_id = excluded.bitrix_entity_type_id,
                bitrix_id = excluded.bitrix_id,
                xml_id = excluded.xml_id,
                updated_at = excluded.updated_at
            """,
            (entity_type, entity_key, bitrix_entity_type_id, bitrix_id, xml_id, now, now),
        )

    async def get(self, entity_type: str, entity_key: str) -> aiosqlite.Row | None:
        return await self.db.fetchone(
            "SELECT * FROM bitrix_id_map WHERE entity_type = ? AND entity_key = ?",
            (entity_type, entity_key),
        )


class RunRepo:
    def __init__(self, db: Database) -> None:
        self.db = db

    async def start(self, run_type: str, mode: str | None = None, config_hash: str | None = None) -> int:
        cursor = await self.db.execute(
            "INSERT INTO runs(run_type, mode, started_at, status, heartbeat_at, config_hash) "
            "VALUES (?, ?, ?, 'running', ?, ?)",
            (run_type, mode, now_iso(), now_iso(), config_hash),
        )
        return int(cursor.lastrowid or 0)

    async def heartbeat(self, run_id: int) -> None:
        await self.db.execute("UPDATE runs SET heartbeat_at = ? WHERE id = ?", (now_iso(), run_id))

    async def finish(self, run_id: int, stats: Any = None, error_count: int = 0) -> None:
        await self.db.execute(
            "UPDATE runs SET status = 'done', finished_at = ?, stats_json = ?, error_count = ? WHERE id = ?",
            (now_iso(), canonical_json(stats) if stats is not None else None, error_count, run_id),
        )


class LockRepo:
    def __init__(self, db: Database) -> None:
        self.db = db

    async def acquire(self, name: str, owner: str, ttl_seconds: int = 3600) -> bool:
        now = now_msk()
        expires = now + timedelta(seconds=ttl_seconds)
        async with self.db.transaction():
            row = await self.db.fetchone("SELECT * FROM job_locks WHERE name = ?", (name,))
            if row is not None and row["expires_at"] > now.isoformat():
                return False
            await self.db.execute(
                """
                INSERT INTO job_locks(name, owner, acquired_at, expires_at, heartbeat_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(name) DO UPDATE SET
                    owner = excluded.owner,
                    acquired_at = excluded.acquired_at,
                    expires_at = excluded.expires_at,
                    heartbeat_at = excluded.heartbeat_at
                """,
                (name, owner, now.isoformat(), expires.isoformat(), now.isoformat()),
            )
            return True

    async def heartbeat(self, name: str, owner: str, ttl_seconds: int = 3600) -> None:
        now = now_msk()
        expires = now + timedelta(seconds=ttl_seconds)
        await self.db.execute(
            "UPDATE job_locks SET heartbeat_at = ?, expires_at = ? WHERE name = ? AND owner = ?",
            (now.isoformat(), expires.isoformat(), name, owner),
        )

    async def release(self, name: str, owner: str) -> None:
        await self.db.execute("DELETE FROM job_locks WHERE name = ? AND owner = ?", (name, owner))

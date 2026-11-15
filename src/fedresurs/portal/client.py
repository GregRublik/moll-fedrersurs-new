from __future__ import annotations

import asyncio
import random
import time
from typing import Any

from fedresurs.browser.errors import SessionExpiredError
from fedresurs.browser.session import PortalSession
from fedresurs.browser.transport import PageTransport
from fedresurs.portal.parsers import PortalParseError, parse_json
from fedresurs.storage.db import Database
from fedresurs.storage.repositories import FetchLogRepo, now_iso


class PortalHttpError(Exception):
    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


class PortalBlockedError(PortalHttpError):
    pass


class PortalTransportError(PortalHttpError):
    pass


class PortalClient:
    """Paced, retrying client for the portal's internal JSON API."""

    def __init__(
        self,
        transport: PageTransport,
        db: Database,
        session: PortalSession | None = None,
        *,
        min_interval_ms: int = 1500,
        jitter_ms: int = 800,
        max_retries: int = 5,
        block_cooldown_s: float = 60.0,
        backoff_base_s: float = 2.0,
        run_id: int | None = None,
    ) -> None:
        self.transport = transport
        self.db = db
        self.session = session
        self.min_interval_ms = min_interval_ms
        self.jitter_ms = jitter_ms
        self.max_retries = max(1, max_retries)
        self.block_cooldown_s = block_cooldown_s
        self.backoff_base_s = backoff_base_s
        self.run_id = run_id
        self.fetch_log = FetchLogRepo(db)
        self.request_count = 0
        self._next_at = 0.0

    async def _pace(self) -> None:
        now = time.monotonic()
        if self._next_at > now:
            await asyncio.sleep(self._next_at - now)
        interval_ms = self.min_interval_ms + random.uniform(0, self.jitter_ms)
        self._next_at = time.monotonic() + interval_ms / 1000.0

    async def _log(
        self,
        *,
        path: str,
        started_at: str,
        duration_ms: int,
        attempt: int,
        status: int | None,
        outcome: str,
        window_id: int | None,
        entity_type: str | None,
        entity_key: str | None,
        error_code: str | None = None,
        size: int | None = None,
    ) -> None:
        try:
            await self.fetch_log.log(
                endpoint=path,
                started_at=started_at,
                duration_ms=duration_ms,
                http_status=status,
                outcome=outcome,
                attempt=attempt,
                run_id=self.run_id,
                window_id=window_id,
                entity_type=entity_type,
                entity_key=entity_key,
                error_code=error_code,
                size=size,
            )
        except Exception:  # noqa: BLE001 — logging must never break collection
            pass

    async def get(
        self,
        path: str,
        *,
        window_id: int | None = None,
        entity_type: str | None = None,
        entity_key: str | None = None,
    ) -> dict[str, Any] | list[Any]:
        last_error: Exception | None = None

        for attempt in range(1, self.max_retries + 1):
            await self._pace()
            started_at = now_iso()
            started = time.monotonic()
            self.request_count += 1

            try:
                status, text = await self.transport.get_text(path)
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                await self._log(
                    path=path, started_at=started_at,
                    duration_ms=int((time.monotonic() - started) * 1000),
                    attempt=attempt, status=None, outcome="transport_error",
                    window_id=window_id, entity_type=entity_type, entity_key=entity_key,
                    error_code=type(exc).__name__,
                )
                await asyncio.sleep(self.backoff_base_s * attempt)
                continue

            duration_ms = int((time.monotonic() - started) * 1000)

            if status == 200:
                try:
                    payload = parse_json(text)
                except PortalParseError as exc:
                    last_error = exc
                    await self._log(
                        path=path, started_at=started_at, duration_ms=duration_ms,
                        attempt=attempt, status=status, outcome="parse_error",
                        window_id=window_id, entity_type=entity_type, entity_key=entity_key,
                        error_code="PortalParseError", size=len(text),
                    )
                    await asyncio.sleep(self.backoff_base_s * attempt)
                    continue

                await self._log(
                    path=path, started_at=started_at, duration_ms=duration_ms,
                    attempt=attempt, status=status, outcome="ok",
                    window_id=window_id, entity_type=entity_type, entity_key=entity_key,
                    size=len(text),
                )
                return payload

            if status in (401, 403):
                await self._log(
                    path=path, started_at=started_at, duration_ms=duration_ms,
                    attempt=attempt, status=status, outcome="session_expired",
                    window_id=window_id, entity_type=entity_type, entity_key=entity_key,
                )
                last_error = SessionExpiredError(f"HTTP {status}")
                if self.session is not None and attempt < self.max_retries:
                    await self.session.refresh()
                    continue
                raise PortalHttpError(f"portal rejected the session (HTTP {status})", status)

            if status == 451:
                await self._log(
                    path=path, started_at=started_at, duration_ms=duration_ms,
                    attempt=attempt, status=status, outcome="qrator_block",
                    window_id=window_id, entity_type=entity_type, entity_key=entity_key,
                )
                last_error = PortalBlockedError("HTTP 451 from QRATOR", status)
                if attempt < self.max_retries:
                    # 451 is deterministic for non-SPA request shapes (e.g. unusual
                    # page sizes); refreshing the session does not help and is costly.
                    await asyncio.sleep(self.block_cooldown_s * attempt)
                    continue
                raise PortalBlockedError("portal keeps returning HTTP 451 (QRATOR)", status)

            if 500 <= status < 600:
                await self._log(
                    path=path, started_at=started_at, duration_ms=duration_ms,
                    attempt=attempt, status=status, outcome="http_error",
                    window_id=window_id, entity_type=entity_type, entity_key=entity_key,
                )
                last_error = PortalHttpError(f"HTTP {status}", status)
                await asyncio.sleep(self.backoff_base_s * attempt)
                continue

            await self._log(
                path=path, started_at=started_at, duration_ms=duration_ms,
                attempt=attempt, status=status, outcome="http_error",
                window_id=window_id, entity_type=entity_type, entity_key=entity_key,
            )
            raise PortalHttpError(f"unexpected HTTP {status}", status)

        raise PortalTransportError(f"portal request failed after {self.max_retries} attempts: {last_error}")

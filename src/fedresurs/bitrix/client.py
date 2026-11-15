from __future__ import annotations

import asyncio
import time
from typing import Any

import aiohttp

from fedresurs.bitrix.errors import AUTH_ERRORS, TRANSIENT_ERRORS, BitrixApiError


class BitrixClient:
    """Thin Bitrix24 REST client with pacing, retries and typed errors."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        webhook_base: str,
        *,
        rps: float = 1.8,
        max_retries: int = 3,
        backoff_s: float = 1.5,
    ) -> None:
        self.session = session
        self.webhook_base = webhook_base.rstrip("/")
        self.interval_s = 1.0 / max(rps, 0.1)
        self.max_retries = max(1, max_retries)
        self.backoff_s = backoff_s
        self._next_at = 0.0
        self.request_count = 0

    def _url(self, method: str) -> str:
        return f"{self.webhook_base}/{method}.json"

    async def _pace(self) -> None:
        now = time.monotonic()
        if self._next_at > now:
            await asyncio.sleep(self._next_at - now)
        self._next_at = time.monotonic() + self.interval_s

    async def call(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        last_error: BitrixApiError | None = None

        for attempt in range(1, self.max_retries + 1):
            await self._pace()
            self.request_count += 1
            try:
                async with self.session.post(
                    self._url(method),
                    json=params or {},
                    timeout=aiohttp.ClientTimeout(total=60),
                ) as response:
                    status = response.status
                    try:
                        payload = await response.json(content_type=None)
                    except Exception:  # noqa: BLE001
                        text = await response.text()
                        raise BitrixApiError(method, "NON_JSON", text[:300], status)

                if isinstance(payload, dict) and payload.get("error"):
                    code = str(payload.get("error"))
                    error = BitrixApiError(
                        method, code, payload.get("error_description"), status
                    )
                    if code in AUTH_ERRORS:
                        raise error
                    if code in TRANSIENT_ERRORS and attempt < self.max_retries:
                        last_error = error
                        await asyncio.sleep(self.backoff_s * attempt)
                        continue
                    raise error

                if status >= 500 and attempt < self.max_retries:
                    last_error = BitrixApiError(method, "HTTP_5XX", None, status)
                    await asyncio.sleep(self.backoff_s * attempt)
                    continue

                if status >= 400:
                    raise BitrixApiError(method, "HTTP_ERROR", None, status)

                return payload

            except aiohttp.ClientError as exc:
                last_error = BitrixApiError(method, "TRANSPORT_ERROR", str(exc), None)
                if attempt < self.max_retries:
                    await asyncio.sleep(self.backoff_s * attempt)
                    continue
                raise last_error from exc

        raise last_error or BitrixApiError(method, "UNKNOWN", "request failed")

    async def batch(self, commands: dict[str, dict[str, Any]]) -> dict[str, Any]:
        return await self.call("batch", {"halt": 0, "cmd": commands})

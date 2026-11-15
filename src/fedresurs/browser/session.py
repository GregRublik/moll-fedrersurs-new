from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone
from typing import Any

from fedresurs.browser.base import BrowserHandle
from fedresurs.browser.errors import ChallengeTimeoutError, SessionExpiredError
from fedresurs.browser.transport import PageTransport


class PortalSession:
    """Keeps the Qrator session alive and refreshes it before expiry."""

    def __init__(
        self,
        handle: BrowserHandle,
        transport: PageTransport,
        base_url: str,
        *,
        refresh_before_minutes: int = 3,
        challenge_timeout_s: int = 90,
    ) -> None:
        self.handle = handle
        self.transport = transport
        self.base_url = base_url.rstrip("/")
        self.refresh_before_minutes = refresh_before_minutes
        self.challenge_timeout_s = challenge_timeout_s
        self.refresh_count = 0

    async def cookie_expires_at(self) -> datetime | None:
        cookies = await self.handle.context.cookies(self.base_url + "/")
        expiries = [
            datetime.fromtimestamp(cookie["expires"], tz=timezone.utc)
            for cookie in cookies
            if cookie["name"].startswith("qrator_") and cookie.get("expires", -1) > 0
        ]
        return min(expiries) if expiries else None

    async def probe(self) -> bool:
        try:
            status, _ = await self.transport.get_text("/backend/reference-book/bidding-types")
        except Exception:  # noqa: BLE001
            return False
        return status == 200

    async def ensure_alive(self) -> None:
        if self.handle.page.is_closed():
            raise SessionExpiredError("portal page is closed")

        expires = await self.cookie_expires_at()
        if expires is not None:
            remaining = (expires - datetime.now(timezone.utc)).total_seconds()
            if remaining < self.refresh_before_minutes * 60:
                await self.refresh()
                return

        if not await self.probe():
            await self.refresh()

    async def refresh(self) -> None:
        self.refresh_count += 1
        try:
            await self.handle.page.goto(
                self.base_url + "/", wait_until="domcontentloaded", timeout=120_000
            )
        except Exception:  # noqa: BLE001
            pass

        deadline = time.monotonic() + self.challenge_timeout_s
        while time.monotonic() < deadline:
            await asyncio.sleep(5)
            if await self.probe():
                return
        raise ChallengeTimeoutError(
            "Qrator challenge did not complete; manual intervention may be required"
        )

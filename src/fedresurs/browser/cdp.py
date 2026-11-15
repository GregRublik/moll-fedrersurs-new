from __future__ import annotations

from typing import Any

from playwright.async_api import async_playwright

from fedresurs.browser.base import BrowserHandle, LaunchConfig
from fedresurs.browser.errors import BrowserError


class CdpLauncher:
    """Attach to an existing Chrome over CDP (Windows host / operator machine)."""

    def __init__(self) -> None:
        self._pw: Any = None
        self._browser: Any = None

    async def start(self, config: LaunchConfig) -> BrowserHandle:
        if not config.cdp_url:
            raise BrowserError("PORTAL_CDP_URL is required for launch mode 'cdp'")
        self._pw = await async_playwright().start()
        self._browser = await self._pw.chromium.connect_over_cdp(config.cdp_url)
        context = self._browser.contexts[0] if self._browser.contexts else await self._browser.new_context()
        page = context.pages[0] if context.pages else await context.new_page()
        try:
            await page.goto(config.base_url, wait_until="domcontentloaded", timeout=90_000)
        except Exception:  # noqa: BLE001
            pass
        return BrowserHandle(context=context, page=page, mode="cdp")

    async def stop(self) -> None:
        if self._browser is not None:
            try:
                await self._browser.close()  # disconnects; does not kill the user's Chrome
            except Exception:  # noqa: BLE001
                pass
            self._browser = None
        if self._pw is not None:
            await self._pw.stop()
            self._pw = None

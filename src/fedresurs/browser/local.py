from __future__ import annotations

from typing import Any

from playwright.async_api import async_playwright

from fedresurs.browser.base import BrowserHandle, LaunchConfig


class LocalLauncher:
    """Headful Chromium with a persistent profile (desktop / Xvfb display)."""

    def __init__(self) -> None:
        self._pw: Any = None
        self._context: Any = None

    async def start(self, config: LaunchConfig) -> BrowserHandle:
        config.profile_dir.mkdir(parents=True, exist_ok=True)
        self._pw = await async_playwright().start()
        self._context = await self._pw.chromium.launch_persistent_context(
            user_data_dir=str(config.profile_dir),
            headless=config.headless,
            locale=config.locale,
            timezone_id=config.timezone_id,
            viewport={"width": config.viewport_width, "height": config.viewport_height},
            args=["--disable-blink-features=AutomationControlled", *config.extra_args],
        )
        page = self._context.pages[0] if self._context.pages else await self._context.new_page()
        await self._open_portal(page, config.base_url)
        return BrowserHandle(context=self._context, page=page, mode="local")

    @staticmethod
    async def _open_portal(page: Any, base_url: str) -> None:
        try:
            await page.goto(base_url, wait_until="domcontentloaded", timeout=90_000)
        except Exception:  # noqa: BLE001
            # The Qrator challenge may still be running; session.ensure_alive()
            # will retry and report a clear error if it never completes.
            pass

    async def stop(self) -> None:
        if self._context is not None:
            try:
                await self._context.close()
            except Exception:  # noqa: BLE001
                pass
            self._context = None
        if self._pw is not None:
            await self._pw.stop()
            self._pw = None

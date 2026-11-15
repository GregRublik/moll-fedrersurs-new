from __future__ import annotations

import os
import shutil
import subprocess
import time

from fedresurs.browser.base import BrowserHandle, LaunchConfig
from fedresurs.browser.errors import BrowserError
from fedresurs.browser.local import LocalLauncher


class XvfbLauncher:
    """Headful Chromium on a virtual X display (Linux servers)."""

    def __init__(self) -> None:
        self._local = LocalLauncher()
        self._proc: subprocess.Popen | None = None
        self._started_display = False

    async def start(self, config: LaunchConfig) -> BrowserHandle:
        self._ensure_display(config)
        return await self._local.start(config)

    def _ensure_display(self, config: LaunchConfig) -> None:
        if os.environ.get("DISPLAY"):
            return
        xvfb = shutil.which("Xvfb")
        if not xvfb:
            raise BrowserError(
                "DISPLAY is not set and Xvfb is not installed. "
                "Install xvfb (apt install xvfb) or use PORTAL_LAUNCH_MODE=cdp/local."
            )
        display = ":99"
        self._proc = subprocess.Popen(
            [
                xvfb,
                display,
                "-screen",
                "0",
                f"{config.viewport_width}x{config.viewport_height}x24",
                "-nolisten",
                "tcp",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        os.environ["DISPLAY"] = display
        self._started_display = True
        time.sleep(1.5)

    async def stop(self) -> None:
        await self._local.stop()
        if self._proc is not None:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._proc.kill()
            self._proc = None
        if self._started_display:
            os.environ.pop("DISPLAY", None)
            self._started_display = False

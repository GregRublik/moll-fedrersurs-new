from __future__ import annotations

from typing import Any

from fedresurs.browser.base import BrowserLauncher, LaunchConfig


def make_launcher(mode: str) -> BrowserLauncher:
    if mode == "local":
        from fedresurs.browser.local import LocalLauncher

        return LocalLauncher()
    if mode == "xvfb":
        from fedresurs.browser.xvfb import XvfbLauncher

        return XvfbLauncher()
    if mode == "cdp":
        from fedresurs.browser.cdp import CdpLauncher

        return CdpLauncher()
    raise ValueError(f"unsupported launch mode: {mode}")


def config_from_settings() -> LaunchConfig:
    from config import settings

    return LaunchConfig(
        base_url=settings.portal.base_url,
        profile_dir=settings.portal.profile_dir,
        mode=settings.portal.launch_mode,
        headless=settings.portal.headless,
        cdp_url=settings.portal.cdp_url,
    )

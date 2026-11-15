from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol


@dataclass(slots=True)
class LaunchConfig:
    base_url: str
    profile_dir: Path
    mode: str = "local"
    headless: bool = False
    cdp_url: str | None = None
    locale: str = "ru-RU"
    timezone_id: str = "Europe/Moscow"
    viewport_width: int = 1440
    viewport_height: int = 900
    extra_args: list[str] = field(default_factory=list)


@dataclass(slots=True)
class BrowserHandle:
    context: Any
    page: Any
    mode: str


class BrowserLauncher(Protocol):
    async def start(self, config: LaunchConfig) -> BrowserHandle: ...

    async def stop(self) -> None: ...

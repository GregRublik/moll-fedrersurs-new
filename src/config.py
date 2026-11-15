from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[1]


class BitrixSettings(BaseSettings):
    base_url: str
    key_202: str
    user_id: int

    entity_trade: int = Field(default=1078, alias="entity_trade")
    entity_lot: int = Field(default=1120, alias="entity_lot")
    category_trade: int = Field(default=179, alias="category_trade")
    category_lot: int = Field(default=180, alias="category_lot")

    rps: float = Field(default=1.8, alias="rps")
    batch_size: int = Field(default=50, alias="batch_size")
    write_enabled: bool = Field(default=False, alias="write_enabled")
    dry_run: bool = Field(default=True, alias="dry_run")
    default_assigned_by: int | None = Field(default=None, alias="default_assigned_by")

    model_config = SettingsConfigDict(
        env_prefix="BITRIX_", env_file=ROOT / ".env", extra="ignore", populate_by_name=True
    )

    @property
    def webhook_base(self) -> str:
        return f"{self.base_url.rstrip('/')}/rest/{self.user_id}/{self.key_202}"


class PortalSettings(BaseSettings):
    base_url: str = "https://fedresurs.ru"
    api_prefix: str = "/backend"
    launch_mode: Literal["local", "xvfb", "cdp"] = "local"
    cdp_url: str | None = None
    profile_dir: Path = ROOT / "var" / "browser-profile"
    headless: bool = False
    min_interval_ms: int = 1500
    jitter_ms: int = 800
    max_retries: int = 5
    session_ttl_min: int = 15
    daily_request_budget: int | None = None
    trade_url_template: str = "https://fedresurs.ru/biddings/{guid}"
    message_url_template: str = "https://fedresurs.ru/bankruptmessages/{guid}"

    model_config = SettingsConfigDict(env_prefix="PORTAL_", env_file=ROOT / ".env", extra="ignore")


class AppSettings(BaseSettings):
    db_path: Path = ROOT / "var" / "fedresurs.sqlite3"
    log_level: str = "INFO"
    log_dir: Path = ROOT / "var" / "log"
    filter_config_path: Path = ROOT / "config" / "filters.toml"
    field_map_path: Path = ROOT / "config" / "bitrix_fieldmap.toml"
    sync_mode: Literal["upsert", "fill_empty", "create_only"] = "upsert"
    sync_stage: bool = False
    schedule_enabled: bool = True

    model_config = SettingsConfigDict(env_file=ROOT / ".env", extra="ignore", populate_by_name=True)


class Settings(BaseSettings):
    bitrix: BitrixSettings = Field(default_factory=BitrixSettings)
    portal: PortalSettings = Field(default_factory=PortalSettings)
    app: AppSettings = Field(default_factory=AppSettings)


settings = Settings()

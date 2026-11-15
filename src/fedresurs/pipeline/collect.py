from __future__ import annotations

from datetime import timedelta
from typing import Any

from fedresurs.filtering.rules import FilterConfig
from fedresurs.normalization.bidding import TYPE_CODES_BY_NAME, type_codes_from_reference
from fedresurs.portal import endpoints
from fedresurs.portal.client import PortalClient
from fedresurs.portal.details import DetailsService
from fedresurs.portal.discovery import DiscoveryService, WindowResult
from fedresurs.storage.db import Database
from fedresurs.storage.repositories import (
    BiddingRepo,
    ErrorRepo,
    LotRepo,
    MessageRepo,
    RawRepo,
    WindowRepo,
)
from fedresurs.timeutil import now_msk


async def fetch_type_codes(client: PortalClient) -> dict[str, str]:
    try:
        payload: Any = await client.get(endpoints.bidding_types())
    except Exception:  # noqa: BLE001 — fallback map is enough for normalization
        return dict(TYPE_CODES_BY_NAME)
    records = payload if isinstance(payload, list) else payload.get("pageData", [])
    mapping = type_codes_from_reference(records)
    return mapping or dict(TYPE_CODES_BY_NAME)


async def run_collect(
    *,
    client: PortalClient,
    db: Database,
    filter_config: FilterConfig,
    type_codes: dict[str, str],
    date_from: str,
    date_to: str,
    trade_type: str | None = None,
    max_pages: int | None = None,
    page_size: int = 15,
    run_id: int | None = None,
) -> WindowResult:
    window_repo = WindowRepo(db)
    filter_hash = f"{filter_config.version}:{trade_type or 'all'}"
    window_id = await window_repo.get_or_create(
        kind="feed",
        date_from=date_from,
        date_to=date_to,
        filter_hash=filter_hash,
        run_id=run_id,
        trade_type=trade_type,
    )
    discovery = DiscoveryService(
        client=client,
        db=db,
        window_repo=window_repo,
        bidding_repo=BiddingRepo(db),
        raw_repo=RawRepo(db),
        error_repo=ErrorRepo(db),
        filter_config=filter_config,
        type_codes=type_codes,
        run_id=run_id,
        page_size=page_size,
    )
    return await discovery.discover_window(
        window_id,
        date_from=date_from,
        date_to=date_to,
        trade_type=trade_type,
        max_pages=max_pages,
    )


async def run_collect_recent(
    *,
    client: PortalClient,
    db: Database,
    filter_config: FilterConfig,
    type_codes: dict[str, str],
    lookback_hours: int = 24,
    trade_type: str | None = None,
    max_pages: int | None = None,
    page_size: int = 15,
    run_id: int | None = None,
) -> WindowResult:
    """Incremental discovery of the newest biddings (list is dateCreate DESC)."""
    now = now_msk()
    date_from = (now - timedelta(hours=lookback_hours)).isoformat(timespec="seconds")
    date_to = now.isoformat(timespec="seconds")
    filter_hash = f"{filter_config.version}:recent:{trade_type or 'all'}:{lookback_hours}"

    window_repo = WindowRepo(db)
    window_id = await window_repo.get_or_create(
        kind="feed",
        date_from=date_from,
        date_to=date_to,
        filter_hash=filter_hash,
        run_id=run_id,
        trade_type=trade_type,
    )
    discovery = DiscoveryService(
        client=client,
        db=db,
        window_repo=window_repo,
        bidding_repo=BiddingRepo(db),
        raw_repo=RawRepo(db),
        error_repo=ErrorRepo(db),
        filter_config=filter_config,
        type_codes=type_codes,
        run_id=run_id,
        page_size=page_size,
    )
    return await discovery.discover_recent(
        window_id=window_id,
        date_from=date_from,
        date_to=date_to,
        trade_type=trade_type,
        max_pages=max_pages,
    )


async def run_details(
    *,
    client: PortalClient,
    db: Database,
    filter_config: FilterConfig,
    limit: int,
    run_id: int | None = None,
) -> dict[str, int]:
    service = DetailsService(
        client=client,
        db=db,
        bidding_repo=BiddingRepo(db),
        lot_repo=LotRepo(db),
        message_repo=MessageRepo(db),
        raw_repo=RawRepo(db),
        error_repo=ErrorRepo(db),
        filter_config=filter_config,
        run_id=run_id,
    )
    return await service.process_candidates(limit)

from __future__ import annotations

from typing import Any
from urllib.parse import urlencode

from config import settings


def api(path: str, params: dict[str, Any] | None = None) -> str:
    prefix = settings.portal.api_prefix.rstrip("/")
    if not path.startswith("/"):
        path = "/" + path
    url = f"{prefix}{path}"
    if params:
        clean = {key: value for key, value in params.items() if value is not None}
        if clean:
            url = f"{url}?{urlencode(clean, doseq=True)}"
    return url


def bidding_types() -> str:
    return api("/reference-book/bidding-types")


def regions() -> str:
    return api("/reference-book/regions")


def biddings(
    *,
    limit: int = 50,
    offset: int = 0,
    trade_start_date: str | None = None,
    trade_end_date: str | None = None,
    trade_type: str | None = None,
    region_number: str | None = None,
    bankrupt_guid: str | None = None,
    search_string: str | None = None,
    only_available: bool | None = None,
) -> str:
    return api(
        "/biddings",
        {
            "limit": limit,
            "offset": offset,
            "tradeStartDate": trade_start_date,
            "tradeEndDate": trade_end_date,
            "tradeType": trade_type,
            "regionNumber": region_number,
            "bankruptGuid": bankrupt_guid,
            "searchString": search_string,
            "onlyAvailableToParticipate": (
                "true" if only_available is True else "false" if only_available is False else None
            ),
        },
    )


def bidding(guid: str) -> str:
    return api(f"/biddings/{guid}")


def bidding_main(guid: str) -> str:
    return api(f"/biddings/{guid}/main")


def bidding_additional(guid: str) -> str:
    return api(f"/biddings/{guid}/additional")


def bidding_lots(guid: str, *, limit: int = 50, offset: int = 0) -> str:
    return api(f"/biddings/{guid}/lots", {"limit": limit, "offset": offset})


def bidding_messages(guid: str, *, limit: int = 50, offset: int = 0) -> str:
    return api(f"/biddings/{guid}/messages", {"limit": limit, "offset": offset})


def account_receivables(*, limit: int = 50, offset: int = 0) -> str:
    return api("/account-receivables", {"limit": limit, "offset": offset})


def card_url(guid: str) -> str:
    return settings.portal.trade_url_template.format(guid=guid)


def message_url(message_guid: str) -> str:
    return settings.portal.message_url_template.format(guid=message_guid)

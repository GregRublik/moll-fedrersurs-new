from __future__ import annotations

from typing import Any

from fedresurs.normalization.hashing import canonical_json, content_hash
from fedresurs.normalization.html_text import money, number_text, strip_html


def lot_key(trade_guid: str, lot_number: str) -> str:
    return f"{trade_guid}:{lot_number}"


def normalize_lot(
    item: dict[str, Any],
    *,
    trade_guid: str,
    ordinal: int,
    is_public_offer: bool,
) -> dict[str, Any]:
    lot_number = number_text(item.get("number"))
    if not lot_number:
        raise ValueError(f"lot without number in trade {trade_guid}")

    status = item.get("status") or {}
    classifiers = [str(value) for value in (item.get("classifiers") or []) if value]
    trade_object_html = item.get("tradeObject")

    normalized: dict[str, Any] = {
        "trade_guid": trade_guid,
        "lot_number": lot_number,
        "ordinal": ordinal,
        "lot_key": lot_key(trade_guid, lot_number),
        "status_code": status.get("code"),
        "status_name": status.get("name"),
        "start_price": money(item.get("startPrice")),
        "current_price": money(item.get("currentPrice")),
        "min_price": money(item.get("minPrice")),
        "deposit": money(item.get("deposit")),
        "advance_percent": money(item.get("advancePercent")),
        "price_reduction_json": canonical_json(
            {"text": item.get("priceReduction"), "prices": item.get("prices")}
        ),
        "classifiers_json": canonical_json(classifiers),
        "trade_object_html": trade_object_html,
        "trade_object_text": strip_html(trade_object_html),
        "sale_agreement": item.get("saleAgreement"),
        "payment_info": item.get("paymentInfo"),
        "is_public_offer": int(is_public_offer),
    }

    result = dict(normalized)
    result["content_hash"] = content_hash(normalized)
    result["normalized_json"] = canonical_json(normalized)
    return result

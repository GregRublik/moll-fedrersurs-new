from __future__ import annotations

from typing import Any

from fedresurs.normalization.hashing import canonical_json, content_hash
from fedresurs.portal import endpoints
from fedresurs.timeutil import to_msk_iso

# Fallback if the reference book could not be loaded.
TYPE_CODES_BY_NAME = {
    "Открытый аукцион": "OpenAuction",
    "Открытый конкурс": "OpenConcours",
    "Публичное предложение": "PublicOffer",
    "Закрытый аукцион": "CloseAuction",
    "Закрытый конкурс": "CloseConcours",
    "Закрытое публичное предложение": "ClosePublicOffer",
}


def type_codes_from_reference(records: list[dict[str, Any]]) -> dict[str, str]:
    return {
        str(record.get("name")): str(record.get("code"))
        for record in records
        if record.get("name") and record.get("code")
    }


def normalize_bidding(
    item: dict[str, Any],
    type_codes: dict[str, str] | None = None,
) -> dict[str, Any]:
    guid = item.get("guid")
    if not guid:
        raise ValueError("bidding item has no guid")

    bankrupt = item.get("bankrupt") or {}
    trade_place = item.get("tradePlace") or {}
    status = item.get("status") or {}
    type_name = item.get("type")
    codes = type_codes or TYPE_CODES_BY_NAME

    normalized: dict[str, Any] = {
        "guid": guid,
        "number": item.get("number"),
        "trade_type_code": codes.get(type_name),
        "trade_type_name": type_name,
        "status": status.get("name"),
        "price_form": None,
        "is_rebidding": int(bool(item.get("isRebidding"))),
        "debtor_name": bankrupt.get("name"),
        "debtor_inn": bankrupt.get("inn"),
        "debtor_ogrn": bankrupt.get("ogrn"),
        "debtor_region": bankrupt.get("region"),
        "organizer_name": None,
        "organizer_inn": None,
        "manager_name": None,
        "manager_inn": None,
        "manager_snils": None,
        "manager_address": None,
        "manager_email": None,
        "sro_name": None,
        "sro_inn": None,
        "sro_ogrn": None,
        "sro_address": None,
        "application_rules": None,
        "additional_text": None,
        "announcement_text": None,
        "publisher_json": None,
        "case_number": None,
        "court": None,
        "platform_name": trade_place.get("name"),
        "platform_url": trade_place.get("url"),
        "trade_start_at": to_msk_iso(item.get("dateStart")),
        "trade_end_at": to_msk_iso(item.get("dateFinish")),
        "application_start_at": None,
        "application_end_at": None,
        "published_at": to_msk_iso(item.get("dateCreate")),
        "updated_at_source": None,
        "source_url": endpoints.card_url(guid),
        "message_url": None,
        "source_state": "active",
    }

    result = dict(normalized)
    result["content_hash"] = content_hash(normalized)
    result["normalized_json"] = canonical_json(normalized)
    return result

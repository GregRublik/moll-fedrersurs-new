from __future__ import annotations

from typing import Any

from config import settings
from fedresurs.normalization.hashing import canonical_json, content_hash
from fedresurs.normalization.html_text import strip_html
from fedresurs.portal import endpoints
from fedresurs.timeutil import to_msk_iso


def normalize_message(item: dict[str, Any], trade_guid: str) -> dict[str, Any] | None:
    """Message metadata from /biddings/{guid}/messages."""
    guid = item.get("guid")
    if not guid:
        return None

    normalized: dict[str, Any] = {
        "guid": guid,
        "trade_guid": trade_guid,
        "event_time": to_msk_iso(item.get("eventTime")),
        "number": item.get("number"),
        "date_publish": to_msk_iso(item.get("datePublish")),
        "type": item.get("type"),
        "is_annulled": int(bool(item.get("isAnnuled"))),
        "is_locked": int(bool(item.get("isLocked"))),
        "text_html": None,
        "text_plain": None,
        "files_json": canonical_json(item.get("files") or []),
    }
    normalized["content_hash"] = content_hash(normalized)
    return normalized


def document_url(doc_guid: str) -> str:
    base = settings.portal.base_url.rstrip("/")
    return base + endpoints.bankruptcy_message_doc(doc_guid)


def normalize_announcement(
    payload: dict[str, Any], trade_guid: str
) -> dict[str, Any] | None:
    """Full sale announcement from /backend/bankruptcy-messages/{guid}."""
    guid = payload.get("guid")
    if not guid:
        return None

    content = payload.get("content") or {}
    message_content = (content.get("messageInfo") or {}).get("messageContent") or {}

    documents = []
    for doc in payload.get("docs") or []:
        doc_guid = doc.get("guid")
        if not doc_guid:
            continue
        documents.append(
            {
                "guid": doc_guid,
                "name": doc.get("name"),
                "size": doc.get("size"),
                "url": document_url(doc_guid),
            }
        )

    text = message_content.get("text")
    auction = message_content.get("auctionDateTime") or {}

    normalized: dict[str, Any] = {
        "guid": guid,
        "trade_guid": trade_guid,
        "event_time": to_msk_iso(auction.get("dateTime")),
        "number": payload.get("number"),
        "date_publish": to_msk_iso(payload.get("datePublish")),
        "type": payload.get("typeName") or payload.get("messageType"),
        "is_annulled": 0,
        "is_locked": 0,
        "text_html": text,
        "text_plain": strip_html(text),
        "files_json": canonical_json(documents),
    }
    normalized["content_hash"] = content_hash(normalized)
    return normalized


def normalize_bidding_message(
    payload: dict[str, Any], trade_guid: str
) -> dict[str, Any] | None:
    """Event message from /backend/bidding-messages/{guid}."""
    guid = payload.get("guid")
    if not guid:
        return None

    content = payload.get("content") or {}
    normalized: dict[str, Any] = {
        "guid": guid,
        "trade_guid": trade_guid,
        "event_time": to_msk_iso(content.get("eventTime") or payload.get("datePublish")),
        "number": payload.get("number"),
        "date_publish": to_msk_iso(payload.get("datePublish")),
        "type": (payload.get("type") or {}).get("name"),
        "is_annulled": 0,
        "is_locked": int(bool(payload.get("isLocked"))),
        "text_html": None,
        "text_plain": None,
        "files_json": canonical_json(payload.get("files") or []),
    }
    normalized["content_hash"] = content_hash(normalized)
    return normalized


def publisher_fields(payload: dict[str, Any]) -> dict[str, Any]:
    """Map content.publisher (arbitr manager + SRO) to bidding columns."""
    publisher = (payload.get("content") or {}).get("publisher") or {}
    fio = publisher.get("fio") or {}
    sro = publisher.get("sro") or {}

    name = " ".join(
        part for part in (fio.get("lastName"), fio.get("firstName"), fio.get("middleName")) if part
    ).strip() or None

    values = {
        "manager_name": name,
        "manager_inn": publisher.get("inn"),
        "manager_snils": publisher.get("snils"),
        "manager_address": publisher.get("correspondenceAddress"),
        "manager_email": publisher.get("email"),
        "sro_name": sro.get("name"),
        "sro_inn": sro.get("inn"),
        "sro_ogrn": sro.get("ogrn"),
        "sro_address": sro.get("address"),
        "publisher_json": canonical_json(publisher) if publisher else None,
    }
    return {key: value for key, value in values.items() if value}


def announcement_fields(payload: dict[str, Any]) -> dict[str, Any]:
    """Map announcement rules/text to bidding columns."""
    content = payload.get("content") or {}
    message_content = (content.get("messageInfo") or {}).get("messageContent") or {}
    application = message_content.get("application") or {}
    values = {
        "application_rules": application.get("rules"),
        "additional_text": message_content.get("additionalText"),
        "announcement_text": message_content.get("text"),
    }
    return {key: value for key, value in values.items() if value}

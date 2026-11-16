from __future__ import annotations

import json
import logging
from typing import Any

from fedresurs.bitrix.client import BitrixClient
from fedresurs.bitrix.errors import BitrixApiError
from fedresurs.bitrix.fields import EntityMap, FieldMap, xml_id_for
from fedresurs.normalization.html_text import strip_html
from fedresurs.portal import endpoints
from fedresurs.storage.repositories import (
    BiddingRepo,
    BitrixMapRepo,
    ErrorRepo,
    LotRepo,
)
from fedresurs.timeutil import date_only, to_msk_iso

logger = logging.getLogger(__name__)


def _truncate(value: str, limit: int = 500) -> str:
    return value if len(value) <= limit else value[: limit - 1] + "…"


def _format_value(entity: EntityMap, logical: str, value: Any) -> Any:
    if value is None or value == "":
        return None
    field_type = entity.type_of(logical)
    if field_type == "date":
        return date_only(value)
    if field_type == "datetime":
        return to_msk_iso(value)
    if field_type in ("double", "integer"):
        try:
            return float(value) if field_type == "double" else int(float(value))
        except (TypeError, ValueError):
            return None
    if isinstance(value, (dict, list)):
        value = json.dumps(value, ensure_ascii=False)
    return _truncate(str(value))


def _resolve(entity: EntityMap, logical: str, source: dict[str, Any]) -> Any:
    if logical not in source:
        return None
    return _format_value(entity, logical, source[logical])


def _price_reduction_text(raw: str | None) -> str | None:
    if not raw:
        return None
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return raw
    if not isinstance(payload, dict):
        return str(payload)

    intervals = payload.get("intervals") or []
    if intervals:
        parts = []
        for interval in intervals:
            start = date_only(interval.get("start_at"))
            end = date_only(interval.get("end_at"))
            price = interval.get("price")
            if start or end:
                parts.append(f"{start or '—'}–{end or '—'}: {price}")
            elif price:
                parts.append(str(price))
        if parts:
            return "; ".join(parts)

    text = payload.get("text")
    return str(text) if text else None


def _first_classifier(raw: str | None) -> str | None:
    if not raw:
        return None
    try:
        values = json.loads(raw)
    except json.JSONDecodeError:
        return raw
    if isinstance(values, list) and values:
        return str(values[0])
    return None


def _range_text(start: str | None, end: str | None) -> str | None:
    if not start and not end:
        return None
    return f"{date_only(start) or '—'} — {date_only(end) or '—'}"


def build_trade_fields(row: Any, field_map: FieldMap) -> dict[str, Any]:
    entity = field_map.trade
    source = {
        "number": row["number"],
        "trade_number": row["number"],
        "trade_type": row["trade_type_name"],
        "trade_type_alt": row["trade_type_name"],
        "status": row["status"],
        "price_form": row["price_form"],
        "date": row["published_at"],
        "trade_date": row["trade_start_at"],
        "trade_start": row["trade_start_at"],
        "trade_end": row["trade_end_at"],
        "application_start": row["application_start_at"],
        "application_end": row["application_end_at"],
        "application_period": _range_text(
            row["application_start_at"], row["application_end_at"]
        ),
        "card_url": row["source_url"],
        "url": row["source_url"],
        "message_url": row["message_url"],
        "debtor_name": row["debtor_name"],
        "debtor_inn": row["debtor_inn"],
        "debtor_ogrn": row["debtor_ogrn"],
        "region": row["debtor_region"],
        "case_number": row["case_number"],
        "court": row["court"],
        "organizer": row["organizer_name"],
        "manager": row["manager_name"],
        "manager_name": row["manager_name"],
        "manager_inn": row["manager_inn"],
        "manager_snils": row["manager_snils"],
        "manager_address": row["manager_address"],
        "manager_email": row["manager_email"],
        "sro_name": row["sro_name"],
        "sro_inn": row["sro_inn"],
        "sro_ogrn": row["sro_ogrn"],
        "sro_address": row["sro_address"],
        "rules": row["application_rules"],
        "additional_info": row["additional_text"],
        "text": row["announcement_text"],
        "platform_raw": row["platform_name"],
        "etp_name": row["platform_name"],
        "etp_url": row["platform_url"],
        "trade_place": row["platform_name"],
    }
    return {
        entity.api_fields()[logical]: value
        for logical in entity.fields
        if (value := _resolve(entity, logical, source)) is not None
    }


def build_lot_fields(row: Any, trade_row: Any, field_map: FieldMap) -> dict[str, Any]:
    entity = field_map.lot
    source = {
        "lot_number": row["lot_number"],
        "trade_number": trade_row["number"],
        "description": row["trade_object_text"] or strip_html(row["trade_object_html"]),
        "classification": _first_classifier(row["classifiers_json"]),
        "start_price": row["start_price"],
        "current_price": row["current_price"],
        "min_price": row["min_price"],
        "deposit": row["deposit"],
        "price_reduction": _price_reduction_text(row["price_reduction_json"]),
        "status": row["status_name"],
        "trade_status": row["status_name"],
        "trade_url": endpoints.card_url(row["trade_guid"]),
        "trade_start_date": trade_row["trade_start_at"],
        "debtor": trade_row["debtor_name"],
    }
    return {
        entity.api_fields()[logical]: value
        for logical in entity.fields
        if (value := _resolve(entity, logical, source)) is not None
    }


def build_payload(
    entity: EntityMap,
    fields: dict[str, Any],
    *,
    xml_id: str,
    category_id: int,
    required: dict[str, Any],
) -> dict[str, Any]:
    payload = dict(fields)
    payload["xmlId"] = xml_id
    payload["categoryId"] = category_id
    for key, value in required.items():
        payload.setdefault(key, value)
    return {key: value for key, value in payload.items() if value is not None}


class BitrixSyncService:
    def __init__(
        self,
        *,
        client: BitrixClient,
        field_map: FieldMap,
        bidding_repo: BiddingRepo,
        lot_repo: LotRepo,
        map_repo: BitrixMapRepo,
        error_repo: ErrorRepo,
        dry_run: bool = True,
        write_enabled: bool = False,
    ) -> None:
        self.client = client
        self.field_map = field_map
        self.bidding_repo = bidding_repo
        self.lot_repo = lot_repo
        self.map_repo = map_repo
        self.error_repo = error_repo
        self.dry_run = dry_run or not write_enabled

    async def sync_pending(
        self,
        limit: int = 50,
        *,
        trade_guid: str | None = None,
        force: bool = False,
        only_candidates: bool = True,
    ) -> dict[str, int]:
        stats = {
            "trades_scanned": 0,
            "trades_synced": 0,
            "lots_scanned": 0,
            "lots_synced": 0,
            "waiting_for_trade": 0,
            "skipped_non_candidates": 0,
            "matched_by_number": 0,
            "dry_run": 0,
            "errors": 0,
        }

        if only_candidates:
            stats["skipped_non_candidates"] += await self.bidding_repo.count_non_candidates(
                guid=trade_guid, include_synced=force
            )
            stats["skipped_non_candidates"] += await self.lot_repo.count_non_candidates(
                trade_guid=trade_guid, include_synced=force
            )

        for row in await self.bidding_repo.list_for_sync(
            limit, guid=trade_guid, include_synced=force, only_candidates=only_candidates
        ):
            stats["trades_scanned"] += 1
            await self._sync_bidding(row, stats)

        for row in await self.lot_repo.list_for_sync(
            limit, trade_guid=trade_guid, include_synced=force, only_candidates=only_candidates
        ):
            stats["lots_scanned"] += 1
            await self._sync_lot(row, stats)

        return stats

    async def _sync_bidding(self, row: Any, stats: dict[str, int]) -> None:
        guid = row["guid"]
        entity = self.field_map.trade
        xml_id = xml_id_for(entity, guid)
        fields = build_trade_fields(row, self.field_map)
        fields["title"] = entity.title_template.format(
            number=row["number"] or "", trade_type=row["trade_type_name"] or ""
        ).strip()
        payload = build_payload(
            entity,
            fields,
            xml_id=xml_id,
            category_id=entity.category_id,
            required=self.field_map.required_fields,
        )

        try:
            existing = await self._find_item(
                entity.entity_type_id, xml_id, category_id=entity.category_id
            )
            if existing is None:
                number_field = entity.api_fields().get("trade_number")
                if number_field and row["number"]:
                    existing = await self._find_item_by_field(
                        entity.entity_type_id,
                        number_field,
                        row["number"],
                        category_id=entity.category_id,
                    )
                    if existing is not None:
                        stats["matched_by_number"] += 1
                        logger.info(
                            "bitrix matched trade %s by %s=%s -> id %s",
                            guid,
                            number_field,
                            row["number"],
                            existing,
                        )
        except BitrixApiError as exc:
            await self._fail_bidding(guid, exc, stats)
            return

        if self.dry_run:
            logger.info("bitrix dry-run trade %s xmlId=%s fields=%s", guid, xml_id, sorted(payload))
            stats["dry_run"] += 1
            return

        try:
            if existing is not None:
                await self.client.call(
                    "crm.item.update",
                    {"entityTypeId": entity.entity_type_id, "id": existing, "fields": payload},
                )
                bitrix_id = existing
            else:
                response = await self.client.call(
                    "crm.item.add",
                    {"entityTypeId": entity.entity_type_id, "fields": payload},
                )
                bitrix_id = int(response["result"]["item"]["id"])
        except BitrixApiError as exc:
            await self._fail_bidding(guid, exc, stats)
            return
        except Exception as exc:  # noqa: BLE001
            await self._fail_bidding(guid, exc, stats)
            return

        await self.map_repo.set(
            entity_type="bidding",
            entity_key=guid,
            bitrix_entity_type_id=entity.entity_type_id,
            bitrix_id=bitrix_id,
            xml_id=xml_id,
        )
        await self.bidding_repo.set_synced(guid, bitrix_id, row["content_hash"])
        stats["trades_synced"] += 1

    async def _sync_lot(self, row: Any, stats: dict[str, int]) -> None:
        lot_key = row["lot_key"]
        trade_guid = row["trade_guid"]
        trade_row = await self.bidding_repo.get(trade_guid)
        if trade_row is None:
            stats["waiting_for_trade"] += 1
            return

        mapping = await self.map_repo.get("bidding", trade_guid)
        trade_bitrix_id = mapping["bitrix_id"] if mapping else trade_row["bitrix_id"]
        if not trade_bitrix_id:
            stats["waiting_for_trade"] += 1
            return

        entity = self.field_map.lot
        xml_id = xml_id_for(entity, lot_key)
        fields = build_lot_fields(row, trade_row, self.field_map)
        fields["title"] = entity.title_template.format(
            lot_number=row["lot_number"] or "",
            classification=_first_classifier(row["classifiers_json"]) or "",
        ).strip()
        if entity.parent_field:
            fields[entity.parent_field] = trade_bitrix_id
        payload = build_payload(
            entity,
            fields,
            xml_id=xml_id,
            category_id=entity.category_id,
            required=self.field_map.required_fields,
        )

        try:
            existing = await self._find_item(
                entity.entity_type_id, xml_id, category_id=entity.category_id
            )
        except BitrixApiError as exc:
            await self._fail_lot(lot_key, exc, stats)
            return

        if self.dry_run:
            logger.info("bitrix dry-run lot %s xmlId=%s fields=%s", lot_key, xml_id, sorted(payload))
            stats["dry_run"] += 1
            return

        try:
            if existing is not None:
                await self.client.call(
                    "crm.item.update",
                    {"entityTypeId": entity.entity_type_id, "id": existing, "fields": payload},
                )
                bitrix_id = existing
            else:
                response = await self.client.call(
                    "crm.item.add",
                    {"entityTypeId": entity.entity_type_id, "fields": payload},
                )
                bitrix_id = int(response["result"]["item"]["id"])
        except Exception as exc:  # noqa: BLE001
            await self._fail_lot(lot_key, exc, stats)
            return

        await self.map_repo.set(
            entity_type="lot",
            entity_key=lot_key,
            bitrix_entity_type_id=entity.entity_type_id,
            bitrix_id=bitrix_id,
            xml_id=xml_id,
        )
        await self.lot_repo.set_synced(lot_key, bitrix_id, row["content_hash"])
        stats["lots_synced"] += 1

    async def _find_item(
        self, entity_type_id: int, xml_id: str, *, category_id: int
    ) -> int | None:
        response = await self.client.call(
            "crm.item.list",
            {
                "entityTypeId": entity_type_id,
                "filter": {"xmlId": xml_id, "categoryId": category_id},
                "select": ["id", "xmlId", "categoryId"],
            },
        )
        items = response.get("result", {}).get("items", [])
        if not items:
            return None
        return int(items[0]["id"])

    async def _find_item_by_field(
        self,
        entity_type_id: int,
        field: str,
        value: object,
        *,
        category_id: int,
    ) -> int | None:
        """Find legacy cards created by another integration (empty xmlId).

        Prefer a card without xmlId, then the oldest one; duplicates already
        exist in the portal, and we must not create one more.
        """
        response = await self.client.call(
            "crm.item.list",
            {
                "entityTypeId": entity_type_id,
                "filter": {field: str(value), "categoryId": category_id},
                "select": ["id", "xmlId", "categoryId", "title"],
                "order": {"id": "ASC"},
            },
        )
        items = response.get("result", {}).get("items", [])
        if not items:
            return None
        items.sort(key=lambda item: (bool(item.get("xmlId")), int(item.get("id", 0))))
        return int(items[0]["id"])

    async def _fail_bidding(self, guid: str, exc: Exception, stats: dict[str, int]) -> None:
        stats["errors"] += 1
        await self.bidding_repo.set_sync_failed(guid, str(exc))
        try:
            await self.error_repo.add(
                error_type="bitrix_api_error",
                message=str(exc),
                stage="sync",
                entity_type="bidding",
                entity_key=guid,
            )
        except Exception:  # noqa: BLE001
            pass

    async def _fail_lot(self, lot_key: str, exc: Exception, stats: dict[str, int]) -> None:
        stats["errors"] += 1
        await self.lot_repo.set_sync_failed(lot_key, str(exc))
        try:
            await self.error_repo.add(
                error_type="bitrix_api_error",
                message=str(exc),
                stage="sync",
                entity_type="lot",
                entity_key=lot_key,
            )
        except Exception:  # noqa: BLE001
            pass

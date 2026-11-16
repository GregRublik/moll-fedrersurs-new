from __future__ import annotations

import json
from typing import Any

from fedresurs.constants import EntityType
from fedresurs.filtering.rules import FilterConfig, decide_lot, decide_trade, lot_classifiers, lot_texts
from fedresurs.normalization.hashing import canonical_json, content_hash
from fedresurs.normalization.lot import normalize_lot
from fedresurs.normalization.message import (
    announcement_fields,
    normalize_announcement,
    normalize_message,
    publisher_fields,
)
from fedresurs.portal import endpoints
from fedresurs.portal.client import PortalClient
from fedresurs.portal.parsers import extract_page
from fedresurs.storage.db import Database
from fedresurs.storage.repositories import (
    BIDDING_COLUMNS,
    BiddingRepo,
    ErrorRepo,
    LotRepo,
    MessageRepo,
    RawRepo,
)
from fedresurs.timeutil import to_msk_iso

PRICE_FORM_NAMES = {"OpenForm": "Открытая", "CloseForm": "Закрытая"}


def price_form_name(value: str | None) -> str | None:
    if not value:
        return None
    return PRICE_FORM_NAMES.get(value, value)


def merge_card(
    base: dict[str, Any],
    card: dict[str, Any],
    main: dict[str, Any],
    additional: dict[str, Any],
) -> dict[str, Any]:
    merged = dict(base)

    type_info = card.get("type") or {}
    if type_info.get("code"):
        merged["trade_type_code"] = type_info["code"]
    if type_info.get("name"):
        merged["trade_type_name"] = type_info["name"]

    status = main.get("status") or {}
    if status.get("name"):
        merged["status"] = status["name"]
    if "isRebidding" in main:
        merged["is_rebidding"] = int(bool(main.get("isRebidding")))

    debtor = card.get("debtor") or {}
    for source, target in (
        ("name", "debtor_name"),
        ("inn", "debtor_inn"),
        ("ogrn", "debtor_ogrn"),
        ("region", "debtor_region"),
    ):
        if debtor.get(source):
            merged[target] = debtor[source]

    organizer = card.get("organizer") or {}
    if organizer.get("name"):
        merged["organizer_name"] = organizer["name"]

    manager = card.get("arbitrManager") or {}
    if manager.get("name"):
        merged["manager_name"] = manager["name"]
    if manager.get("inn"):
        merged["manager_inn"] = manager["inn"]

    legal_case = card.get("legalCase") or {}
    if legal_case.get("number"):
        merged["case_number"] = legal_case["number"]

    if additional.get("courtName"):
        merged["court"] = additional["courtName"]
    if additional.get("priceForm"):
        merged["price_form"] = price_form_name(additional["priceForm"])

    place = card.get("tradePlace") or {}
    if place.get("name"):
        merged["platform_name"] = place["name"]
    if place.get("url"):
        merged["platform_url"] = place["url"]

    application = card.get("applicationPeriod") or {}
    if to_msk_iso(application.get("startDate")):
        merged["application_start_at"] = to_msk_iso(application.get("startDate"))
    if to_msk_iso(application.get("endDate")):
        merged["application_end_at"] = to_msk_iso(application.get("endDate"))

    bidding_period = card.get("biddingPeriod") or {}
    if to_msk_iso(bidding_period.get("startDate")):
        merged["trade_start_at"] = to_msk_iso(bidding_period.get("startDate"))
    if to_msk_iso(bidding_period.get("endDate")):
        merged["trade_end_at"] = to_msk_iso(bidding_period.get("endDate"))

    message = card.get("message") or {}
    if message.get("guid"):
        merged["message_url"] = endpoints.message_url(message["guid"])
    if to_msk_iso(message.get("datePublish")):
        merged["updated_at_source"] = to_msk_iso(message.get("datePublish"))

    return merged


def build_bidding_row(row: Any, base: dict[str, Any]) -> dict[str, Any]:
    data = {column: row[column] for column in BIDDING_COLUMNS}
    data.update({column: base[column] for column in BIDDING_COLUMNS if column in base})
    data["guid"] = row["guid"]
    data["content_hash"] = content_hash(base)
    data["normalized_json"] = canonical_json(base)
    return data


class DetailsService:
    def __init__(
        self,
        *,
        client: PortalClient,
        db: Database,
        bidding_repo: BiddingRepo,
        lot_repo: LotRepo,
        message_repo: MessageRepo,
        raw_repo: RawRepo,
        error_repo: ErrorRepo,
        filter_config: FilterConfig,
        lot_page_size: int = 3,
        message_page_size: int = 3,
        run_id: int | None = None,
    ) -> None:
        self.client = client
        self.db = db
        self.bidding_repo = bidding_repo
        self.lot_repo = lot_repo
        self.message_repo = message_repo
        self.raw_repo = raw_repo
        self.error_repo = error_repo
        self.filter_config = filter_config
        self.lot_page_size = lot_page_size
        self.message_page_size = message_page_size
        self.run_id = run_id

    async def process_candidates(self, limit: int = 50) -> dict[str, int]:
        rows = await self.bidding_repo.list_candidates(limit)
        stats = {"candidates": len(rows), "processed": 0, "errors": 0, "lots": 0, "messages": 0}
        for row in rows:
            try:
                result = await self.process_one(row)
            except Exception as exc:  # noqa: BLE001
                stats["errors"] += 1
                await self._error(row["guid"], "details_failed", exc)
                continue
            stats["processed"] += 1
            stats["lots"] += result["lots"]
            stats["messages"] += result["messages"]
        return stats

    async def process_one(self, row: Any) -> dict[str, int]:
        guid = row["guid"]
        base = json.loads(row["normalized_json"] or "{}")

        card = await self._get_json(
            endpoints.bidding(guid), entity_type=EntityType.BIDDING, entity_key=guid
        )
        main = await self._get_json(
            endpoints.bidding_main(guid), entity_type=EntityType.BIDDING, entity_key=guid
        )
        additional = await self._get_json(
            endpoints.bidding_additional(guid), entity_type=EntityType.BIDDING, entity_key=guid
        )
        merged = merge_card(base, card, main, additional)

        announcement = None
        message_guid = (card.get("message") or {}).get("guid")
        if message_guid:
            try:
                announcement = await self._get_json(
                    endpoints.bankruptcy_message(message_guid),
                    entity_type=EntityType.BIDDING,
                    entity_key=guid,
                )
            except Exception as exc:  # noqa: BLE001
                await self._error(guid, "announcement_failed", exc)
            else:
                merged.update(announcement_fields(announcement))
                merged.update(publisher_fields(announcement))
                message_data = normalize_announcement(announcement, guid)
                if message_data is not None:
                    try:
                        await self.message_repo.upsert(message_data)
                    except Exception as exc:  # noqa: BLE001
                        await self._error(guid, "announcement_store_failed", exc)

        decision = decide_trade(merged.get("trade_type_code"), self.filter_config)
        merged["is_candidate"] = int(decision.decision == "include")
        merged["match_score"] = decision.score
        merged["match_reasons_json"] = canonical_json(decision.reasons)
        merged["filter_version"] = self.filter_config.version
        merged["classification_source"] = str(decision.source)

        data = build_bidding_row(row, merged)
        await self.bidding_repo.upsert(data)
        await self.bidding_repo.mark_details_fetched(guid)

        lots = 0
        if row["lots_fetched_at"] is None:
            lots = await self._process_lots(guid, merged)
            await self.bidding_repo.mark_lots_fetched(guid)

        messages = 0
        if row["messages_fetched_at"] is None:
            messages = await self._process_messages(guid)
            await self.bidding_repo.mark_messages_fetched(guid)

        return {"lots": lots, "messages": messages}

    async def _process_lots(self, guid: str, bidding: dict[str, Any]) -> int:
        items = await self._fetch_all(
            endpoints.bidding_lots,
            guid,
            page_size=self.lot_page_size,
        )
        is_public_offer = bidding.get("trade_type_code") == "PublicOffer"
        count = 0
        for ordinal, item in enumerate(items, start=1):
            try:
                data = normalize_lot(
                    item, trade_guid=guid, ordinal=ordinal, is_public_offer=is_public_offer
                )
            except Exception as exc:  # noqa: BLE001
                await self._error(guid, "lot_validation_error", exc)
                continue
            decision = decide_lot(
                classifiers=lot_classifiers(data),
                texts=lot_texts(data),
                config=self.filter_config,
            )
            data["is_candidate"] = int(decision.decision == "include")
            data["match_score"] = decision.score
            data["match_reasons_json"] = canonical_json(decision.reasons)
            data["classification_source"] = str(decision.source)
            await self.lot_repo.upsert(data)
            count += 1
        return count

    async def _process_messages(self, guid: str) -> int:
        items = await self._fetch_all(
            endpoints.bidding_messages,
            guid,
            page_size=self.message_page_size,
        )
        count = 0
        for item in items:
            data = normalize_message(item, guid)
            if data is None:
                continue
            try:
                await self.message_repo.upsert(data)
                count += 1
            except Exception as exc:  # noqa: BLE001
                await self._error(guid, "message_validation_error", exc)
        return count

    async def _fetch_all(self, endpoint, guid: str, *, page_size: int) -> list[dict[str, Any]]:
        offset = 0
        items: list[dict[str, Any]] = []
        while True:
            path = endpoint(guid, limit=page_size, offset=offset)
            payload = await self._get_json(path, entity_type=EntityType.BIDDING, entity_key=guid)
            page, found = extract_page(payload)
            items.extend(page)
            offset += len(page)
            if not page or len(page) < page_size:
                break
            if found is not None and offset >= found:
                break
        return items

    async def _get_json(self, path: str, *, entity_type: str, entity_key: str) -> dict[str, Any]:
        payload = await self.client.get(
            path, entity_type=entity_type, entity_key=entity_key
        )
        await self.raw_repo.save(
            entity_type=entity_type,
            entity_key=entity_key,
            endpoint=path,
            payload=payload,
            http_status=200,
            run_id=self.run_id,
        )
        if not isinstance(payload, dict):
            raise ValueError(f"unexpected payload for {path}")
        return payload

    async def _error(self, entity_key: str, error_type: str, exc: Exception) -> None:
        try:
            await self.error_repo.add(
                error_type=error_type,
                message=str(exc),
                stage="details",
                run_id=self.run_id,
                entity_type=EntityType.BIDDING,
                entity_key=entity_key,
            )
        except Exception:  # noqa: BLE001
            pass

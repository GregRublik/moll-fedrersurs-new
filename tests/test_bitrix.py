from __future__ import annotations

import json
from pathlib import Path

from fedresurs.bitrix.fields import FieldMap, to_api_name, xml_id_for
from fedresurs.bitrix.sync import (
    BitrixSyncService,
    _price_reduction_text,
    build_lot_fields,
    build_payload,
    build_trade_fields,
)
from fedresurs.portal.details import merge_card
from fedresurs.storage.repositories import BiddingRepo, BitrixMapRepo, ErrorRepo, LotRepo

ROOT = Path(__file__).resolve().parents[1]
FIELD_MAP = ROOT / "config" / "bitrix_fieldmap.toml"


def make_field_map(tmp_path: Path) -> FieldMap:
    discovery = tmp_path / "discovery"
    discovery.mkdir()
    fields = {
        "UF_CRM_138_1744310803": {"type": "date"},
        "UF_CRM_138_1744310779": {"type": "string"},
    }
    (discovery / "crm.item.fields_1078.json").write_text(
        json.dumps({"result": {"fields": fields}}), encoding="utf-8"
    )
    (discovery / "crm.item.fields_1120.json").write_text(
        json.dumps({"result": {"fields": {}}}), encoding="utf-8"
    )
    return FieldMap.load(FIELD_MAP, discovery_dir=discovery)


def trade_row(**overrides) -> dict:
    row = {
        "guid": "trade-1",
        "number": "394236",
        "trade_type_name": "Публичное предложение",
        "status": "Объявлены торги",
        "price_form": "Закрытая",
        "published_at": "2026-11-15T16:00:00+03:00",
        "trade_start_at": "2026-11-16T00:00:00+03:00",
        "trade_end_at": "2027-02-20T15:00:00+03:00",
        "application_start_at": "2026-11-16T00:00:00+03:00",
        "application_end_at": "2027-02-20T15:00:00+03:00",
        "source_url": "https://fedresurs.ru/biddings/trade-1",
        "message_url": None,
        "debtor_name": "Должник",
        "debtor_inn": "7700000000",
        "debtor_ogrn": None,
        "debtor_region": None,
        "case_number": "А65-19059/2022",
        "court": "Арбитражный суд",
        "organizer_name": None,
        "manager_name": "Миллер Артур Артурович",
        "manager_inn": "164400870952",
        "manager_snils": "05776088605",
        "manager_address": "423452, а/я 201",
        "manager_email": None,
        "sro_name": "СРО СОЮЗ \"АУ \"ПРАВОСОЗНАНИЕ\"",
        "sro_inn": "5029998905",
        "sro_ogrn": "1145000002146",
        "sro_address": "423600, Елабуга",
        "application_rules": "Правила приема заявок",
        "additional_text": "Дополнительный текст",
        "announcement_text": "Текст объявления",
        "platform_name": "АУКЦИОНПРО",
        "platform_url": "au-pro.ru",
        "content_hash": "hash",
    }
    row.update(overrides)
    return row


def lot_row(**overrides) -> dict:
    row = {
        "trade_guid": "trade-1",
        "lot_number": "1",
        "lot_key": "trade-1:1",
        "status_name": "Объявлены торги",
        "trade_object_text": "Имущественные права требования",
        "trade_object_html": "<b>Имущественные права требования</b>",
        "classifiers_json": json.dumps(["Права требования"], ensure_ascii=False),
        "start_price": "5062810.76",
        "current_price": None,
        "min_price": None,
        "deposit": None,
        "price_reduction_json": json.dumps({"text": "Минус 5%", "prices": None}, ensure_ascii=False),
    }
    row.update(overrides)
    return row


def test_api_name_conversion():
    assert to_api_name("UF_CRM_138_1744310779") == "ufCrm138_1744310779"
    assert to_api_name("UF_CRM_138_STATUS") == "ufCrm138Status"
    assert to_api_name("UF_CRM_138_PRICE_FORM") == "ufCrm138PriceForm"
    assert to_api_name("title") == "title"


def test_xml_id(tmp_path):
    field_map = make_field_map(tmp_path)
    assert xml_id_for(field_map.trade, "abc") == "fdrs:1078:abc"
    assert xml_id_for(field_map.lot, "abc:1") == "fdrs:1120:abc:1"


def test_build_trade_fields(tmp_path):
    field_map = make_field_map(tmp_path)
    fields = build_trade_fields(trade_row(), field_map)
    assert fields["ufCrm138_1744310779"] == "394236"
    assert fields["ufCrm138_1763216600"] == "Публичное предложение"
    assert fields["ufCrm138Status"] == "Объявлены торги"
    assert fields["ufCrm138PriceForm"] == "Закрытая"
    assert fields["ufCrm138_1774282320"] == "05776088605"  # manager_snils
    assert fields["ufCrm138_1774282346"] == 'СРО СОЮЗ "АУ "ПРАВОСОЗНАНИЕ"'
    assert fields["ufCrm138_1774282150"] == "Правила приема заявок"
    assert fields["ufCrm138_1744310814"] == "Текст объявления"
    assert fields["ufCrm138_1744310803"] == "2026-11-15"  # date field, date-only
    assert fields["ufCrm138_1774282181"] == "https://fedresurs.ru/biddings/trade-1"


def test_build_lot_fields(tmp_path):
    field_map = make_field_map(tmp_path)
    fields = build_lot_fields(lot_row(), trade_row(), field_map)
    assert fields["ufCrm148_1774282420"] == "1"
    assert fields["ufCrm148_1758037984"] == "5062810.76"
    assert fields["ufCrm148_1758037977"] == "Права требования"
    assert fields["ufCrm148_1758038004"] == "Минус 5%"


def test_merge_card_maps_status_and_price_form():
    merged = merge_card(
        {"guid": "trade-1"},
        {"type": {"code": "PublicOffer", "name": "Публичное предложение"}},
        {"status": {"name": "Объявлены торги"}},
        {"priceForm": "CloseForm", "courtName": "Арбитражный суд"},
    )
    assert merged["status"] == "Объявлены торги"
    assert merged["price_form"] == "Закрытая"
    assert merged["court"] == "Арбитражный суд"


def test_price_reduction_summary_from_intervals():
    raw = json.dumps(
        {
            "format": "html_table",
            "intervals": [
                {
                    "start_at": "2026-11-16T00:00:00+03:00",
                    "end_at": "2026-11-20T15:00:00+03:00",
                    "price": "482012.85",
                }
            ],
            "text": None,
        }
    )
    assert _price_reduction_text(raw) == "2026-11-16–2026-11-20: 482012.85"


class FakeBitrixClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    async def call(self, method: str, params: dict) -> dict:
        self.calls.append((method, params))
        if method == "crm.item.list":
            if "xmlId" in params["filter"]:
                return {"result": {"items": []}}
            return {
                "result": {
                    "items": [
                        {"id": 11393, "xmlId": "", "categoryId": 179, "title": "392933 Торги"}
                    ]
                }
            }
        if method == "crm.item.update":
            return {"result": {"item": {"id": 11393}}}
        raise AssertionError(f"unexpected method {method}")


async def test_sync_matches_existing_trade_by_number_and_sets_xml_id(db, tmp_path):
    field_map = make_field_map(tmp_path)
    await BiddingRepo(db).upsert(
        {
            "guid": "trade-1",
            "number": "392933",
            "trade_type_code": "PublicOffer",
            "trade_type_name": "Публичное предложение",
            "status": "Объявлены торги",
            "is_candidate": 1,
            "source_state": "active",
            "content_hash": "hash-1",
            "normalized_json": json.dumps({"guid": "trade-1", "number": "392933"}),
        }
    )
    row = await db.fetchone("SELECT * FROM biddings WHERE guid = 'trade-1'")

    client = FakeBitrixClient()
    service = BitrixSyncService(
        client=client,
        field_map=field_map,
        bidding_repo=BiddingRepo(db),
        lot_repo=LotRepo(db),
        map_repo=BitrixMapRepo(db),
        error_repo=ErrorRepo(db),
        dry_run=False,
        write_enabled=True,
    )
    stats = {
        "trades_scanned": 1,
        "trades_synced": 0,
        "lots_scanned": 0,
        "lots_synced": 0,
        "waiting_for_trade": 0,
        "skipped_non_candidates": 0,
        "matched_by_number": 0,
        "dry_run": 0,
        "errors": 0,
    }
    await service._sync_bidding(row, stats)

    assert stats["matched_by_number"] == 1
    assert stats["trades_synced"] == 1

    methods = [method for method, _ in client.calls]
    assert methods == ["crm.item.list", "crm.item.list", "crm.item.update"]
    number_filter = client.calls[1][1]["filter"]
    assert number_filter["ufCrm138_1774282169"] == "392933"
    assert number_filter["categoryId"] == 179

    update_params = client.calls[2][1]
    assert update_params["id"] == 11393
    assert update_params["fields"]["xmlId"] == "fdrs:1078:trade-1"

    updated = await BiddingRepo(db).get("trade-1")
    assert updated["bitrix_id"] == 11393
    assert updated["sync_status"] == "synced"
    mapping = await BitrixMapRepo(db).get("bidding", "trade-1")
    assert mapping["bitrix_id"] == 11393


def test_build_payload_adds_identity_and_category(tmp_path):
    field_map = make_field_map(tmp_path)
    payload = build_payload(
        field_map.trade,
        {"title": "394236"},
        xml_id="fdrs:1078:trade-1",
        category_id=179,
        required={"opened": "Y"},
    )
    assert payload["xmlId"] == "fdrs:1078:trade-1"
    assert payload["categoryId"] == 179
    assert payload["opened"] == "Y"

from __future__ import annotations

import json
from pathlib import Path

from fedresurs.bitrix.fields import FieldMap, to_api_name, xml_id_for
from fedresurs.bitrix.sync import build_lot_fields, build_payload, build_trade_fields

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
        "manager_inn": None,
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
    assert fields["ufCrm138_1744310803"] == "2026-11-15"  # date field, date-only
    assert fields["ufCrm138_1774282181"] == "https://fedresurs.ru/biddings/trade-1"


def test_build_lot_fields(tmp_path):
    field_map = make_field_map(tmp_path)
    fields = build_lot_fields(lot_row(), trade_row(), field_map)
    assert fields["ufCrm148_1774282420"] == "1"
    assert fields["ufCrm148_1758037984"] == "5062810.76"
    assert fields["ufCrm148_1758037977"] == "Права требования"
    assert fields["ufCrm148_1758038004"] == "Минус 5%"


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

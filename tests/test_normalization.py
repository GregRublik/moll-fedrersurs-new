from __future__ import annotations

import json

from fedresurs.normalization.bidding import normalize_bidding
from fedresurs.normalization.html_text import money, strip_html
from fedresurs.normalization.lot import normalize_lot


SAMPLE_BIDDING = {
    "guid": "f8332862-e2f0-4d59-89b6-d613095de414",
    "dateCreate": "2026-11-11T12:12:20.28",
    "type": "Публичное предложение",
    "number": "6079",
    "status": {"code": "ApplicationSessionStarted", "name": "Открыт прием заявок"},
    "priceForm": "CloseForm",
    "bankrupt": {"guid": "aa0ba760", "name": "Сальков Александр Борисович", "type": "Person", "inn": "722407513058"},
    "tradePlace": {"guid": "4a99c68a", "name": '"АУКЦИОНПРО"'},
    "dateStart": "2026-11-10T12:00:00",
    "dateFinish": "2026-12-30T12:00:00",
}

SAMPLE_LOT = {
    "number": 1,
    "status": {"code": "ApplicationSessionStarted", "name": "Открыт прием заявок"},
    "startPrice": 30000.0,
    "advancePercent": 10.0,
    "classifiers": ["Права требования"],
    "tradeObject": "Имущественные права требования<br/>Костромская область",
    "saleAgreement": "Договор купли-продажи",
    "paymentInfo": "Оплата в течение 30 дней",
    "priceReduction": "Минус процент от начальной цены",
}


def test_normalize_bidding_maps_fields_and_dates():
    data = normalize_bidding(SAMPLE_BIDDING)
    assert data["guid"] == SAMPLE_BIDDING["guid"]
    assert data["trade_type_code"] == "PublicOffer"
    assert data["trade_type_name"] == "Публичное предложение"
    assert data["status"] == "Открыт прием заявок"
    assert data["debtor_name"] == "Сальков Александр Борисович"
    assert data["platform_name"] == '"АУКЦИОНПРО"'
    assert data["trade_start_at"] == "2026-11-10T12:00:00+03:00"
    assert data["published_at"] == "2026-11-11T12:12:20.280000+03:00"
    assert data["content_hash"]
    assert json.loads(data["normalized_json"])["guid"] == data["guid"]


def test_normalize_bidding_is_stable():
    first = normalize_bidding(SAMPLE_BIDDING)
    second = normalize_bidding(SAMPLE_BIDDING)
    assert first["content_hash"] == second["content_hash"]


def test_normalize_lot_key_money_and_html():
    data = normalize_lot(
        SAMPLE_LOT, trade_guid="trade-1", ordinal=1, is_public_offer=True
    )
    assert data["lot_key"] == "trade-1:1"
    assert data["start_price"] == "30000.00"
    assert data["advance_percent"] == "10.00"
    assert data["is_public_offer"] == 1
    assert data["classifiers_json"] == json.dumps(["Права требования"], ensure_ascii=False)
    assert data["trade_object_text"] == "Имущественные права требования Костромская область"


def test_money_and_strip_html_helpers():
    assert money(1234.5) == "1234.50"
    assert money(None) is None
    assert money("bad") is None
    assert strip_html("a<br/>b &amp; c") == "a b & c"
    assert strip_html("") is None

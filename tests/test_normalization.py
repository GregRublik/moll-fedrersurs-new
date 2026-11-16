from __future__ import annotations

import json

from fedresurs.normalization.bidding import normalize_bidding
from fedresurs.normalization.html_text import money, strip_html
from fedresurs.normalization.lot import normalize_lot
from fedresurs.normalization.message import (
    announcement_fields,
    normalize_announcement,
    publisher_fields,
)


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


SAMPLE_ANNOUNCEMENT = {
    "guid": "msg-1",
    "number": "25492617",
    "datePublish": "2026-11-12T11:40:24.933",
    "typeName": "Объявление о проведении торгов",
    "content": {
        "messageInfo": {
            "messageContent": {
                "text": "<p>Текст объявления</p>",
                "additionalText": "Дополнительный текст",
                "auctionDateTime": {"dateTime": "2027-02-20T16:00:00"},
                "application": {"rules": "Правила приема заявок"},
            }
        },
        "publisher": {
            "fio": {"lastName": "Миллер", "firstName": "Артур", "middleName": "Артурович"},
            "inn": "164400870952",
            "snils": "05776088605",
            "correspondenceAddress": "423452, а/я 201",
            "sro": {
                "name": 'СРО СОЮЗ "АУ "ПРАВОСОЗНАНИЕ"',
                "inn": "5029998905",
                "ogrn": "1145000002146",
                "address": "423600, Елабуга",
            },
        },
    },
    "docs": [{"guid": "doc-1", "name": "Договор.docx", "size": 32954}],
}


def test_normalize_announcement_extracts_text_and_documents():
    data = normalize_announcement(SAMPLE_ANNOUNCEMENT, "trade-1")
    assert data["guid"] == "msg-1"
    assert data["trade_guid"] == "trade-1"
    assert data["text_html"] == "<p>Текст объявления</p>"
    assert data["text_plain"] == "Текст объявления"
    assert data["type"] == "Объявление о проведении торгов"
    assert data["event_time"] == "2027-02-20T16:00:00+03:00"

    files = json.loads(data["files_json"])
    assert files == [
        {
            "guid": "doc-1",
            "name": "Договор.docx",
            "size": 32954,
            "url": "https://fedresurs.ru/backend/bankruptcy-message-docs/doc-1",
        }
    ]


def test_publisher_and_announcement_fields():
    publisher = publisher_fields(SAMPLE_ANNOUNCEMENT)
    assert publisher["manager_name"] == "Миллер Артур Артурович"
    assert publisher["manager_inn"] == "164400870952"
    assert publisher["manager_snils"] == "05776088605"
    assert publisher["sro_name"] == 'СРО СОЮЗ "АУ "ПРАВОСОЗНАНИЕ"'
    assert publisher["sro_ogrn"] == "1145000002146"

    fields = announcement_fields(SAMPLE_ANNOUNCEMENT)
    assert fields["application_rules"] == "Правила приема заявок"
    assert fields["additional_text"] == "Дополнительный текст"
    assert fields["announcement_text"] == "<p>Текст объявления</p>"

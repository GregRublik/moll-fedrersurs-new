from __future__ import annotations

import json
from datetime import datetime

from fedresurs.normalization.lot import normalize_lot
from fedresurs.normalization.price_schedule import parse_price_schedule
from fedresurs.timeutil import MSK

NOW = datetime(2026, 11, 17, 12, 0, tzinfo=MSK)

TABLE_4 = (
    "<table>"
    "<tr><td>13.11.2026 09:00:00</td><td>16.11.2026 09:00:00</td><td>729000,00</td><td>0,00</td></tr>"
    "<tr><td>16.11.2026 09:00:00</td><td>19.11.2026 09:00:00</td><td>692550,00</td><td>0,00</td></tr>"
    "<tr><td>19.11.2026 09:00:00</td><td>22.11.2026 09:00:00</td><td>656100,00</td><td>0,00</td></tr>"
    "</table>"
)

TABLE_8 = (
    "<table>"
    "<tr><td><b>Дата начала интервала</b></td><td><b>Дата начала приема заявок на интервале</b></td>"
    "<td><b>Дата окончания приема заявок на интервале</b></td><td><b>Дата окончания интервала</b></td>"
    "<td><b>Величина снижения</b></td><td><b>Задаток на интервале, руб.</b></td>"
    "<td><b>Цена на интервале, руб.</b></td><td><b>Комментарий</b></td></tr>"
    "<tr><td>16.11.2026 10:00</td><td>16.11.2026 10:00</td><td>23.11.2026 10:00</td>"
    "<td>23.11.2026 10:00</td><td>0,00</td><td>2 700,00</td><td>27 000,00</td><td></td></tr>"
    "<tr><td>23.11.2026 10:00</td><td>23.11.2026 10:00</td><td>30.11.2026 10:00</td>"
    "<td>30.11.2026 10:00</td><td>5,00</td><td>2 565,00</td><td>25 650,00</td><td></td></tr>"
    "</table>"
)

BR_TEXT = (
    "23.11.2026 00:00: 255645.00<br/>"
    "30.11.2026 00:00: 235980.00<br/>"
    "07.12.2026 00:00: 216315.00"
)

PLAIN_TEXT = "Цена на интервале задается как снижение в рублях от цены предыдущего интервала"


def test_parse_four_column_table():
    schedule = parse_price_schedule(TABLE_4, now=NOW)
    assert schedule["format"] == "html_table"
    assert len(schedule["intervals"]) == 3
    assert schedule["intervals"][0]["start_at"] == "2026-11-13T09:00:00+03:00"
    assert schedule["intervals"][0]["end_at"] == "2026-11-16T09:00:00+03:00"
    assert schedule["intervals"][0]["price"] == "729000.00"
    assert schedule["intervals"][0]["extra"] == "0.00"
    assert "deposit" not in schedule["intervals"][0]
    assert schedule["current_price"] == "692550.00"
    assert schedule["min_price"] == "656100.00"


def test_parse_eight_column_table_with_header():
    schedule = parse_price_schedule(TABLE_8, now=NOW)
    assert schedule["format"] == "html_table"
    assert len(schedule["intervals"]) == 2

    first = schedule["intervals"][0]
    assert first["start_at"] == "2026-11-16T10:00:00+03:00"
    assert first["end_at"] == "2026-11-23T10:00:00+03:00"
    assert first["application_start_at"] == "2026-11-16T10:00:00+03:00"
    assert first["application_end_at"] == "2026-11-23T10:00:00+03:00"
    assert first["price"] == "27000.00"
    assert first["deposit"] == "2700.00"
    assert first["reduction"] == "0,00"

    assert schedule["current_price"] == "27000.00"
    assert schedule["min_price"] == "25650.00"


def test_parse_br_text():
    schedule = parse_price_schedule(BR_TEXT, now=NOW)
    assert schedule["format"] == "br_text"
    assert len(schedule["intervals"]) == 3
    assert schedule["intervals"][0]["start_at"] == "2026-11-23T00:00:00+03:00"
    assert schedule["intervals"][0]["price"] == "255645.00"
    assert schedule["current_price"] == "255645.00"
    assert schedule["min_price"] == "216315.00"


def test_plain_text_has_no_intervals():
    schedule = parse_price_schedule(PLAIN_TEXT, now=NOW)
    assert schedule["format"] == "text"
    assert schedule["intervals"] == []
    assert schedule["current_price"] is None
    assert schedule["min_price"] is None
    assert schedule["text"] == PLAIN_TEXT


def test_empty_value():
    schedule = parse_price_schedule(None, now=NOW)
    assert schedule == {
        "format": "none",
        "intervals": [],
        "current_price": None,
        "min_price": None,
        "text": None,
    }


def test_normalize_lot_fills_current_and_min_price():
    lot = normalize_lot(
        {
            "number": 1,
            "status": {"code": "BiddingDeclared", "name": "Объявлены торги"},
            "startPrice": 729000.0,
            "priceReduction": TABLE_4,
            "classifiers": ["Права требования"],
            "tradeObject": "Дебиторская задолженность",
        },
        trade_guid="trade-1",
        ordinal=1,
        is_public_offer=True,
    )
    schedule = json.loads(lot["price_reduction_json"])
    assert schedule["format"] == "html_table"
    assert lot["current_price"] == schedule["current_price"]
    assert lot["min_price"] == "656100.00"

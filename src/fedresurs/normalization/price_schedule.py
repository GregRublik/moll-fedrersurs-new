from __future__ import annotations

import re
from datetime import datetime
from decimal import Decimal, InvalidOperation
from html.parser import HTMLParser

from fedresurs.normalization.html_text import money, strip_html
from fedresurs.timeutil import MSK, parse_dt

_DATE_RE = re.compile(r"^\s*\d{2}\.\d{2}\.\d{4}(\s+\d{2}:\d{2}(:\d{2})?)?\s*$")
_MONEY_RE = re.compile(r"^\s*[\d\s\xa0]+(?:[.,]\d+)?\s*(?:руб\.?|₽)?\s*$", re.IGNORECASE)
_BR_RE = re.compile(r"<br\s*/?>", re.IGNORECASE)
_LINE_RE = re.compile(
    r"^(?P<date>\d{2}\.\d{2}\.\d{4}\s+\d{2}:\d{2}(?::\d{2})?)\s*:\s*(?P<price>.+)$"
)

_HEADERS = {
    "start_at": ("дата начала интервала", "начало интервала"),
    "end_at": ("дата окончания интервала", "окончание интервала"),
    "application_start_at": ("дата начала приема заявок", "начало приема заявок"),
    "application_end_at": ("дата окончания приема заявок", "окончание приема заявок"),
    "price": ("цена на интервале", "цена"),
    "deposit": ("задаток",),
    "reduction": ("величина снижения", "снижение"),
    "comment": ("комментарий",),
}


class _TableParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[list[str]] = []
        self._row: list[str] | None = None
        self._cell: list[str] | None = None

    def handle_starttag(self, tag: str, attrs) -> None:
        tag = tag.lower()
        if tag == "tr":
            self._row = []
        elif tag in ("td", "th"):
            self._cell = []
        elif tag == "br" and self._cell is not None:
            self._cell.append(" ")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag == "tr" and self._row is not None:
            cells = [cell.strip() for cell in self._row if cell.strip()]
            if cells:
                self.rows.append(cells)
            self._row = None
        elif tag in ("td", "th") and self._cell is not None:
            if self._row is not None:
                self._row.append("".join(self._cell))
            self._cell = None

    def handle_data(self, data: str) -> None:
        if self._cell is not None:
            self._cell.append(data)


def _parse_money(value: str | None) -> str | None:
    if not value:
        return None
    text = value.replace("\xa0", " ").replace(" ", "").replace("₽", "")
    text = re.sub(r"(?i)руб\.?$", "", text).strip().replace(",", ".")
    if not text or not re.search(r"\d", text):
        return None
    try:
        Decimal(text)
    except InvalidOperation:
        return None
    return money(text)


def _is_date(value: str) -> bool:
    return bool(_DATE_RE.match(value or ""))


def _is_money(value: str) -> bool:
    return bool(_MONEY_RE.match(value or "")) and bool(re.search(r"\d", value or ""))


def _parse_date(value: str | None) -> str | None:
    if not value:
        return None
    try:
        parsed = parse_dt(value.strip())
    except ValueError:
        return None
    return parsed.isoformat() if parsed else None


def _header_index(header: list[str], key: str) -> int | None:
    patterns = _HEADERS[key]
    for index, cell in enumerate(header):
        low = (cell or "").lower().replace("ё", "е")
        if any(pattern in low for pattern in patterns):
            return index
    return None


def _looks_like_header(row: list[str]) -> bool:
    letters = sum(1 for cell in row if re.search(r"[А-Яа-яA-Za-z]", cell or ""))
    dates = sum(1 for cell in row if _is_date(cell))
    return letters >= 2 and dates == 0


def _interval_from_row(row: list[str], header: list[str] | None) -> dict | None:
    if header:
        def cell(key: str) -> str | None:
            index = _header_index(header, key)
            return row[index] if index is not None and index < len(row) else None

        price = _parse_money(cell("price"))
        if price is None:
            money_cells = [(i, _parse_money(value)) for i, value in enumerate(row) if _is_money(value)]
            money_cells = [(i, value) for i, value in money_cells if value]
            if not money_cells:
                return None
            price = max(money_cells, key=lambda item: Decimal(item[1]))[1]

        interval = {
            "start_at": _parse_date(cell("start_at")),
            "end_at": _parse_date(cell("end_at")),
            "application_start_at": _parse_date(cell("application_start_at")),
            "application_end_at": _parse_date(cell("application_end_at")),
            "price": price,
            "deposit": _parse_money(cell("deposit")),
            "reduction": cell("reduction"),
            "comment": cell("comment"),
        }
        return {key: value for key, value in interval.items() if value not in (None, "")}

    dates = [value for value in (_parse_date(cell) for cell in row) if value]
    money_cells = [(index, value) for index, value in enumerate(row) if _is_money(value)]
    money_cells = [(index, _parse_money(value)) for index, value in money_cells]
    money_cells = [(index, value) for index, value in money_cells if value]
    if not money_cells:
        return None

    price_index, price = max(money_cells, key=lambda item: Decimal(item[1]))
    extras = [value for index, value in money_cells if index != price_index and value != price]
    interval = {
        "start_at": dates[0] if dates else None,
        "end_at": dates[1] if len(dates) > 1 else None,
        "price": price,
    }
    if extras:
        # The 4th column of the compact table is not labelled; do not guess
        # whether it is a deposit or a reduction value.
        interval["extra"] = extras[0]
    return {key: value for key, value in interval.items() if value not in (None, "")}


def _current_price(intervals: list[dict], now: datetime) -> str | None:
    priced = [item for item in intervals if item.get("price")]
    if not priced:
        return None

    for item in priced:
        start = parse_dt(item.get("start_at"))
        end = parse_dt(item.get("end_at"))
        if start and end and start <= now <= end:
            return item["price"]
        if start and not end and start <= now:
            return item["price"]

    started = [item for item in priced if (parse_dt(item.get("start_at")) or now) <= now]
    if started:
        return started[-1]["price"]
    return priced[0]["price"]


def _min_price(intervals: list[dict]) -> str | None:
    prices = []
    for item in intervals:
        try:
            prices.append(Decimal(item["price"]))
        except (KeyError, InvalidOperation):
            continue
    return format(min(prices), "f") if prices else None


def _parse_table(value: str, now: datetime) -> dict:
    parser = _TableParser()
    try:
        parser.feed(value)
    except Exception:  # noqa: BLE001
        pass

    rows = parser.rows
    header = rows[0] if rows and _looks_like_header(rows[0]) else None
    data_rows = rows[1:] if header else rows

    intervals = []
    for row in data_rows:
        interval = _interval_from_row(row, header)
        if interval and interval.get("price"):
            intervals.append(interval)

    if not intervals:
        return _parse_plain(value)

    return {
        "format": "html_table",
        "intervals": intervals,
        "current_price": _current_price(intervals, now),
        "min_price": _min_price(intervals),
        "text": None,
    }


def _parse_br(value: str, now: datetime) -> dict:
    intervals = []
    lines = []
    for chunk in _BR_RE.split(value):
        plain = strip_html(chunk)
        if not plain:
            continue
        lines.append(plain)
        match = _LINE_RE.match(plain)
        if not match:
            continue
        start = _parse_date(match.group("date"))
        price = _parse_money(match.group("price"))
        if start and price:
            intervals.append({"start_at": start, "price": price})

    if not intervals:
        return _parse_plain(value)

    return {
        "format": "br_text",
        "intervals": intervals,
        "current_price": _current_price(intervals, now),
        "min_price": _min_price(intervals),
        "text": "; ".join(lines),
    }


def _parse_plain(value: str) -> dict:
    return {
        "format": "text",
        "intervals": [],
        "current_price": None,
        "min_price": None,
        "text": strip_html(value) or value,
    }


def parse_price_schedule(value: str | None, now: datetime | None = None) -> dict:
    """Parse lot.priceReduction into intervals, current and minimum price.

    Supported shapes seen on the portal:
      - 4/8-column HTML tables (with or without a header row);
      - <br/>-separated "dd.mm.yyyy hh:mm: price" lines;
      - free text explaining the reduction rule.
    """
    if not value or not str(value).strip():
        return {
            "format": "none",
            "intervals": [],
            "current_price": None,
            "min_price": None,
            "text": None,
        }

    text = str(value).strip()
    moment = now or datetime.now(MSK)

    if "<table" in text.lower():
        return _parse_table(text, moment)
    if _BR_RE.search(text):
        return _parse_br(text, moment)
    return _parse_plain(text)

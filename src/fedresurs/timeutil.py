from __future__ import annotations

from datetime import datetime, timezone, timedelta

MSK = timezone(timedelta(hours=3))

# Formats seen in the portal API and in .NET serializers.
_DT_FORMATS = (
    "%Y-%m-%dT%H:%M:%S.%f",
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%dT%H:%M:%S.%f%z",
    "%Y-%m-%dT%H:%M:%S%z",
    "%d.%m.%Y %H:%M:%S",
    "%d.%m.%Y %H:%M",
    "%d.%m.%Y",
    "%Y-%m-%d",
)


def parse_dt(value: str | datetime | None) -> datetime | None:
    """Parse a portal date into an aware MSK datetime.

    Naive values are treated as Moscow time: the portal publishes local time
    without an offset.
    """
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        text = value.strip()
        dt = None
        try:
            dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            for fmt in _DT_FORMATS:
                try:
                    dt = datetime.strptime(text, fmt)
                    break
                except ValueError:
                    continue
        if dt is None:
            raise ValueError(f"unsupported datetime: {value!r}")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=MSK)
    return dt.astimezone(MSK)


def to_msk_iso(value: str | datetime | None) -> str | None:
    dt = parse_dt(value)
    return dt.isoformat() if dt else None


def now_msk() -> datetime:
    return datetime.now(MSK)


def date_only(value: str | datetime | None) -> str | None:
    dt = parse_dt(value)
    return dt.date().isoformat() if dt else None

from __future__ import annotations

from datetime import date, datetime, timedelta

from fedresurs.timeutil import MSK, parse_dt


def day_segments(date_from: str, date_to: str) -> list[tuple[str, str]]:
    """Split an inclusive date range into [day, day+1) segments."""
    start = parse_dt(date_from)
    end = parse_dt(date_to)
    if start is None or end is None:
        raise ValueError("date_from and date_to are required")
    if start > end:
        raise ValueError("date_from must be <= date_to")

    segments: list[tuple[str, str]] = []
    cursor = start.date()
    last = end.date()
    while cursor <= last:
        segments.append((cursor.isoformat(), (cursor + timedelta(days=1)).isoformat()))
        cursor += timedelta(days=1)
    return segments


def plan_feed(
    *,
    now: datetime | None = None,
    lookback_hours: int = 48,
    lookahead_days: int = 14,
    overlap_hours: int = 24,
) -> tuple[str, str]:
    """One feed window covering late publications and upcoming trades."""
    current = now or datetime.now(MSK)
    start = current - timedelta(hours=lookback_hours)
    end = current + timedelta(days=lookahead_days)
    return start.date().isoformat(), end.date().isoformat()


def split_window(date_from: str, date_to: str) -> list[tuple[str, str]]:
    """Halve a window; used when the source hits its 10000-result cap."""
    start = date.fromisoformat(date_from)
    end = date.fromisoformat(date_to)
    if start >= end:
        return [(date_from, date_to)]
    middle = start + (end - start) / 2
    left = middle.isoformat() if middle != start else date_from
    return [(date_from, left), (left, date_to)]

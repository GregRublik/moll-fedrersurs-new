from __future__ import annotations

import tomllib
from pathlib import Path

from fedresurs.timeutil import date_only, parse_dt, to_msk_iso

ROOT = Path(__file__).resolve().parents[1]


def test_parse_naive_portal_datetime_as_msk():
    dt = parse_dt("2026-11-10T12:00:00")
    assert dt is not None
    assert dt.isoformat() == "2026-11-10T12:00:00+03:00"


def test_parse_datetime_with_millis_and_offset():
    dt = parse_dt("2026-11-09T13:10:05.45")
    assert dt is not None
    assert to_msk_iso(dt) == "2026-11-09T13:10:05.450000+03:00"


def test_date_only():
    assert date_only("2026-11-10T12:00:00") == "2026-11-10"


def test_field_map_matches_discovered_type_ids():
    data = tomllib.loads((ROOT / "config" / "bitrix_fieldmap.toml").read_text(encoding="utf-8"))

    assert data["trade"]["entity_type_id"] == 1078
    assert data["trade"]["crm_type_id"] == 138
    assert data["trade"]["category_id"] == 179
    assert len(data["trade"]["fields"]) == 43

    assert data["lot"]["entity_type_id"] == 1120
    assert data["lot"]["crm_type_id"] == 148
    assert data["lot"]["category_id"] == 180
    assert data["lot"]["parent_field"] == "parentId1078"
    assert len(data["lot"]["fields"]) == 21

    for section in ("trade", "lot"):
        prefix = f"UF_CRM_{data[section]['crm_type_id']}_"
        values = list(data[section]["fields"].values())
        assert len(values) == len(set(values))
        assert all(value.startswith(prefix) for value in values), section

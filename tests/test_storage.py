from __future__ import annotations

import json

import pytest

from fedresurs.storage.repositories import (
    BiddingRepo,
    BitrixMapRepo,
    LockRepo,
    LotRepo,
    SyncJobRepo,
    WindowRepo,
)


def bidding_data(guid: str = "trade-1", content_hash: str = "hash-1", **overrides):
    data = {
        "guid": guid,
        "number": "6079",
        "trade_type_code": "PublicOffer",
        "trade_type_name": "Публичное предложение",
        "status": "Открыт прием заявок",
        "is_rebidding": 0,
        "debtor_name": "Должник",
        "debtor_inn": "7700000000",
        "case_number": "А70-3961/2026",
        "platform_name": "АУКЦИОНПРО",
        "trade_start_at": "2026-11-10T12:00:00+03:00",
        "trade_end_at": "2026-12-30T12:00:00+03:00",
        "source_url": f"https://fedresurs.ru/biddings/{guid}",
        "is_candidate": 1,
        "source_state": "active",
        "content_hash": content_hash,
        "normalized_json": json.dumps({"number": "6079", "status": "open"}, sort_keys=True),
    }
    data.update(overrides)
    return data


def lot_data(trade_guid: str = "trade-1", lot_key: str = "trade-1:1", content_hash: str = "lhash-1", **overrides):
    data = {
        "trade_guid": trade_guid,
        "lot_number": "1",
        "ordinal": 1,
        "lot_key": lot_key,
        "status_code": "ApplicationSessionStarted",
        "start_price": "30000.00",
        "deposit": "10",
        "classifiers_json": json.dumps(["Права требования"], ensure_ascii=False),
        "content_hash": content_hash,
        "normalized_json": json.dumps({"lot_number": "1", "start_price": "30000.00"}, sort_keys=True),
    }
    data.update(overrides)
    return data


async def test_bidding_upsert_is_idempotent(db):
    repo = BiddingRepo(db)

    first = await repo.upsert(bidding_data())
    assert first.is_new is True
    assert first.changed is True

    second = await repo.upsert(bidding_data())
    assert second.is_new is False
    assert second.changed is False

    rows = await db.fetchall("SELECT COUNT(*) AS cnt FROM biddings")
    assert rows[0]["cnt"] == 1


async def test_bidding_update_records_version_and_changed_fields(db):
    repo = BiddingRepo(db)
    await repo.upsert(bidding_data())

    updated = bidding_data(
        content_hash="hash-2",
        normalized_json=json.dumps({"number": "6079", "status": "closed"}, sort_keys=True),
        status="Завершенные",
    )
    result = await repo.upsert(updated)
    assert result.changed is True
    assert "status" in result.changed_fields

    versions = await db.fetchall("SELECT version_no FROM entity_versions ORDER BY version_no")
    assert [row["version_no"] for row in versions] == [1, 2]

    row = await repo.get("trade-1")
    assert row["status"] == "Завершенные"
    assert row["sync_status"] == "pending"


async def test_lot_upsert_by_lot_key_and_trade_link(db):
    await BiddingRepo(db).upsert(bidding_data())
    lots = LotRepo(db)

    first = await lots.upsert(lot_data())
    assert first.is_new is True

    second = await lots.upsert(lot_data())
    assert second.changed is False

    by_key = await lots.get("trade-1:1")
    assert by_key["trade_guid"] == "trade-1"

    by_trade = await lots.list_by_trade("trade-1")
    assert len(by_trade) == 1


async def test_lot_requires_existing_trade(db):
    with pytest.raises(Exception):
        await LotRepo(db).upsert(lot_data(trade_guid="missing"))


async def test_window_get_or_create_is_idempotent(db):
    repo = WindowRepo(db)

    first = await repo.get_or_create(
        kind="feed", date_from="2026-11-01", date_to="2026-11-02", filter_hash="f1"
    )
    second = await repo.get_or_create(
        kind="feed", date_from="2026-11-01", date_to="2026-11-02", filter_hash="f1"
    )
    assert first == second

    child = await repo.get_or_create(
        kind="feed",
        date_from="2026-11-01",
        date_to="2026-11-02",
        filter_hash="f1",
        parent_window_id=first,
        depth=1,
    )
    assert child != first


async def test_sync_job_dedup_and_dependency(db):
    repo = SyncJobRepo(db)

    trade_job = await repo.enqueue(
        entity_type="bidding", entity_key="trade-1", operation="create", payload_hash="p1"
    )
    same = await repo.enqueue(
        entity_type="bidding", entity_key="trade-1", operation="create", payload_hash="p1"
    )
    assert trade_job == same

    lot_job = await repo.enqueue(
        entity_type="lot",
        entity_key="trade-1:1",
        operation="create",
        payload_hash="p2",
        depends_on_job_id=trade_job,
    )

    ready = await repo.claim_ready()
    assert [row["id"] for row in ready] == [trade_job]

    await repo.complete(trade_job, bitrix_id=100)
    ready = await repo.claim_ready()
    assert [row["id"] for row in ready] == [lot_job]


async def test_bitrix_id_map_and_lock(db):
    mapping = BitrixMapRepo(db)
    await mapping.set(
        entity_type="bidding",
        entity_key="trade-1",
        bitrix_entity_type_id=1078,
        bitrix_id=42,
        xml_id="fdrs:1078:trade-1",
    )
    assert (await mapping.get("bidding", "trade-1"))["bitrix_id"] == 42

    locks = LockRepo(db)
    assert await locks.acquire("collect", "owner-a") is True
    assert await locks.acquire("collect", "owner-b") is False
    await locks.release("collect", "owner-a")
    assert await locks.acquire("collect", "owner-b") is True

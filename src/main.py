"""CLI entry point for the fedresurs collector."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import tomllib
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import aiohttp

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from config import settings  # noqa: E402
from fedresurs.bitrix.client import BitrixClient  # noqa: E402
from fedresurs.bitrix.fields import FieldMap  # noqa: E402
from fedresurs.bitrix.sync import BitrixSyncService  # noqa: E402
from fedresurs.browser.factory import config_from_settings, make_launcher  # noqa: E402
from fedresurs.browser.session import PortalSession  # noqa: E402
from fedresurs.browser.transport import PageTransport  # noqa: E402
from fedresurs.filtering.rules import FilterConfig  # noqa: E402
from fedresurs.logging import setup_logging  # noqa: E402
from fedresurs.pipeline.collect import (  # noqa: E402
    fetch_type_codes,
    run_collect,
    run_collect_recent,
    run_details,
)
from fedresurs.portal import endpoints  # noqa: E402
from fedresurs.portal.client import PortalClient, PortalHttpError  # noqa: E402
from fedresurs.portal.parsers import extract_page  # noqa: E402
from fedresurs.storage.db import Database, open_database  # noqa: E402
from fedresurs.storage.repositories import (  # noqa: E402
    BiddingRepo,
    BitrixMapRepo,
    ErrorRepo,
    LotRepo,
    RunRepo,
)

try:  # optional runtime dependency, already declared in pyproject
    import aiosqlite  # noqa: F401
except ImportError:  # pragma: no cover
    pass


async def cmd_init_db(args: argparse.Namespace) -> int:
    db = await open_database()
    try:
        version = await db.schema_version()
        print(f"database: {db.path}")
        print(f"schema version: {version}")
    finally:
        await db.close()
    return 0


async def cmd_doctor(args: argparse.Namespace) -> int:
    problems = 0

    print("== settings ==")
    print(f"portal: {settings.portal.base_url} (mode={settings.portal.launch_mode})")
    print(f"bitrix portal: {urlparse(settings.bitrix.base_url).netloc}")
    print(f"bitrix entities: trade={settings.bitrix.entity_trade}, lot={settings.bitrix.entity_lot}")
    print(f"bitrix categories: trade={settings.bitrix.category_trade}, lot={settings.bitrix.category_lot}")
    print(f"bitrix write_enabled={settings.bitrix.write_enabled} dry_run={settings.bitrix.dry_run}")
    print(f"db: {settings.app.db_path}")

    print("\n== field map ==")
    field_map_path = Path(settings.app.field_map_path)
    if not field_map_path.exists():
        print(f"  MISSING: {field_map_path}")
        problems += 1
    else:
        data = tomllib.loads(field_map_path.read_text(encoding="utf-8"))
        for key in ("trade", "lot"):
            section = data.get(key)
            if not section:
                print(f"  MISSING section [{key}]")
                problems += 1
                continue
            fields = section.get("fields", {})
            print(
                f"  {key}: entity={section.get('entity_type_id')} "
                f"category={section.get('category_id')} fields={len(fields)}"
            )
            if section.get("entity_type_id") != getattr(settings.bitrix, f"entity_{key}"):
                print(f"  WARN: {key} entityTypeId differs from settings")
                problems += 1
            if section.get("category_id") != getattr(settings.bitrix, f"category_{key}"):
                print(f"  WARN: {key} categoryId differs from settings")
                problems += 1
        if not data.get("lot", {}).get("parent_field"):
            print("  WARN: lot.parent_field is not set")
            problems += 1

    print("\n== database ==")
    db_path = Path(settings.app.db_path)
    if not db_path.exists():
        print(f"  not initialized: {db_path} (run: init-db)")
        problems += 1
    else:
        db = Database(db_path)
        await db.connect()
        try:
            version = await db.schema_version()
            windows = await db.fetchone("SELECT COUNT(*) AS cnt FROM collection_windows")
            biddings = await db.fetchone("SELECT COUNT(*) AS cnt FROM biddings")
            lots = await db.fetchone("SELECT COUNT(*) AS cnt FROM lots")
            jobs = await db.fetchone("SELECT COUNT(*) AS cnt FROM sync_jobs WHERE status = 'pending'")
            print(f"  schema={version} windows={windows['cnt']} biddings={biddings['cnt']} "
                  f"lots={lots['cnt']} pending_jobs={jobs['cnt']}")
        finally:
            await db.close()

    if args.network:
        print("\n== bitrix (network) ==")
        problems += await _bitrix_doctor()

    print(f"\nproblems: {problems}")
    return 0 if problems == 0 else 1


async def _bitrix_call(session: aiohttp.ClientSession, method: str, payload: dict) -> dict:
    url = f"{settings.bitrix.webhook_base}/{method}.json"
    async with session.post(url, json=payload, timeout=aiohttp.ClientTimeout(total=30)) as resp:
        data = await resp.json(content_type=None)
        if resp.status != 200 or data.get("error"):
            raise RuntimeError(
                f"{method}: HTTP {resp.status}, error={data.get('error')!r}, "
                f"description={data.get('error_description')!r}"
            )
        return data


async def _bitrix_doctor() -> int:
    problems = 0
    async with aiohttp.ClientSession() as session:
        for entity_type_id, key in (
            (settings.bitrix.entity_trade, "trade"),
            (settings.bitrix.entity_lot, "lot"),
        ):
            try:
                response = await _bitrix_call(
                    session, "crm.type.getByEntityTypeId", {"entityTypeId": entity_type_id}
                )
                type_info = response["result"]["type"]
                print(f"  {entity_type_id}: type.id={type_info.get('id')} title={type_info.get('title')!r}")
            except Exception as exc:  # noqa: BLE001
                print(f"  {entity_type_id}: FAILED — {exc}")
                problems += 1
                continue
            try:
                cats = await _bitrix_call(session, "crm.category.list", {"entityTypeId": entity_type_id})
                ids = [c.get("id") for c in cats.get("result", {}).get("categories", [])]
                expected = getattr(settings.bitrix, f"category_{key}")
                print(f"    categories={ids} expected={expected}")
                if expected not in ids:
                    print(f"    WARN: expected category {expected} not found")
                    problems += 1
            except Exception as exc:  # noqa: BLE001
                print(f"    crm.category.list FAILED — {exc}")
                problems += 1
    return problems


async def cmd_probe(args: argparse.Namespace) -> int:
    """Check portal availability from this host and measure Qrator behaviour."""
    import time

    launch_config = config_from_settings()
    launcher = make_launcher(launch_config.mode)
    db = await open_database()
    report: dict = {
        "launch_mode": launch_config.mode,
        "base_url": settings.portal.base_url,
        "checks": [],
        "burst": {},
    }
    problems = 0
    handle = None

    try:
        print(f"launching browser (mode={launch_config.mode}) ...")
        handle = await launcher.start(launch_config)
        transport = PageTransport(handle.page)
        session = PortalSession(handle, transport, settings.portal.base_url)

        await session.ensure_alive()
        expires = await session.cookie_expires_at()
        ttl = (expires - datetime.now(timezone.utc)).total_seconds() if expires else None
        report["qrator_cookie_ttl_s"] = int(ttl) if ttl is not None else None
        print(f"session alive; qrator cookie TTL: {report['qrator_cookie_ttl_s']} s")

        client = PortalClient(
            transport,
            db,
            session,
            min_interval_ms=settings.portal.min_interval_ms,
            jitter_ms=settings.portal.jitter_ms,
            max_retries=2,
            block_cooldown_s=5,
        )

        checks = [
            ("bidding-types", endpoints.bidding_types()),
            ("regions", endpoints.regions()),
            ("biddings", endpoints.biddings(limit=1, offset=0)),
            ("account-receivables", endpoints.account_receivables(limit=1)),
        ]
        for name, path in checks:
            started = time.monotonic()
            try:
                payload = await client.get(path)
                latency = int((time.monotonic() - started) * 1000)
                items, found = extract_page(payload) if isinstance(payload, dict) and "pageData" in payload else (payload if isinstance(payload, list) else [], None)
                check = {
                    "name": name,
                    "ok": True,
                    "latency_ms": latency,
                    "items": len(items) if isinstance(items, list) else None,
                    "found": found,
                }
                print(f"  {name}: ok, latency={latency} ms, items={check['items']}, found={found}")
            except PortalHttpError as exc:
                latency = int((time.monotonic() - started) * 1000)
                check = {"name": name, "ok": False, "error": str(exc), "latency_ms": latency}
                print(f"  {name}: FAILED — {exc}")
                problems += 1
            report["checks"].append(check)

        print(f"\nburst: {args.requests} requests ...")
        statuses: list[str] = []
        latencies: list[int] = []
        for index in range(args.requests):
            started = time.monotonic()
            try:
                await client.get(endpoints.biddings(limit=1, offset=index))
                statuses.append("ok")
            except PortalHttpError as exc:
                statuses.append(type(exc).__name__)
            latencies.append(int((time.monotonic() - started) * 1000))

        report["burst"] = {
            "requests": len(statuses),
            "ok": statuses.count("ok"),
            "errors": {name: statuses.count(name) for name in set(statuses) if name != "ok"},
            "avg_latency_ms": sum(latencies) // len(latencies) if latencies else None,
            "max_latency_ms": max(latencies) if latencies else None,
        }
        print(json.dumps(report["burst"], ensure_ascii=False))

        out = Path("var/probe.json")
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\nreport saved: {out}")
        print(f"problems: {problems}")
        return 0 if problems == 0 else 1

    finally:
        if handle is not None:
            await launcher.stop()
        await db.close()


async def cmd_collect(args: argparse.Namespace) -> int:
    """Discover biddings for a date range and store them in SQLite."""
    launch_config = config_from_settings()
    launcher = make_launcher(launch_config.mode)
    db = await open_database()
    handle = None
    run_repo = RunRepo(db)
    run_id: int | None = None

    try:
        filter_config = FilterConfig.load(settings.app.filter_config_path)
        run_id = await run_repo.start(
            "collect", mode=args.trade_type, config_hash=filter_config.version
        )

        print(f"launching browser (mode={launch_config.mode}) ...")
        handle = await launcher.start(launch_config)
        transport = PageTransport(handle.page)
        session = PortalSession(handle, transport, settings.portal.base_url)
        await session.ensure_alive()

        client = PortalClient(
            transport,
            db,
            session,
            min_interval_ms=settings.portal.min_interval_ms,
            jitter_ms=settings.portal.jitter_ms,
            max_retries=settings.portal.max_retries,
            block_cooldown_s=60,
            run_id=run_id,
        )

        type_codes = await fetch_type_codes(client)
        print(f"trade types: {type_codes}")

        if bool(args.date_from) != bool(args.date_to):
            print("--from and --to must be passed together")
            return 2

        if args.date_from and args.date_to:
            result = await run_collect(
                client=client,
                db=db,
                filter_config=filter_config,
                type_codes=type_codes,
                date_from=args.date_from,
                date_to=args.date_to,
                trade_type=args.trade_type,
                max_pages=args.max_pages,
                page_size=args.page_size,
                run_id=run_id,
            )
        else:
            result = await run_collect_recent(
                client=client,
                db=db,
                filter_config=filter_config,
                type_codes=type_codes,
                lookback_hours=args.lookback_hours,
                trade_type=args.trade_type,
                max_pages=args.max_pages,
                page_size=args.page_size,
                run_id=run_id,
            )

        details_stats = None
        if args.details_limit:
            details_stats = await run_details(
                client=client,
                db=db,
                filter_config=filter_config,
                limit=args.details_limit,
                run_id=run_id,
            )

        biddings = await db.fetchone("SELECT COUNT(*) AS cnt FROM biddings")
        candidates = await db.fetchone("SELECT COUNT(*) AS cnt FROM biddings WHERE is_candidate = 1")
        lots = await db.fetchone("SELECT COUNT(*) AS cnt FROM lots")
        stats = {
            "window_id": result.window_id,
            "found": result.found,
            "collected": result.collected,
            "known": result.known,
            "pages": result.pages,
            "outcome": result.outcome,
            "biddings_total": biddings["cnt"],
            "candidates_total": candidates["cnt"],
            "lots_total": lots["cnt"],
            "details": details_stats,
            "requests": client.request_count,
        }
        await run_repo.finish(run_id, stats=stats)

        print(json.dumps(stats, ensure_ascii=False, indent=2))
        return 0 if result.outcome in ("ok", "no_data", "truncated") else 1

    finally:
        if handle is not None:
            await launcher.stop()
        await db.close()


async def cmd_sync(args: argparse.Namespace) -> int:
    """Push pending biddings/lots to Bitrix24 (dry-run by default)."""
    db = await open_database()
    try:
        field_map = FieldMap.load(
            settings.app.field_map_path,
            discovery_dir=ROOT / "var" / "discovery",
        )
        async with aiohttp.ClientSession() as session:
            client = BitrixClient(
                session,
                settings.bitrix.webhook_base,
                rps=settings.bitrix.rps,
            )
            service = BitrixSyncService(
                client=client,
                field_map=field_map,
                bidding_repo=BiddingRepo(db),
                lot_repo=LotRepo(db),
                map_repo=BitrixMapRepo(db),
                error_repo=ErrorRepo(db),
                dry_run=not args.write or settings.bitrix.dry_run,
                write_enabled=settings.bitrix.write_enabled,
            )
            stats = await service.sync_pending(args.limit)
            stats["requests"] = client.request_count
            stats["dry_run_mode"] = service.dry_run
            stats["write_enabled"] = settings.bitrix.write_enabled
        print(json.dumps(stats, ensure_ascii=False, indent=2))
        return 0 if stats["errors"] == 0 else 1
    finally:
        await db.close()


def _not_implemented(name: str) -> int:
    print(f"'{name}' is not implemented yet (next stages: portal, filtering, bitrix sync).")
    return 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="fedresurs", description="Fedresurs trade collector")
    parser.add_argument("--log-level", default=None)
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("init-db", help="create or migrate the SQLite database")
    doctor = sub.add_parser("doctor", help="check settings, field map, database and Bitrix")
    doctor.add_argument("--network", action="store_true", help="also call Bitrix24")

    probe = sub.add_parser("probe", help="check portal availability and Qrator behaviour")
    probe.add_argument("--requests", type=int, default=10, help="burst size (default: 10)")

    collect = sub.add_parser("collect", help="discover biddings (recent by default)")
    collect.add_argument("--from", dest="date_from", default=None, help="trade-period window start (optional)")
    collect.add_argument("--to", dest="date_to", default=None, help="trade-period window end (optional)")
    collect.add_argument(
        "--lookback-hours",
        type=int,
        default=24,
        help="recent mode: stop once records older than this are reached (default: 24)",
    )
    collect.add_argument("--trade-type", default=None, help="portal tradeType code, e.g. PublicOffer")
    collect.add_argument("--max-pages", type=int, default=None)
    collect.add_argument("--page-size", type=int, default=15, help="portal page size (15 is SPA-safe)")
    collect.add_argument(
        "--details-limit",
        type=int,
        default=0,
        help="after discovery, fetch card/lots/messages for N candidates (default: 0)",
    )

    sync = sub.add_parser("sync", help="push pending items to Bitrix24 (dry-run by default)")
    sync.add_argument("--limit", type=int, default=50)
    sync.add_argument(
        "--write",
        action="store_true",
        help="actually write; still requires BITRIX_WRITE_ENABLED=true",
    )

    for name in ("refresh", "verify", "report", "refilter"):
        sub.add_parser(name, help=f"{name} (not implemented yet)")

    return parser


async def async_main(args: argparse.Namespace) -> int:
    if args.command == "init-db":
        return await cmd_init_db(args)
    if args.command == "doctor":
        return await cmd_doctor(args)
    if args.command == "probe":
        return await cmd_probe(args)
    if args.command == "collect":
        return await cmd_collect(args)
    if args.command == "sync":
        return await cmd_sync(args)
    return _not_implemented(args.command)


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    setup_logging(args.log_level)
    return asyncio.run(async_main(args))


if __name__ == "__main__":
    raise SystemExit(main())

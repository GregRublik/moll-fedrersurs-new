from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from fedresurs.constants import EntityType, Outcome, WindowStatus
from fedresurs.filtering.rules import FilterConfig, decide_trade
from fedresurs.normalization.bidding import normalize_bidding
from fedresurs.normalization.hashing import canonical_json
from fedresurs.portal import endpoints
from fedresurs.portal.client import PortalBlockedError, PortalClient, PortalHttpError
from fedresurs.portal.parsers import extract_page
from fedresurs.storage.db import Database
from fedresurs.storage.repositories import BiddingRepo, ErrorRepo, RawRepo, WindowRepo


@dataclass(slots=True)
class WindowResult:
    window_id: int
    found: int | None
    collected: int
    pages: int
    outcome: str
    error: str | None = None
    known: int = 0


class DiscoveryService:
    def __init__(
        self,
        *,
        client: PortalClient,
        db: Database,
        window_repo: WindowRepo,
        bidding_repo: BiddingRepo,
        raw_repo: RawRepo,
        error_repo: ErrorRepo,
        filter_config: FilterConfig,
        type_codes: dict[str, str],
        run_id: int | None = None,
        page_size: int = 15,
        cap_threshold: int = 9999,
    ) -> None:
        self.client = client
        self.db = db
        self.window_repo = window_repo
        self.bidding_repo = bidding_repo
        self.raw_repo = raw_repo
        self.error_repo = error_repo
        self.filter_config = filter_config
        self.type_codes = type_codes
        self.run_id = run_id
        self.page_size = page_size
        self.cap_threshold = cap_threshold

    async def discover_window(
        self,
        window_id: int,
        *,
        date_from: str,
        date_to: str,
        trade_type: str | None = None,
        search_string: str | None = None,
        max_pages: int | None = None,
    ) -> WindowResult:
        await self.window_repo.mark_running(window_id)

        offset = 0
        pages = 0
        found: int | None = None
        guids: set[str] = set()
        outcome = Outcome.OK

        try:
            while max_pages is None or pages < max_pages:
                path = endpoints.biddings(
                    limit=self.page_size,
                    offset=offset,
                    trade_start_date=date_from,
                    trade_end_date=date_to,
                    trade_type=trade_type,
                    search_string=search_string,
                )
                payload = await self.client.get(
                    path,
                    window_id=window_id,
                    entity_type="window",
                    entity_key=str(window_id),
                )
                await self.raw_repo.save(
                    entity_type="window",
                    entity_key=str(window_id),
                    endpoint=path,
                    payload=payload,
                    http_status=200,
                    run_id=self.run_id,
                )

                items, page_found = extract_page(payload)
                if found is None and page_found is not None:
                    found = page_found

                if not items:
                    break

                for item in items:
                    await self._store_item(window_id, item, offset, guids)

                pages += 1
                offset += len(items)

                if len(items) < self.page_size:
                    break
                if found is not None and offset >= found:
                    break

            if pages == 0 and (found is None or found == 0):
                outcome = Outcome.NO_DATA
            elif found is not None and found >= self.cap_threshold:
                outcome = Outcome.TRUNCATED
            elif found is not None and len(guids) < found:
                outcome = Outcome.INCOMPLETE
            else:
                outcome = Outcome.OK

        except PortalBlockedError as exc:
            outcome = Outcome.QRATOR_BLOCK
            await self._error(window_id, "source_blocked", str(exc))
        except PortalHttpError as exc:
            outcome = Outcome.HTTP_ERROR
            await self._error(window_id, "source_http_error", str(exc))
        except Exception as exc:  # noqa: BLE001 — the window must be closed, not lost
            outcome = Outcome.PARSE_ERROR
            await self._error(window_id, "source_parse_error", str(exc))

        status = (
            WindowStatus.DONE
            if outcome in (Outcome.OK, Outcome.NO_DATA, Outcome.TRUNCATED)
            else WindowStatus.INCOMPLETE
        )
        await self.window_repo.finish(
            window_id,
            status=str(status),
            outcome=str(outcome),
            found=found,
            collected=len(guids),
            pages=pages,
            last_offset=offset,
            error_message=None if status == WindowStatus.DONE else str(outcome),
        )
        return WindowResult(window_id, found, len(guids), pages, str(outcome))

    async def discover_recent(
        self,
        *,
        window_id: int,
        date_from: str,
        date_to: str,
        trade_type: str | None = None,
        max_pages: int | None = None,
        known_pages_to_stop: int = 2,
    ) -> WindowResult:
        """Walk the create-date-ordered feed from the newest item until we hit known records.

        The portal list is sorted by dateCreate DESC and its date params filter the
        trade period, not publication time. Therefore incremental discovery pages
        from offset 0 and stops after a couple of fully-known pages or once the
        cutoff is reached.
        """
        from fedresurs.timeutil import parse_dt

        await self.window_repo.mark_running(window_id)
        cutoff = parse_dt(date_from)
        offset = 0
        pages = 0
        found: int | None = None
        guids: set[str] = set()
        known = 0
        known_streak = 0
        oldest = None
        outcome = Outcome.OK

        try:
            while max_pages is None or pages < max_pages:
                path = endpoints.biddings(limit=self.page_size, offset=offset, trade_type=trade_type)
                payload = await self.client.get(
                    path, window_id=window_id, entity_type="window", entity_key=str(window_id)
                )
                await self.raw_repo.save(
                    entity_type="window",
                    entity_key=str(window_id),
                    endpoint=path,
                    payload=payload,
                    http_status=200,
                    run_id=self.run_id,
                )
                items, page_found = extract_page(payload)
                if found is None and page_found is not None:
                    found = page_found
                if not items:
                    break

                page_known = 0
                page_dates = []
                for item in items:
                    existed = await self._store_item(window_id, item, offset, guids)
                    if existed is True:
                        page_known += 1
                    created = parse_dt(item.get("dateCreate"))
                    if created is not None:
                        page_dates.append(created)

                known += page_known
                known_streak = known_streak + 1 if page_known == len(items) else 0
                if page_dates:
                    page_oldest = min(page_dates)
                    oldest = page_oldest if oldest is None else min(oldest, page_oldest)

                pages += 1
                offset += len(items)

                if known_streak >= known_pages_to_stop:
                    break
                if oldest is not None and cutoff is not None and oldest < cutoff:
                    break
                if len(items) < self.page_size:
                    break
                if found is not None and offset >= found:
                    break

            if max_pages is not None and pages >= max_pages:
                if oldest is None or (cutoff is not None and oldest > cutoff):
                    outcome = Outcome.TRUNCATED

        except PortalBlockedError as exc:
            outcome = Outcome.QRATOR_BLOCK
            await self._error(window_id, "source_blocked", str(exc))
        except PortalHttpError as exc:
            outcome = Outcome.HTTP_ERROR
            await self._error(window_id, "source_http_error", str(exc))
        except Exception as exc:  # noqa: BLE001
            outcome = Outcome.PARSE_ERROR
            await self._error(window_id, "source_parse_error", str(exc))

        status = (
            WindowStatus.DONE
            if outcome in (Outcome.OK, Outcome.NO_DATA, Outcome.TRUNCATED)
            else WindowStatus.INCOMPLETE
        )
        await self.window_repo.finish(
            window_id,
            status=str(status),
            outcome=str(outcome),
            found=found,
            collected=len(guids),
            pages=pages,
            last_offset=offset,
            error_message=None if status == WindowStatus.DONE else str(outcome),
        )
        return WindowResult(window_id, found, len(guids), pages, str(outcome), known=known)

    async def _store_item(
        self, window_id: int, item: dict[str, Any], offset: int, guids: set[str]
    ) -> bool | None:
        try:
            data = normalize_bidding(item, self.type_codes)
        except Exception as exc:  # noqa: BLE001
            await self._error(window_id, "validation_error", str(exc), item=item)
            return None

        existed = await self.bidding_repo.get(data["guid"]) is not None
        decision = decide_trade(data.get("trade_type_code"), self.filter_config)
        data["is_candidate"] = int(decision.decision == "include")
        data["match_score"] = decision.score
        data["match_reasons_json"] = canonical_json(decision.reasons)
        data["filter_version"] = self.filter_config.version
        data["classification_source"] = str(decision.source)

        try:
            await self.bidding_repo.upsert(data)
            await self.window_repo.add_sighting(window_id, data["guid"], offset)
            guids.add(data["guid"])
            return existed
        except Exception as exc:  # noqa: BLE001
            await self._error(window_id, "validation_error", str(exc), item=item)
            return None

    async def _error(
        self,
        window_id: int,
        error_type: str,
        message: str,
        item: dict[str, Any] | None = None,
    ) -> None:
        try:
            await self.error_repo.add(
                error_type=error_type,
                message=message,
                stage="discovery",
                run_id=self.run_id,
                window_id=window_id,
                entity_type=EntityType.BIDDING if item else None,
                entity_key=(item or {}).get("guid"),
                context=item,
            )
        except Exception:  # noqa: BLE001
            pass

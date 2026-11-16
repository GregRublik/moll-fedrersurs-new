from __future__ import annotations

import json

from fedresurs.filtering.rules import FilterConfig, decide_lot
from fedresurs.normalization.hashing import canonical_json
from fedresurs.storage.db import Database
from fedresurs.storage.repositories import LotRepo


async def refilter_lots(
    db: Database, config: FilterConfig, *, dry_run: bool = False
) -> dict[str, int]:
    rows = await db.fetchall("SELECT * FROM lots")
    repo = LotRepo(db)
    stats = {
        "total": len(rows),
        "changed": 0,
        "included": 0,
        "excluded": 0,
        "reviewed": 0,
        "newly_include": 0,
        "newly_exclude": 0,
    }

    for row in rows:
        try:
            classifiers = json.loads(row["classifiers_json"] or "[]")
        except json.JSONDecodeError:
            classifiers = []
        texts = [
            row["trade_object_text"] or "",
            row["sale_agreement"] or "",
            row["payment_info"] or "",
        ]
        decision = decide_lot(classifiers=classifiers, texts=texts, config=config)
        is_candidate = int(decision.decision == "include")
        previous = int(row["is_candidate"])

        if is_candidate and not previous:
            stats["newly_include"] += 1
        if not is_candidate and previous:
            stats["newly_exclude"] += 1
        if is_candidate:
            stats["included"] += 1
        elif decision.decision == "review":
            stats["reviewed"] += 1
        else:
            stats["excluded"] += 1

        if is_candidate != previous or row["filter_version"] != config.version:
            stats["changed"] += 1
            if not dry_run:
                await repo.update_filter_decision(
                    row["lot_key"],
                    is_candidate=is_candidate,
                    match_score=decision.score,
                    match_reasons_json=canonical_json(decision.reasons),
                    classification_source=str(decision.source),
                    filter_version=config.version,
                )

    return stats

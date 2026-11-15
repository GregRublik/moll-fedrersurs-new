# Implementation notes

Findings from the live source that are not obvious from the code, and how the
collector is operated.

## Source

The old portal `old.bankrot.fedresurs.ru/TradeList.aspx` is a legacy ASP.NET
shell: its trade rows link to `https://fedresurs.ru/biddings/{guid}`. All
card/lot/message data lives on the new portal behind Qrator.

Internal JSON API used by the collector (unofficial, may change):

| Endpoint | Purpose |
|---|---|
| `GET /backend/biddings?limit&offset&tradeType&tradeStartDate&tradeEndDate...` | trade list, **sorted by `dateCreate` DESC** |
| `GET /backend/biddings/{guid}` | card: type, periods, platform, organizer, manager, debtor, case |
| `GET /backend/biddings/{guid}/main` | number, status, type, `isRebidding` |
| `GET /backend/biddings/{guid}/additional` | court, application rules |
| `GET /backend/biddings/{guid}/lots?offset&limit` | lots |
| `GET /backend/biddings/{guid}/messages?offset&limit` | trade events |
| `GET /backend/account-receivables` | "права требований" showcase (no trade guid) |
| `GET /backend/reference-book/bidding-types`, `/regions` | reference books |

### Qrator findings

- Plain HTTP and headless Chromium are blocked (401/403). **Headful Chromium
  with a persistent profile passes.**
- Qrator returns **HTTP 451 (`Server: QRATOR`)** for request shapes the SPA
  does not use. Observed on the trade list:
  - allowed page sizes: **15** (SPA page size), also 1/5/50;
  - blocked: 2, 10, 19, 20, 21, 30 — deterministically, even with different
    filters/offsets.
  - card subresources (`lots`, `messages`) work with **limit=3**.
- `qrator_jsid2` cookie lives ~15 minutes; refresh proactively.
- Never retry a 451 with a different `limit` blindly — use the SPA page sizes.

### Date filter semantics

`tradeStartDate` / `tradeEndDate` filter the **trade period** (`dateStart` ..
`dateFinish`), not the publication date. Long-running public offers are
returned for every window they overlap.

Incremental discovery therefore uses the default ordering: the list is sorted
by `dateCreate DESC`. The collector pages from `offset=0` and stops after two
fully-known pages or when `dateCreate` is older than `--lookback-hours`.

`found` is capped at 10000; do not use it to assert completeness of a full
sweep.

## Bitrix24

Live discovery on the test portal (`crm.item.fields`, `crm.type.getByEntityTypeId`):

- `entityTypeId 1078` -> `crm.type.id 138` ("Федресурс сообщения"),
  category **179** ("Лиды ЕФРСБ").
- `entityTypeId 1120` -> `crm.type.id 148` ("Федресурс лоты"),
  category **180** ("Лиды ЕФРСБ").
- Both smart processes have `xmlId` — the deduplication key.
- Lots have `parentId1078` — the lot -> trade relation.
- Fields `ufCrm145_*` used by the old service **do not exist** in 1078/1120;
  the old code silently wrote to non-existent fields.
- Actual field names: `config/bitrix_fieldmap.toml`. `crm.item.*` expects
  camelCase (`ufCrm138_...`); the TOML stores original names and the client
  converts them.

Re-run field discovery on the production portal before enabling writes:

```bash
uv run python tools/dump_bitrix_fields.py
```

## CLI

```bash
uv run python src/main.py init-db          # create/migrate SQLite
uv run python src/main.py doctor --network # settings, DB, Bitrix read-only checks
uv run python src/main.py probe            # Qrator availability / 451 / latency
uv run python src/main.py collect --trade-type PublicOffer --lookback-hours 6 --details-limit 20
uv run python src/main.py sync --limit 20  # dry-run by default
```

Write mode requires **both** `BITRIX_WRITE_ENABLED=true` and `sync --write`.

## Data model

- `biddings.guid` — trade key.
- `lots.lot_key = "{trade_guid}:{lot_number}"` — lots have no own guid.
- `content_hash` — canonical normalized JSON; unchanged hash means no Bitrix
  update and no duplicate version.
- `raw_payloads` — last raw responses for audit and re-parsing.
- `collection_windows` + `window_sightings` — completeness per window.
- `errors` — separate from `outcome=no_data`; empty source is never an error.

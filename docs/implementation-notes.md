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
| `GET /backend/biddings/{guid}/messages?offset&limit` | trade event list (metadata) |
| `GET /backend/bankruptcy-messages/{guid}` | full sale announcement: text, publisher/SRO, docs, lot table |
| `GET /backend/bidding-messages/{guid}` | event message: rules, application period, `lotList` with price schedule |
| `GET /backend/bankruptcy-message-docs/{doc_guid}` | binary document download |
| `GET /backend/account-receivables` | "права требований" showcase (no trade guid) |
| `GET /backend/reference-book/bidding-types`, `/regions` | reference books |

### Materials (message text and documents)

Verified on the live portal:

- The trade card (`/backend/biddings/{guid}`) contains `message.guid` — the
  **bankruptcy message** (sale announcement), not the event message.
- `/backend/bankruptcy-messages/{guid}` returns `content.messageInfo.messageContent.text`
  and `additionalText` (full announcement text), `content.publisher` (FIO, INN,
  SNILS, OGRNIP, address, SRO name/INN/OGRN/address), `docs[]` (guid, name,
  size) and `lotTable`.
- `/backend/bidding-messages/{guid}` returns the event content:
  `content.tradeInfo.application.rules`, `lotList[]` with `priceReduction`
  (HTML table), `classification`, `paymentInfo`, `saleAgreement`.
- Documents are not links in the page; the SPA calls
  `GET /backend/bankruptcy-message-docs/{doc_guid}` and receives the binary
  file with the correct content type. Verified download of a 32 KB .docx.

Implementation (2026-11-15):

- `DetailsService` reads `card.message.guid` and fetches
  `/backend/bankruptcy-messages/{guid}`; the announcement is stored in
  `messages` with full `text_html`/`text_plain` and `files_json` (document
  guid/name/size/download URL).
- Publisher/SRO fields, `application.rules`, `additionalText` and the
  announcement text are merged into `biddings` (`manager_snils`,
  `manager_address`, `sro_*`, `application_rules`, `additional_text`,
  `announcement_text`, `publisher_json`).
- Bitrix mapping verified on the test trade 5100: rules, text, manager SNILS/
  address and SRO fields are populated. Note: the mapped Bitrix fields are
  `string`, so `_truncate` caps them at 500 characters; the full text stays in
  SQLite.
- Event message bodies (`/backend/bidding-messages/{guid}`) are not fetched
  yet; the announcement already contains the main text, rules and documents.
  Documents are stored as metadata + download URLs, not uploaded into Bitrix.

### Price reduction schedule

`normalization/price_schedule.py` parses `lot.priceReduction` into intervals:

- HTML tables with 4 or 8 columns (the 8-column form has a header row);
- `<br/>`-separated `dd.mm.yyyy hh:mm: price` lines;
- free text explaining the rule (stored as `format=text`).

The result is stored in `lots.price_reduction_json`:
`{format, intervals[], current_price, min_price, text}`. `current_price` and
`min_price` are computed at fetch time when the API does not provide them.
The unlabelled 4th column of the compact table is stored as `extra`, not
guessed as a deposit.

Bitrix gets the human-readable interval summary in «Снижение цены», plus
«Текущая цена» and «Минимальная цена». Summary and text are truncated to 500
characters by the string fields.

### Sync candidate gating

`sync` writes only rows with `is_candidate = 1`. Trades and lots in `review`
or excluded by the filter stay in SQLite and are not created in Bitrix.
`SYNC_ONLY_CANDIDATES=false` or `sync --include-non-candidates` disables the
gate for debugging; the stats field `skipped_non_candidates` shows how many
rows were held back.

Selection defaults are in `config/filters.toml`: `unmatched_decision=exclude`
(no signals -> exclude, not review), anchored text patterns, and matched
patterns recorded in `match_reasons_json`. `refilter [--dry-run]` recomputes
lot decisions from stored data without touching the network and moves newly
selected/skipped lots in the sync queue.

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

## Live verification on the test portal (2026-11-15)

Performed against `b24test.lot4rent.ru` with `BITRIX_WRITE_ENABLED=true`
passed only as a one-off environment override; `.env` remains write-disabled.

- Trade `090f8a46-b780-40ce-911f-c5a4b74a760a` -> Bitrix item **5100**:
  `categoryId=179`, `stageId=DT1078_179:NEW`, `xmlId` set, fields populated.
- Lot `090f8a46...:1` -> Bitrix item **5181**: `categoryId=180`,
  `parentId1078=5100`, `xmlId` set, prices and classification populated.
- Repeated `sync --force` updated the same two items: `crm.item.list` by
  `xmlId` still returns exactly one item each (no duplicates).
- Update path verified: a changed `debtor_name` was written to Bitrix and then
  restored.

Open gap found by the live test: **there was no status field in smart process
1078**. It was resolved by creating two string fields on `CRM_138`:

- `UF_CRM_138_STATUS` ("Статус торгов") -> API name `ufCrm138Status`;
- `UF_CRM_138_PRICE_FORM` ("Форма подачи предложения о цене") ->
  API name `ufCrm138PriceForm`.

Both are populated on the test trade (5100): status `Объявлены торги`,
price form `Закрытая`. The fields are not mapped to funnel stages: stages are
the user's workflow (`Начало`/`Подготовка`/...), not source statuses.

`tools/create_missing_fields.py` checks and creates them idempotently; run it
with `--apply` on the production portal before enabling writes.

Production portal (`b24.lot4rent.ru`, 2026-11-15): `crm.type.id` values are the
same (138/148), categories 179/180 exist, and both fields were created
(`UF_CRM_138_STATUS` id 9439, `UF_CRM_138_PRICE_FORM` id 9440). The lot process
on production has 26 fields instead of 21: five extra fields (manager name and
email, debtor INN, debtor type as enumeration, bankruptcy case number) are not
mapped yet.

### Existing trade cards and deduplication (2026-11-16)

The production smart process already contains 9 959 trade cards in category
179, created by another integration ("Торги (ЕФРСБ, old.bankrot)"). All of
them have an empty `xmlId`, but a filled trade number
(`UF_CRM_138_1774282169`) and card URL.

39 of the 108 trades collected by the new collector already exist there
(matched both by trade number and by the GUID in the card URL).

`sync` now resolves a trade in this order:

1. `xmlId` in category 179;
2. if not found, `ufCrm138_1774282169` = trade number in category 179;
3. if found by number, update that card and set its `xmlId`, so subsequent
   runs use the fast path.

Verified with a read-only dry-run on production: trade `392933` resolved to
existing card id `11393`, no duplicate created.

Lots (1120) still use `xmlId` only. Before bulk sync, check the legacy lot
cards in 1120 for the same problem (empty `xmlId`, filled lot/trade numbers).

### UF naming notes

- For `userfieldconfig.*`, the entity id is **`CRM_138` / `CRM_148`**
  (`crm.type.id`), not `CRM_1078` / `CRM_1120`.
- `crm.item.*` camelCase conversion is not a simple prefix replacement:
  `UF_CRM_138_1744310779` -> `ufCrm138_1744310779`, but
  `UF_CRM_138_STATUS` -> `ufCrm138Status` and
  `UF_CRM_138_PRICE_FORM` -> `ufCrm138PriceForm`.

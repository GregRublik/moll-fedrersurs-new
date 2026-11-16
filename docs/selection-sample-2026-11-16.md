# Selection sample — 2026-11-16

## Sample

- 49 trades (all `PublicOffer`, recent feed) and 49 lots with details.
- Decisions: **2 include**, **47 review**, **0 exclude**.
- Include sources: 1 classifier, 1 text.
- No false negatives by receivables keywords among review/exclude.

Classifier distribution (first classifier):

| Lots | Classifier |
|---:|---|
| 30 | Прочее |
| 6 | Автомобили |
| 4 | Жилые здания (помещения) |
| 4 | Здания (кроме жилых) и сооружения |
| 3 | Земельные участки |
| 1 | Права требования на краткосрочные долговые обязательства |
| 1 | Оружие |

## Findings

1. **`review` is too broad.** 47 of 49 lots are clearly non-target (cars, land,
   flats, equipment) but land in `review` because `decide_lot` returns REVIEW
   when no signal matches. The review queue is therefore almost the whole feed.
2. **The text regex is too broad.** Lot `246270-МЭТС-1` (land + right to the
   results of construction works) was included via `прав[ао]?\s+требовани`,
   matching «право требования на получение результатов работ». It is not a
   receivable.
3. **The classifier rule works.** `246346-МЭТС-1` was included with
   «Права требования на краткосрочные долговые обязательства
   (дебиторская задолженность)» and no keyword text — correct.
4. **No explicit `exclude` decisions.** Everything non-matching falls through
   to `review`, so there is no clean "not our target" state.

## Applied rule changes

1. Replaced the generic text pattern with anchored ones:
   - `дебиторск\w*\s+задолженност`
   - `прав[ао]\s+требовани[ея]?\s+к\s+` (claim against a debtor)
   - `уступк\w*\s+прав`
   - `цесси`
   - `долговы[ех]\s+обязательств`
   Bare `право требования на ...` no longer matches; construction claims are
   also covered by a negative pattern.
2. Added `unmatched_decision = "exclude"` in `config/filters.toml`:
   non-matching lots are excluded, not queued for review. `review` remains
   available for conflicts and manual overrides.
3. `match_reasons_json` now records the matched pattern, e.g.
   `["text:дебиторск\\w*\\s+задолженност"]`.

## Results after refilter

- Existing sample (49 lots): **1 include, 48 exclude, 0 review**.
- The false positive `246270-МЭТС-1` is now excluded with
  `negative:право\s+требования\s+на\s+получение\s+результатов\s+работ`.
- All 64 lots in the DB share the new `filter_version`.

## Targeted positive sample

`searchString=дебиторская задолженность`, 15 trades detailed:

- **15/15 lots included**:
  - 13 by classifier «Права требования на краткосрочные долговые
    обязательства (дебиторская задолженность)»;
  - 2 by text «Имущественные права требования (дебиторская задолженность)»
    with an empty classifier.

## Showcase check (`/backend/account-receivables`)

Attempted to use the portal's "права требований" showcase as a recall
benchmark. Result: **it is not comparable with the biddings registry**.

- 94 active items; all of type `SaleOfAccountReceivables` (sale announcements),
  not `biddings`.
- `item.guid` and `startMessage.guid` do not resolve via `/backend/biddings/...`,
  `/backend/bidding-messages/...` or `/backend/bankruptcy-messages/...`.
- `tradeNumber` is an electronic-platform number (`COM...`), not a Fedresurs
  trade number; only 48 of 94 have it.
- `tradeDate` range: **2022-06-16 .. 2025-07-13**; the collected database has
  PublicOffers from November 2026.
- Overlap by debtor INN: **0 of 94**; by INN + start price (1%): **0 of 94**.

Conclusion: the showcase is a separate stream of sale announcements, not a
subset of the trades we collect. It cannot be used as a completeness benchmark
for the current window without first collecting and modelling that stream (a
separate task, possibly a separate smart process).

## Next validation

- Agreed sample with the client (30–50 trades) — the acceptance method from
  the task.
- Window completeness: `found` vs `distinct_collected` per collection window.
- Larger random PublicOffer sample to estimate the false-negative rate for
  receivables hidden in «Прочее».

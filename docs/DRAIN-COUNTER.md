# Daily drain counter

The overview shows one number: how much a day his accounts are still being charged by recurring charges the family can stop. The number comes only from charges the records show. Clicking it opens a breakdown where every line links to its source document.

With the current fictional archive the card reads:

> **Still being charged** · **$4.24 a day** · $1,548 over a year if nothing changes · + up to $1.82 a day we're less sure about

## Where the spec differs from the repo

The spec was written before the repo was checked. Each point below changed how the feature was built.

| Spec assumption | What the repo has | Decision |
|---|---|---|
| `CLAUDE.md` and a drain `PLAN.md` | Neither exists; `PLAN.md` covers provider outreach. | This file documents the feature. |
| A `Finding` model with `amount` and `frequency` | Findings are plain JSON in `data/demo_archive.json`, with no amounts or frequencies. | Charges are read from document text by fixed rules. Each charge keeps a verbatim quote and its character offsets, then links to a finding by provider. |
| Home insurance, a car loan and other charges in the archive | The archive has three recurring charges: Valley Storage $129 (the renewal email says "Monthly charge: $129"), Harbor Gym $39.99 and Streamly $15.49 (one line each on a single statement). | Storage is **confirmed**. The gym and Streamly are **possible** (one mention, no stated frequency). The headline is **$4.24 a day**, not the spec's example of $4.51. No archive charge falls in "keep for now" or "decide later". Safety for those buckets is tested with synthetic labels. |
| An answer key of planted recurring charges | Only the outreach contact answer key exists. | `data/drain_answer_key.json` hand-labels the three archive charges and 18 synthetic classifier cases. |
| `date_of_death` defaults to a date the archive suggests | `person.date_of_death` is `null`, and `scripts/check-outreach-data.cjs` requires it to stay `null`. | No default. The family enters the date. Until then the card shows the rate and "Add the date to see the total so far." |
| Dedupe with the cross-check agent's merged findings | No cross-check agent exists. | Charges are merged by provider (or label) and amount, so an email and a statement line for the same charge count once. |
| Types {subscription, bill, obligation, insurance, debt} | The storage finding is typed `account`. | Charges come from documents rather than a finding type filter, so no recurring charge is dropped because of how its finding is typed. |
| Server-side computation for the UI | GitHub Pages has no server. | `scripts/drain_snapshot.py` writes the backend's own results to `dist/data/drain_snapshot.json` (one variant per combination of completed tasks). A test fails if that file is stale. The browser never adds up charges. |

## How the number is worked out

**Reading charges** (`backend/drain.py`)

- A stated amount and frequency, such as "Monthly charge: $129" or "$15.49 per month", becomes a charge with that frequency.
- A dated statement line, such as "Sep 3 · Harbor Gym · $39.99", is one occurrence.
  - Occurrences in two or more months give an observed frequency.
  - A single occurrence on a statement labelled "recurring" is assumed to be monthly, and is marked as assumed.
  - A single occurrence on an unlabelled statement has an unknown frequency.

**Tiers and confidence** (the confidence values are heuristics, not measured probabilities)

| Basis | Tier | Confidence |
|---|---|---|
| Amount and frequency stated in a document | confirmed | 0.9 |
| Observed in 2 / 3+ statement periods | confirmed | 0.85 / 0.95 |
| Repeats within one period | possible | 0.7 |
| One line on a statement labelled recurring | possible | 0.6 |
| One unlabelled line | not shown | 0.4 |

**Daily rate.** `daily_rate = amount / divisor`, unrounded, and rounded only for display. The divisors are:

| daily | weekly | biweekly | monthly | quarterly | yearly |
|---|---|---|---|---|---|
| 1 | 7 | 14 | 365.25/12 (30.44) | 365.25/4 (91.31) | 365.25 |

**Buckets.** Rules come from `data/charge_buckets.json` and are checked in this order:
1. "Keep for now" keywords (home and auto insurance, utilities, HOA, alarm monitoring).
2. "Decide later" keywords (mortgage, car loan or lease, timeshare, life insurance, other debt, generic insurance).
3. Curated institutions (the three archive providers).
4. "Stoppable" keywords.
5. The local model. It is only asked about charges no rule matched, over a loopback-only endpoint.
6. `decide_later`, if the model is unavailable or answers anything other than `{"bucket": ...}`.

Keywords match whole words only. Because the safety rules run first, "Harbor Gym home insurance bundle" is sorted as keep for now. Model answers are cached for the life of the process, so restart the service after swapping models.

**Not counted:**
- One-time or unknown-frequency charges.
- Confidence below 0.5.
- A charge that a later document for the same provider says was cancelled. In a document that mentions several providers, only a cancellation on the line naming this provider counts.
- A charge last seen more than one billing period before the date of death.

Excluded charges are returned with their reason and evidence, and are listed under "Not counted" in the breakdown.

**Derived values:**
- `daily` is the sum of **confirmed, stoppable** charges that aren't stopped. This is the headline.
- `possible_daily` is the same for possible charges ("+ up to $X a day").
- `annual` is `daily × 365.25`.
- `since_death` is `daily × days since the date of death`, labelled approximate.
- `stopped_so_far` sums confirmed stoppable charges whose action the family has marked completed. Completing an insurance or loan action never counts as stopping it.
- `by_finding` gives per-action rates for the plan captions.
- A test asserts that the bucket lines add up exactly to `daily`.

## API

```
GET  /drain?done=storage,subscriptions&as_of=YYYY-MM-DD
  -> { daily, possible_daily, annual, since_death, days_since_death, stopped_so_far, as_of,
       date_of_death, date_of_death_source, confirmed: [Line], possible: [Line],
       buckets: { stoppable, keep_for_now, decide_later }, excluded: [...], by_finding: {...} }
  Line = { id, finding_id, provider_id, label, amount, frequency, frequency_basis, daily_rate,
           bucket, bucket_source, note, tier, confidence, periods, last_seen, stopped, evidence }

POST /estate/date-of-death  { "date": "YYYY-MM-DD" | null }
```

- **`done`** takes the ids of completed plan actions, which the browser keeps in local storage. Ids that aren't findings are ignored, because they carry no charges. Malformed ids, or more than 50, return 422.
- **`as_of`** defaults to the server's current date.
- **The date of death** is stored once as the `estate` setting in the local SQLite database. It must be a real date, not in the future and not before 1900. `null` clears it.
- **The event log** records that the date changed, but never the date itself.
- **Same-origin rules:** writes need `Content-Type: application/json` and the `X-Afterword-Client: web` header, like the rest of the local service.

## Interface

- **Overview card** (`dist/drain.js`, `drain.css`): "Still being charged" above a large serif figure, in ink colours only. There's no red and no animation. The figure updates when the page renders, never on a timer.
  - When nothing confirmed is still charging, the card says so.
  - "You've already stopped …" appears only when that figure is above zero.
  - The date line shows either the approximate total since the date of death or "Add the date to see the total so far".
  - On the static site the card says the figures are samples, and the date field is disabled because saving it needs the local service.
- **Breakdown dialog:** three sections. Each row shows the amount, frequency, daily rate, a Confirmed / Less sure label, the note for its bucket, the verbatim quote, and a source link to the existing document view with "Back to charges". Rows reuse the existing controls:
  - **Plan visit** opens the storage action.
  - **Ask to cancel** opens the provider letter on the cancellation template.
  - Other rows get **Open action**.
  - Keep-for-now and decide-later rows are never offered for cancellation.
- **Plan captions:** "$4.24 a day" or "Possibly $1.82 a day" beside an action.

## Metrics

Run `python scripts/evaluate_drain.py`. It reads the answer key and makes no network or model calls. Results on September 25, 2026:

| Metric | Result |
|---|---|
| Rate accuracy | Computed $4.2382/day vs expected $4.2382/day (difference 0); 3/3 lines with the correct frequency and tier |
| Bucket precision | 3/3 archive lines; 18/18 synthetic classifier cases |
| Keep-for-now harms (reported separately) | 0 in the archive, which has no keep-for-now charges; 0 of 7 synthetic keep-for-now cases sorted as stoppable |
| Coverage | 3/3 recurring charges produced a line; 0 unexpected lines (the $1,240 invoice, $400 receipt and $250,000 coverage are not charges) |
| Evidence completeness | 3/3 lines have a quote that matches the document text at its offsets |

These results come from a three-charge fictional archive and hand-written synthetic labels. They do not estimate real-world accuracy. The local model fallback was tested with injected fakes only; no live model classification was run. No Nano timing was measured.

## Verification

- `python -m pytest tests/ -q`: 201 passed, 2 skipped.
  - `tests/test_drain_buckets.py` covers the divisors, rules, precedence, model fallback and loopback guard.
  - `tests/test_drain.py` covers extraction, the headline invariants, dedupe, exclusions, the API, persistence across restart, validation, same-origin enforcement, snapshot freshness and the evaluation.
- `node tests/drain.test.cjs` covers card states, recompute on completion, the snapshot fallback, the service error state, breakdown buckets, safe actions, escaping, captions and tone.
- In headless Firefox on Linux (arm64), both against `python -m backend.main` and against `dist/` on a plain static server:
  - The card showed the correct figures.
  - A future date was refused; saving a date produced "About $93 since September 3".
  - Completing the storage action produced "You've already stopped $4.24 a day".
  - The source link opened the document and returned to the breakdown.
  - Plan visit and Ask to cancel opened the right existing flows.
  - Plan captions matched in both modes.
  - At 390px width, neither the card nor the dialog overflowed horizontally.
  - No page errors were captured (the capture itself was confirmed with a deliberate probe error).

## Known limits and next steps

- **No keep-for-now or decide-later charges in the demo archive.** Adding, for example, a home insurance renewal and a second monthly statement to the fictional archive would exercise those sections and turn the gym and Streamly into confirmed charges. That would change shared fixtures that the outreach answer key and checks depend on, so it needs a team decision.
- **"Marked completed" is treated as "stopped".** Completing the storage action (a visit) therefore counts its $4.24 a day as stopped, as the spec defines `stopped_so_far`.
- **Since-death total uses today's rate.** `since_death` multiplies the current still-charging rate by the days since the date of death. Stopping a charge lowers the total, which is why it is labelled approximate.
- **Source links for uploaded documents.** Documents ingested on the local service show their quote in the breakdown, but have no link unless the static workspace also has that record.
- **Local checks.** Run `pytest` for the Python drain tests, snapshot check and evaluation; run `node tests/drain.test.cjs` separately for the frontend. No CI workflow runs these automatically.

After changing the archive, the rules or `backend/drain.py`, run `python scripts/drain_snapshot.py` and `node scripts/version-assets.cjs`.

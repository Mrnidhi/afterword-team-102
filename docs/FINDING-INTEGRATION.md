# Finding contract integration

The full user requirements are retained in `FINDING-INTEGRATION-SPEC.md`.
This application consumes the team's engine; it does not retrain the model or
duplicate its financial rules. Final live verification is recorded separately.

## Preservation and ownership

The original hp24 multilingual backend and UI were recovered from
`/home/hp24/afterword-team-102`, committed as `5c6965e`, pushed to the
`hp24-multilingual-preservation` branch of the Team 102 repository, and merged
into `main` as `63d8dab`. Runtime `backend/afterword.db` and bytecode were excluded.
The original remote pointed at a different fork and rejected the push; the
commit was transferred through a Git bundle and pushed using the local checkout.

All new remote deployment files belong under
`/home/hp24/Documents/Afterword-Integration/`: `app/`, `venv/`, `runtime/`,
`logs/`, and `reports/`. Local recovery archives and verification reports belong
under the user's `Documents/Afterword-Integration/` folder. Existing model and
teammate service directories are read as integration dependencies.

## Service boundary

`python -m backend.main` launches one worker in offline mode. It mounts extraction,
ingestion, source retrieval, local translation and static assets on one origin.
The `create_app()` factory without the offline flag remains available for the
earlier outreach test suite; it is not the new application's launch path.

| API | Request / result |
| --- | --- |
| `POST /extract` | `{id, source, text, reference_date?}` returns exactly contract v1 |
| `POST /extract/batch` | `{items:[...]}` returns a sequential list of contract results |
| `GET /findings` | `{contract, findings, total, counts}`; stored rows include exact text, creation time and reference date |
| `GET /findings/{id}` | One stored row with the exact extraction input |
| `POST /ingest/preview` | `{filename, content_base64, reference_date?}` parses locally before inference |
| `POST /ingest/extract` | Same upload shape; extracts parsed items sequentially and reports per-item errors |
| `GET /health` | Contract, current served model identity, runtime and translation availability |
| `POST /translate` | Recovered translation contract, confined to local ports 8000 and 8003 |

Use `?retry=true` deliberately to reprocess existing unchanged input. Repeated
ordinary imports are idempotent. Reusing an ID with different source text, type
or reference date is rejected rather than silently changing an evidence record.
The reference date is saved separately from the model envelope and restored for
retries. A model failure is stored as `failed`, including when one batch item
fails and others succeed.

`AFTERWORD_FINDINGS_DB` uses the explicit findings columns from B3, separate from
the earlier outreach database's incompatible JSON-payload table. Both databases
are outside Git. Files use owner-only permissions. Source text and model responses
are stored in SQLite, not persisted by the live frontend in browser storage.
Review notes and read/favorite marks are browser-local and are not encrypted.

The engine code is loaded unchanged with an isolated, restricted HTTP adapter.
Only loopback HTTP `/v1` on port 8000 is permitted, proxies and redirects are
disabled, and model identity is discovered again without restarting the backend.
`AFTERWORD_EXTRACT_MAX_CHARS` defaults to 32,000. Longer input is retained in full
with a visible failed result and never sent to the GPU; no silent truncation is
used. Check the model's context/memory budget before raising the limit.

## User experience and offline behavior

Actions use `route=extract`; memories use `route=memory`; dropped items appear as
an ignored count. Failed and malformed records remain visible for recovery.
The action sort matches the recovered `schema.priority()`: stated `due` days
first, ascending, then engine-returned `money_at_stake` descending. Evidence
numbering follows Python `str.splitlines()` on stored exact text.

Printed amount and financial exposure are displayed separately. The frontend
does not infer a currency, recompute money, or treat a review flag as confirmation.
Telemetry uses returned token/latency/tier values. Undelivered model-layer metrics
and cloud cost comparisons remain unavailable; no performance figures are invented.
The ledger reports zero entities sent to cloud by the offline application, based
on its enforced local processing boundary. This is not whole-device network
telemetry: viewing the app through SSH can transfer results to the browser on
another computer. The label therefore does not claim that no data leaves the HP.

System fonts replace remote font stylesheets. The offline runtime's content
security policy permits same-origin connections only. Gmail and public lookup
routes are absent, and their browser actions are disabled. Installation may need
network access beforehand; processing uses already-installed OCR/model assets.

## Verification requirements

| Scope | Required evidence |
| --- | --- |
| Preservation | Remote source commit, ignored runtime database, public branch and merged main |
| B1–B3 | Actual engine envelope, sequential single/batch behavior, failure persistence and restart/source equality |
| B4–B6 | Per-message/per-page counts, MIME/CSV/PDF handling, real CPU OCR and no network during OCR |
| B7–B8 | Live served model/contract, local-only transport, unavailable cloud routes and browser network check |
| F1–F6 | Actual import → findings → action/evidence/memory flow, correct ordering, status explanations and amount comparison |
| F7–F8 | Actual-only metrics/placeholders and no remote font dependency |
| Weight replacement | Same contract against different served identities without application changes; actual SFT comparison belongs to the model team |

Automated tests, laptop browser checks, HP model execution and final trained-model
evaluation are distinct evidence levels. Passing injected model tests does not
establish live accuracy. Pending model-team deliverables include the curated demo
estate, calibrated confidence and final evaluation/deck metrics.

# Afterword finding integration verification

Verified on 2026-09-24 (America/Los_Angeles).

## Delivered scope

The local application integrates the model team's unchanged `afterword.finding/v1`
engine with sequential extraction, exact-source SQLite persistence, email/SMS/PDF
and CPU OCR intake, action/evidence/memory views, explicit failed-result recovery,
and actual model/tier/token/latency panels. The fictional static preview remains
separate and is never an automatic substitute for missing backend data.

All new HP deployment artifacts are inside
`/home/hp24/Documents/Afterword-Integration/`. Local recovery and verification
artifacts are inside `/Users/srinidhigowda/Documents/Afterword-Integration/`.

## Observed execution

- Verified SSH host `zgx-9b91`, `aarch64`, NVIDIA GB10, driver 580.178.04.
- App listens on HP loopback 8081; Mac loopback 4175 is an SSH tunnel to it.
- Actual served model: `Qwen/Qwen3-4B-Instruct-2507`; contract `afterword.finding/v1`.
- Model 8000 and embedding 8003 processes remained running with their original PIDs.
  No model was loaded, trained, stopped or restarted by this integration work.
- Six records processed through real HTTP API checks; two more through the browser
  MBOX import. Final archive: 5 actions, 2 memories, 1 ignored item; 3 accepted,
  5 needing review. No model failures in this small HP extraction run.
- All input text was read back exactly; evidence strings matched their numbered
  source lines. Repeating existing requests returned identical stored envelopes.
- EML: 1 message; MBOX: 2 messages; SMS CSV: 1 valid row and 1 explicit empty-body
  error; text PDF: 2 pages; scan PNG: 1 CPU OCR record. Parser warnings remained
  visible after successful neighboring records were processed.
- Three-record sequential batch took 9.582 s including transport. Stored latency
  averaged 2609.63 ms and output tokens 36.75 across 8 records. These are small smoke
  test observations under shared load, not a benchmark or accuracy evaluation.
- Scan preview took 2.706 s including upload and first-use CPU OCR. This is not a
  pages-per-second throughput claim. RapidOCR's actual ONNX sessions were checked
  as CPU-only with socket connections blocked in the ingestion test suite.
- All 8 records were identical before/after a graceful restart of this app only.

## User experience

Observed in the browser: empty workspace, local-model failure with source retained,
HP file preview/processing, partial import warning, action ordering, 12.99→155.88
amount comparison, exact evidence highlighting, review notes/read marks, memory
saving, keyboard search, current model measurements, and explicit sample preview
followed by return to the unchanged live archive. Notes/read/favorites survived
reload. Phone views at 390 px and 320 px had no horizontal document overflow. No unexpected
browser warning/error logs were observed during the core flows; the deliberate
translation rejection uses a handled HTTP 503 response.

Unsupported model deadlines retain their returned values but say to verify against
the source; they do not show a definitive countdown. Unsupported amounts are
labelled unverified/provisional. Engine sorting and stored findings are unchanged.

## Verification boundaries

Final Mac automated suite: **254 passed**. HP ARM full suite before the final
translation correction: 246 passed, 2 skipped (optional earlier Tesseract
checks; required RapidOCR checks ran). The changed translation/offline suites
then passed all 42 checks on HP, including 7 subtests. All 7 JavaScript suites
and asset/fixture checks passed. Final code revision `0c60b65` passed
[GitHub deployment](https://github.com/Mrnidhi/afterword-team-102/actions/runs/36078609109).
Six live public assets matched Git byte-for-byte; the final backend-only
correction did not change those assets.

Live translation initially returned broken protected-detail placeholders.
The correction rejects unsafe forward/back translations, bypasses old cache
entries without deleting them, and retains the original English. Verified
again through the HP-backed browser: it showed the readable translation error
and complete original source, with no broken placeholder output. This is a
verified safe fallback, not a claim that this example translated successfully.

The offline application's model destinations are restricted to loopback ports 8000
and 8003; redirects/proxies and cloud routes are disabled. Browser CSP permits
same-origin network requests and system fonts remove external font dependencies.
The team’s physical network cable was not unplugged during verification. Access
from a Mac through SSH transfers results to that Mac, so the ledger reports
zero entities sent to cloud by this application, not zero bytes leaving the HP.

The base model still returns incorrect or weakly grounded fields. Its verified
contract is not evidence of clinical/legal/financial accuracy or calibrated
confidence. The model team still owns the fine-tuned weights, calibration,
curated ~50-document estate and final benchmark/deck metrics. Weight-identity
replacement was tested with injected transports; an actual SFT swap was not
performed. Cloud-equivalent cost remains unavailable.

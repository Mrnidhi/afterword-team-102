# Provider outreach implementation plan

Source of truth: `docs/PROVIDER-OUTREACH-SPEC.md` (the complete user-supplied plan).

## Scope and implementation decisions

Implement the provider-contact → local draft → exact disclosure review → Gmail
handoff → manually recorded send → reply workflow. Build the missing local
Python/SQLite backend as well as the existing buildless browser application.
Keep GitHub Pages functional with explicitly browser-local template generation;
the local server adds document ingest, inference, persistence and integrations.
Never represent a static template, mocked service, opened compose window or
local test as real inference, a delivered email or a hardware measurement.

The specification's principles and primary flow govern conflicting sample prompts:
opening Gmail does **not** mark mail as sent. `Mark as sent` is a separate act.
Use the six fictional providers that actually exist in the current archive;
the alternative provider names in the specification are examples. No recipient
mailbox is assumed controlled. Configure a team-owned inbox before creating live
demo aliases. User-entered recipients are labelled as supplied by the family.

The family reviews the exact recipient, subject, body and attachments. Any edit
invalidates earlier consent. Consent for a company-only web lookup never grants
permission to disclose family information in a letter. Gmail compose URLs expose
the reviewed text to Google when opened, before the user presses Send.

Gmail's `gmail.compose` permission includes sending capability at Google's scope
level. Afterword nevertheless implements draft creation only; it must not claim
that the scope technically forbids sending. The application has no send endpoint.

## Delivery order

1. P0: models, SQLite, exact evidence extraction, directory, ranked resolver,
   five templates, local-model adapter, strict output validation.
2. P0: Letters recipient selection, editable family fields, disclosure review,
   placeholder/sensitive-value/length guards, copy/mailto/Gmail handoff.
3. P0: separately recorded send, waiting status, personal follow-up reminder,
   manual reply, durable consent/outreach history and privacy export.
4. P1: source-matched scan contacts, approval-only public lookup, Gmail OAuth
   draft creation with reviewed attachments, disconnect and token cleanup.
5. P2: separately opted-in readonly reply detection if core tests pass.
6. Verify local service and static site, desktop/mobile keyboard flows, failure
   states, malicious inputs, refresh, stale consent, state transitions and logs.
7. Commit/push tested increments and verify GitHub Pages deployment, preserving
   the existing authorization to keep the repository updated.

## Required evidence and gates

| Requirement | Evidence required |
|---|---|
| O1 schemas/tables | Model validation, persistence/restart and API tests |
| O2 ingest mining | Header/footer/offset/domain/role/no-reply tests; actual ingested fixture |
| O3 directory | All six existing fictional providers represented; owned mailbox configured explicitly |
| O4 resolver | Records > directory > lookup; role/date tie-break; missing and no-reply-only tests |
| O5 draft | All five templates; required slots; actual local adapter contract tested; no unsupported facts |
| O6 review | Rendered full snapshot; provenance; fields; attachment list; edit invalidation |
| O7 handoff | URL encoding, noopener, no auto-send, 1500-char bound, clipboard/mailto fallback |
| O8 tracking | Opening does not imply sent; explicit sent → waiting; +14-day personal reminder |
| O9 scan pipeline | PNG/JPEG validation → real local Tesseract OCR → original/recognized-text preview → versioned corrections → explicit current-hash confirmation → configured local vision and exact reviewed-text spans; live Nano/vision verification separate |
| O10 lookup | Explicit consent; only canonical company/country payload; source URL; unverified status; logs |
| O11 Gmail draft | OAuth state/PKCE; draft-only API; reviewed MIME attachment bytes; local tokens; disconnect |
| O12 privacy | Who/when/fields/consenting actor; distinguish handoff from sent; export works |
| O13 reply | Optional readonly consent; real incoming message in correct thread; manual path works |
| Metrics | Reproducible fixture resolution/precision/minimization; measured browser timing clearly scoped |
| Nano timing | Actual HP end-to-end timing and manual baseline, never substituted by laptop timing |
| Demo delivery | Human-controlled inbox + human Send; receipt/reply verified only with actual evidence |

## O9 implementation and verification boundary

The local scan pipeline is implemented in `backend/scans.py` and
`dist/outreach-scans.js`. It accepts a single PNG/JPEG up to 6 MB, 20 megapixels
and 12,000 pixels per dimension. PDF conversion and animated images are outside
this bounded intake. Pillow validates and decodes the image; a fixed-argument
Tesseract process reads English text with a timeout. Installation requires the
Tesseract executable and `eng` language data. `AFTERWORD_TESSERACT_BIN` overrides
the service's executable discovery; installation and run instructions are in the
README.

Original scan bytes, their hash, the processing copy/hash and raw OCR/hash remain
separate. A reviewer can correct text before extraction; correction versions
retain the previous hash, actor and time. The old hash cannot approve new text.
Extraction checks the current image/text hashes, requires explicit confirmation,
uses the configured loopback vision endpoint and stores source spans against the
reviewed OCR. Corrected OCR is labelled as such. Confirming again is idempotent;
changed stored images fail validation, and an ingested source cannot be edited.
Files stay in private storage outside the repository (`AFTERWORD_SCAN_DIR` or
`~/.local/share/afterword/scans/`) and are never automatically attached to mail.

OCR staging, original-image preview and corrections are usable when the vision
model is unavailable. Contact extraction then remains unavailable, with no fake
success or inferred recipient. Readiness reports the OCR executable, image
validator and vision configuration independently.

Verification includes `node tests/outreach-scans.test.cjs` and the Python scan
suite within `.venv/bin/python -m pytest tests/ -q`. Adversarial tests cover limits,
invalid image types, fixed command arguments, timeouts, cleanup, stale hashes,
modified stored bytes, missing services, correction provenance, idempotency and
unsupported model contacts. Real Tesseract CLI/API tests processed the fictional
fixture on the developer's machine and revealed a contact-character OCR error.
No Nano timing or successful live vision extraction is established by those tests.
The root verification report and metrics remain the authority for broader gates.

## External configuration pending

- Demo recipient authorized by the user and configured in local settings. The
  address is intentionally absent from this public repository. No delivery or
  inbox-ownership verification is implied by that authorization.
- Nano local text/vision model endpoints and live device access.
- Optional Google OAuth testing client and teammate test accounts.
- Optional approved public-lookup adapter credentials/configuration.

Implementation and offline/contract tests proceed while these are pending.
Live integrations and hardware measurements stay explicitly unverified until
their prerequisites are present. The goal remains active while required evidence
is missing; passing mocked tests alone is not full completion.

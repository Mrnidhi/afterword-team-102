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
| O9 vision | Local vision integration with exact OCR match; live hardware verification separate |
| O10 lookup | Explicit consent; only canonical company/country payload; source URL; unverified status; logs |
| O11 Gmail draft | OAuth state/PKCE; draft-only API; reviewed MIME attachment bytes; local tokens; disconnect |
| O12 privacy | Who/when/fields/consenting actor; distinguish handoff from sent; export works |
| O13 reply | Optional readonly consent; real incoming message in correct thread; manual path works |
| Metrics | Reproducible fixture resolution/precision/minimization; measured browser timing clearly scoped |
| Nano timing | Actual HP end-to-end timing and manual baseline, never substituted by laptop timing |
| Demo delivery | Human-controlled inbox + human Send; receipt/reply verified only with actual evidence |

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

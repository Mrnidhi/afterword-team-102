# Provider outreach verification — September 24, 2026

## Result and boundary

The provider-outreach implementation is ready for a configured local rehearsal.
All 78 Python tests and the three Node test suites passed on the development
machine. Static fixture parity, every frontend JavaScript syntax check and asset
version checks passed. No email was sent. The approved demo recipient is stored
in local settings and is not included in the repository.

**The complete acceptance gate is still open.** Nano model/vision execution,
Google OAuth and real draft creation, approved live lookup, an actual sent/replied
mailbox rehearsal, and the requested Nano/manual timing comparison have not been
verified. Mocked transport tests are not evidence of those outcomes.

## Requirement audit

| Item | Implemented and executed evidence | Outstanding evidence / limitation |
|---|---|---|
| O1 Models and storage | Strict request schemas, SQLite persistence, immutable consent/events API, restricted database permissions, restart and mutation tests | Single-process local workspace; not a production multi-user authorization service |
| O2 Contact mining | Header/footer extraction, exact domain association, role ranking, no-reply filtering, dates and evidence offsets; MIME base64/plain-part decoding retains raw source and canonical text | Wider real-document evaluation remains necessary |
| O3 Offline directory | All six providers in the actual fictional archive; runtime approved inbox; Gmail aliases only for Gmail domains; exact address on other domains | Mailbox control is user-attested, not independently verified; delivered mail not tested |
| O4 Resolution | Records/directory/lookup ranking, empty/no-reply cases, wrong-provider rejection, source offsets and provider-specific candidates sharing one inbox | Heuristic confidence is not a probability or proof of contact authority |
| O5 Five draft templates | All templates, visible required slots, local adapter contract, factual slot equality, rejection/fallback tests and browser checks of actual backend templates | Actual Nano model endpoint is still needed; browser/template fallback is labelled honestly |
| O6 Disclosure review | Exact recipient/company/subject/body/checklist/file-manifest review; snapshot includes provider identity; stale edit/attachment/provider consent tests; browser review inspected | Humans must review arbitrary prose and file contents; detection cannot identify every personal detail |
| O7 Email handoff | URL encoding, opener isolation, 1,500-character guard, mailto and consented clipboard fallback; placeholder/reserved-recipient failures tested in browser | No actual Gmail compose navigation or email-app delivery was performed in this rehearsal |
| O8 Sent/replied lifecycle | Explicit separate confirmation, waiting/review mapping, +14-day personal reminder, idempotence and stale-consent tests | Browser copy was verified without falsely marking it sent; lifecycle confirmations used test data in automated tests |
| O9 Scan contacts | Loopback vision adapter and exact stored-OCR span gate exercised with injected responses; API stores validated contacts | Requires a local OCR text ingest and configured PNG/JPEG vision runtime; no scan-upload product UI or complete OCR pipeline is claimed |
| O10 Public lookup | Explicit approval/hash, canonical company/country payload, provenance, unverified contacts, escalation log, public DNS pinning and redirect/proxy restrictions tested | Operator-provided HTTPS search adapter is not configured or live-tested |
| O11 Gmail API draft | PKCE/browser-bound state, narrow operation allowlist, restricted external token storage, account profile, reviewed MIME bytes and hash-bound consent; UI completion uses the actual final consent; ambiguous retries are guarded | Google client/test account and live OAuth/draft/attachment rehearsal required; official draft-ID UI permalink is unavailable, so a clearly labelled Drafts-folder link is used |
| O12 Privacy | Actual consented browser copy appeared in privacy history; copies distinguished from external handoffs; actor/time/approved fields/export and server persistence implemented | Browser records are editable local storage; no delivery receipt is inferred |
| O13 Reply tracking | Separately approved readonly scope, sent-message correlation and incoming-thread checks exercised with fakes; manual reply supported | On-demand check, not background polling; actual controlled reply still required |
| Scored metrics | Independent answer key, reproducible seven-finding report, five-template lengths/disclosures, blocked-field probes | Nano end-to-end time and matched human baseline remain null |

The primary specification forbids auto-send and requires a separate sent
confirmation. That takes precedence over sample Prompt D, which incorrectly
combines opening Gmail and marking sent. The application contains no send
operation. Google's `gmail.compose` permission itself does include send
capability; the UI and integration documentation state that accurately.

## Executed checks

Run from the repository root with Node and the documented Python environment:

```sh
python -m pytest tests/ -q
node tests/state.test.cjs
node tests/outreach.test.cjs
node tests/outreach-integrations.test.cjs
node scripts/check-outreach-data.cjs
python scripts/evaluate_outreach.py
node scripts/version-assets.cjs --check
for file in dist/*.js; do node --check "$file"; done
git diff --check
```

Observed Python result: **78 passed in 2.23 seconds** on the development machine.
This is test-run duration, not model latency. The independent evaluation also ran
with the user-approved inbox supplied via a local environment variable. That
report contains eight proposed provider/address pairs, all matching the answer
key; two distinct providers intentionally share one inbox. See
`outreach-fixture-results.json` and `METRICS.md` for denominators and limits.

Browser checks used the actual local service and a separate static server:

- Selecting a directory recipient, completing fictional family details, preparing
  a letter, reviewing it and copying it after consent.
- Reloading the service/browser preserves the draft and copy-consent history.
- Unconfigured Gmail shows setup guidance, not a successful draft or new consent.
- Static mode shows its template-only status, reserved source provenance and
  blocked Gmail/mailto actions; attempting copy with missing fields shows the
  same guard.
- Mobile navigation and letter/review reflow had no horizontal overflow at
  measured 333px and 351px CSS widths. Desktop fields and layout were inspected.
  The in-app viewport overrides did not produce the exact requested 320/390px
  dimensions; those exact widths are not claimed as tested in this release.
- No JavaScript error messages were observed in the inspected static-mode log.
  Earlier workspace-wide tests are documented separately in README.

This is not an exhaustive browser matrix or an independent accessibility audit.
The UI keeps one working draft per action/template. Changing the provider updates
that letter; the service retains separately generated records and consent history.

## Remaining live acceptance steps

1. Run the service on the HP device with its text-model endpoint configured; verify
   `local_model_guarded` rather than fallback, and capture the full finding-to-review
   timing. Run a matched human task and retain the baseline.
2. Provide local OCR text and a scan to the configured local vision endpoint;
   compare every accepted source span with the actual scan.
3. Configure the approved public-search adapter and verify one consented query
   contains exactly company/country and no family fields.
4. Configure a Google OAuth testing client outside the repository and authorize
   a teammate test account through the UI. Create one reviewed draft with a
   fictional attachment and inspect it in Gmail.
5. A person presses Send to the approved demo inbox, confirms sending in Afterword,
   replies from that inbox, and verifies manual plus connected reply tracking.

Record the observed results before calling the full feature plan complete.

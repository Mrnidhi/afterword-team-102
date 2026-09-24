# Provider outreach verification — September 24, 2026

## Result and boundary

The provider-outreach implementation is ready for a configured local rehearsal.
All 138 Python tests and the five Node test suites passed on the development
machine. Static fixture parity, every frontend JavaScript syntax check and asset
version checks passed. No email was sent. The approved demo recipient is stored
in local settings and is not included in the repository.

The preceding outreach release was commit `092fc9445c45c2e27369ccac48a5e7d99496fba5`.
[GitHub Actions run 36063210632](https://github.com/Mrnidhi/afterword-team-102/actions/runs/36063210632)
passed both validation and Pages deployment. Its HTML and four outreach assets
were verified byte for byte. The scan/readiness extension is published as commit
`e0c07895fdcf3d2473ea17c8baa6bb2b614ad151`.
[GitHub Actions run 36065091281](https://github.com/Mrnidhi/afterword-team-102/actions/runs/36065091281)
passed validation and Pages deployment. A fresh public read-back matched the
release bytes for `index.html`, `outreach-scans.js`, `outreach.js`,
`outreach-integrations.js`, `outreach.css` and `workspace.js`.
The source-reference and navigation correction is published as commit
`2f9e6b7adda492d1c0748f776e60e0d88fc935ee`.
[GitHub Actions run 36067293932](https://github.com/Mrnidhi/afterword-team-102/actions/runs/36067293932)
passed validation and Pages deployment. A fresh public read-back matched the
release bytes for `index.html`, `outreach.js`, `outreach-core.js` and
`outreach-scans.js`.
GitHub Pages runs the static mode; it does not host Python, the private database,
scan images or Google tokens.

**The complete acceptance gate is still open.** Nano model/vision execution,
Google OAuth and real draft creation, approved live lookup, an actual sent/replied
mailbox rehearsal, and the requested Nano/manual timing comparison have not been
verified. Mocked transport tests are not evidence of those outcomes.

## Requirement audit

| Item | Implemented and executed evidence | Outstanding evidence / limitation |
|---|---|---|
| O1 Models and storage | Strict request schemas, SQLite persistence, immutable consent/events API, restricted database permissions, restart and mutation tests | Single-process local workspace; not a production multi-user authorization service |
| O2 Contact mining | Header/footer extraction, actual sender-domain inference, role ranking, no-reply filtering, valid email Date fallback and evidence offsets; MIME decoding retains raw source and canonical text; conflicting providers are rejected | Wider real-document evaluation remains necessary |
| O3 Offline directory | All six providers in the actual fictional archive; runtime approved inbox; Gmail aliases only for Gmail domains; exact address on other domains | Mailbox control is user-attested, not independently verified; delivered mail not tested |
| O4 Resolution | Records/directory/lookup ranking, empty/no-reply cases, wrong-provider rejection, source offsets and provider-specific candidates sharing one inbox | Heuristic confidence is not a probability or proof of contact authority |
| O5 Five draft templates | All templates, visible required slots, local adapter contract, factual slot equality, rejection/fallback tests and browser checks; account references come from exact provider-scoped source spans, with explicit selection or omission when ambiguous | Actual Nano model endpoint is still needed; browser/template fallback is labelled honestly |
| O6 Disclosure review | Exact recipient/company/subject/body/checklist/file-manifest review; snapshot includes provider and source-reference identity; stale source/edit/attachment/provider consent tests; browser review inspected | Humans must review arbitrary prose and file contents; detection cannot identify every personal detail |
| O7 Email handoff | URL encoding, opener isolation, 1,500-character guard, mailto and consented clipboard fallback; placeholder/reserved-recipient failures tested in browser | No actual Gmail compose navigation or email-app delivery was performed in this rehearsal |
| O8 Sent/replied lifecycle | Explicit separate confirmation, waiting/review mapping, +14-day personal reminder, idempotence and stale-consent tests; actual frontend handlers preserve later manual task decisions during history reload | Browser copy was verified without falsely marking it sent; lifecycle confirmations used test data in automated tests |
| O9 Scan contacts | Documents upload UI; local Tesseract OCR; exact original image and raw OCR retained; human correction history; hash-bound review; resume after restart; exact contact spans and provider association; actual local OCR/browser/API verification | PNG/JPEG only, up to 6 MB and 20 megapixels; PDF pages require image export; actual Nano vision extraction is still unverified |
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
node tests/outreach-scans.test.cjs
node tests/outreach-navigation.test.cjs
node scripts/check-outreach-data.cjs
python scripts/evaluate_outreach.py
node scripts/version-assets.cjs --check
for file in dist/*.js; do node --check "$file"; done
git diff --check
```

Observed Python result: **138 passed in 4.60 seconds** on the development machine,
including two tests executing the installed Tesseract engine. CI installs English
Tesseract so these tests also execute there rather than silently skip.
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
- Letters and review were checked at measured 320px and 390px CSS widths, with
  no horizontal overflow; Privacy and Settings were checked at 320px. The scan
  review also passed measured 320px, 390px and 1440px checks; the original image
  loaded, and the dialog had no horizontal overflow. Temporary viewport overrides
  were reset after testing.
- Uploaded the fictional Cedar Life image through the browser, ran actual local
  OCR, corrected its misread email and omitted heading, and verified the raw OCR
  remained available. Restarting the backend and reloading preserved the saved
  correction and the Resume review entry. Approval reset on resume.
- Exact original image bytes matched the fixture. Old OCR approval hashes were
  rejected. Missing vision configuration kept extraction disabled in the UI and
  returned HTTP 409 from the API without creating an archive document.
- Settings showed two actual working drafts, connected text intake and Gmail
  not configured, rather than the former hardcoded draft/connection labels.
- Static mode showed the local-service requirement without reading or uploading a file.
- Privacy now describes the locally stored scans, raw OCR and corrected versions.
- No JavaScript error messages were observed in the inspected scan-session log.
  Earlier workspace-wide tests are documented separately in README.
- Imported `valley-storage-reference.eml` with provider and date left unset.
  The actual browser routed from Documents to the storage action, inferred the
  provider from the sender domain, displayed the September 23 source date and
  selected account ending 7766. The prepared letter contained only that masked
  reference, not the full fixture identifier.
- Imported the second storage fixture. The existing selection stayed intact;
  the two source records remained separate. Choosing account ending 2233 kept
  the previous body intact and required preparation before sharing. Preparing
  applied only the new masked reference. Explicit omission removed the account
  reference from the letter.
- The reference selector and its source description fit measured 320px and 390px
  CSS widths without document overflow. The viewport override was reset, and no
  errors were present in the inspected browser log.

This is not an exhaustive browser matrix or an independent accessibility audit.
The UI keeps one working draft per action/template. Changing the provider updates
that letter; the service retains separately generated records and consent history.

## Remaining live acceptance steps

1. Run the service on the HP device with its text-model endpoint configured; verify
   `local_model_guarded` rather than fallback, and capture the full finding-to-review
   timing. Run a matched human task and retain the baseline.
2. Upload a PNG/JPEG scan in Documents, review/correct the local OCR, and run
   extraction using the configured local vision endpoint. Compare every accepted
   source span with the actual scan.
3. Configure the approved public-search adapter and verify one consented query
   contains exactly company/country and no family fields.
4. Configure a Google OAuth testing client outside the repository and authorize
   a teammate test account through the UI. Create one reviewed draft with a
   fictional attachment and inspect it in Gmail.
5. A person presses Send to the approved demo inbox, confirms sending in Afterword,
   replies from that inbox, and verifies manual plus connected reply tracking.

Record the observed results before calling the full feature plan complete.

## Actual OCR result and rehearsal readiness

Tesseract 5.5.3 on the macOS development machine misread the fixture's
`claims@cedar-life.example` as `clains@cedar-life.example` and omitted its large
heading. That failure is retained in `outreach-ocr-verification.json`, alongside
the actual correction, source-byte check and rejection checks. An exact span
proves agreement with reviewed text, not that OCR itself was correct. This result
is not a Nano vision measurement or a contact-precision score.

The configuration inspection found no text-model name, vision/search endpoint,
Google client configuration or saved Google token file. An explicitly requested
loopback `/models` probe could not reach the default text-model service. Readiness
inspection itself reads only configuration and file metadata; it does not open
token contents or contact external services. The local rehearsal tooling now
captures redacted audit events and artifact hashes without performing the email,
lookup or model actions. See `OUTREACH-LIVE-REHEARSAL.md` for the remaining checks.

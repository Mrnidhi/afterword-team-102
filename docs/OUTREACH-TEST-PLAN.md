# Provider outreach test plan

## Contact and evidence

- Known provider exact domain, subdomain policy, unrelated/spoofed domain, mixed-case address.
- Prefer claims/bereavement/estates/support/service; blacklist every specified sender alias.
- Header From/Reply-To/Return-Path and last 15 body lines; quoted source offsets match stored original.
- MIME encoded headers and multipart plain text; don't lose the source that offsets refer to.
- No contact, no-reply-only, ambiguous identity, duplicate contacts, recent versus old role address.
- Tier ordering records > directory > lookup and explicit user-selected address.
- Reserved fictional domains never handed off; directory aliases require a confirmed controlled inbox.
- All actual archive providers included, including both subscription providers.
- A known sender domain identifies a provider without a display name or manual selection; conflicting known headers remain ambiguous.
- Valid email Date headers supply missing document dates; explicit dates take precedence and invalid/duplicate headers remain unknown.
- Uploaded account references reach the generated letter as masked values with exact source evidence.
- Multiple accounts require a deliberate choice or explicit omission; the newest record does not automatically choose an account.
- References cannot cross providers, use changed source text, or collapse distinct full identifiers merely because the last four characters match.

## Draft and disclosure

- Five templates and permitted finding mappings; correct full name, masked reference and chronology.
- Missing writer/capacity/date/phone placeholders; any unresolved bracket slot blocks all handoffs.
- Model-supplied unsupported email, name, amount, identifier or action rejected by code.
- SSN, full account/policy value and date of birth blocked in subject and body; unknown custom text is not falsely labelled absent.
- Required fields appear in order, compact output; overlong Gmail URL offers a usable copy fallback.
- Exact snapshot hash includes recipient, subject, body and attachment content hashes.
- Edit recipient, body or attachment after review: stale consent cannot be reused.
- Consent actor, timestamp, channel and disclosed fields survive refresh and server restart.

## Handoff and lifecycle

- Google compose URL encodes Unicode, &, #, +, newlines and apostrophes correctly.
- New tab has no opener; blockers and clipboard errors leave a recoverable path.
- Gmail, mailto and clipboard paths require the same disclosure review.
- Opening/copying creates only a handoff record; user must separately mark sent.
- Explicit sent -> waiting; personal reminder +14 calendar days across month/year boundaries.
- Manual reply -> review; sent/replied status idempotence; no duplicate follow-up or consent row on double click.
- Switching templates or findings preserves separate working drafts and returns to the originating evidence.
- Local and backend modes never silently mix histories; reset/export cover outreach state.
- Reloading old outreach history preserves a later manual completion, reopened action or edited reminder; a new explicit outreach transition can update the task.

## Optional integrations

- Lookup refusal yields no network; canonical company/country payload only; caller-supplied query discarded/rejected.
- Public source URL and exact source match required; returned contact starts unverified.
- URL fetching rejects private/loopback destinations and redirect-based bypasses where applicable.
- OCR/vision invented contact cannot pass exact-match gate.
- Scan upload accepts validated bounded PNG/JPEG only; a file selection is not an upload.
- OCR runs locally with fixed arguments and timeout; original image and processing copy retain distinct hashes.
- Image preview bytes match the input; raw OCR remains unchanged after a correction.
- Corrections retain actor/history, reject stale hashes and invalidate review; approved extraction is idempotent.
- Missing OCR fails clearly; missing vision still allows staging/review but cannot ingest contacts.
- Pending scan reviews survive service restart and page reload; no image or OCR text enters browser storage.
- The actual Tesseract fixture test may contain OCR errors; it does not claim perfect transcription or Nano vision execution.
- Readiness inspection reads no token contents and makes no network calls; the optional probe only GETs loopback model metadata.
- Rehearsal reports keep measured events separate from human assertions; a passing observation needs a retained evidence artifact.
- OAuth state replay, wrong state, PKCE, redirect destination and minimal scope handling.
- Draft API creates MIME with only reviewed bytes; no sending API exists.
- Tokens stored outside repository, restricted permissions, deleted on disconnect.
- Additional readonly scope needs separate consent; sent message discovery not inferred from an old draft ID.
- Incoming reply must match the verified thread and sender relationship; own sent/draft messages are not replies.

## Product and regression

- Desktop 1440px and mobile 390px/320px: no horizontal overflow, readable recipient/body, accessible dialog controls.
- Keyboard route/edit/review/cancel paths, focus recovery, labels and status announcements.
- Missing backend, model failure, lookup disabled, OAuth unconfigured, storage failure and save retry shown honestly.
- Existing notes, actions, source links, memories, settings, appearance, autosave, print and export continue to work.
- Static GitHub Pages works below /afterword-team-102/; local full backend serves same static assets.
- After ingest, open the finding associated with the actual provider; scan results refresh that target's contacts even if its previous results were cached.

# Afterword — Team 102

A local family-record workspace built against `afterword.finding/v1`, by Team 102.

[Website](https://mrnidhi.github.io/afterword-team-102/)

A family workspace for organizing the practical work after a loss. The local application ingests individual records, calls the on-device extraction engine, stores exact source text and findings, and presents actions, evidence and memories. The public website remains a clearly separate fictional sample. It is an independent concept for HP ZGX, not an HP product or endorsement. No private credentials or real family records are included in the repository.

## Local extraction application

See [integration requirements](docs/FINDING-INTEGRATION-SPEC.md) and
[integration guide](docs/FINDING-INTEGRATION.md) for the full contract, and
[verified results](docs/FINDING-INTEGRATION-VERIFICATION.md) for observed execution and limits.
The normal `python -m backend.main` command starts the **offline extraction runtime**.
It serves the interface and API together. Extraction calls only the existing chat
model on loopback port 8000. Translation uses ports 8000 and 8003. It does not
start, stop or load a model. Gmail and public-search routes are not mounted.

```sh
python -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
AFTERWORD_PORT=8081 .venv/bin/python -m backend.main
```

Open `http://127.0.0.1:8081`. Default runtime databases are under
`~/Documents/Afterword-Integration/runtime/`. The HP integration checkout,
environment, logs and verification reports live under
`~/Documents/Afterword-Integration/`; teammates' existing services remain intact.

Import EML/MBOX email, SMS CSV (`date,sender,body`), Android SMS XML, text, PDFs,
or images. Each message/page has a stable source identity and is processed
sequentially. The exact extracted text is retained for numbered evidence review.
RapidOCR runs on the CPU using installed local assets. Failed extraction is
visible and can be retried; it never becomes an invented successful finding.

The engine and schema recovered from hp24 are retained under `model/`, with
provenance in [model/README.md](model/README.md). `AFTERWORD_MODEL_DIR` can point
at the team's existing model-code directory. Changing the served weights on
port 8000 needs no backend or UI code change. Run the shared-box status command
before GPU work and coordinate with Prakhar before restarting that server.

Source amounts and derived financial exposure remain separate. Deadlines come
from stated days and the supplied reference date. Verification status does not
establish entitlement, current account status, or a legal deadline.

## Public sample preview and earlier outreach work

The website keeps ten family-facing views:

1. **Overview** — the daily drain (what recurring charges still cost each day, traced to their sources), next action, archive counts and recent browser-local activity.
2. **Action plan** — status/category/search filters, date/amount sorting, notes, reminders, completion/waiting/reopening and CSV export.
3. **Documents** — searchable fictional excerpts, source previews and a validated file-name staging queue. With the local service, scanned PNG/JPEG letters can be read, compared with their OCR text, corrected and submitted to the configured local vision model for source-checked contacts.
4. **Evidence review** — source comparisons, known/unknown distinctions, working review notes, read acknowledgements, timestamps, JSON export and print.
5. **Letters** — provider contacts with source evidence, five templates, family details, exact disclosure review, Gmail/mailto/copy handoff and separately recorded sent/replied states.
6. **Memories** — a typography-led archive of fictional writing with reading dialogs and favorites.
7. **Ask Afterword** — four scripted source-linked examples and an honest unsupported-question response.
8. **Privacy** — storage and connection status, outreach/disclosure history, consent records and export.
9. **Activity** — searchable history of real changes made in this browser, with export.
10. **Settings** — reading size, background motion, JSON export, reset and session-scoped undo.

Hardware promotion, model-routing diagrams and design-research pages are deliberately kept out of the family workflow. Technical architecture and references belong in this document. The overview prioritizes the next action and dates to keep in view.

Global search opens with the search control or Command/Ctrl+K. Evidence topics and sources, letter templates and document previews support hash query links. Source inspection returns to the originating action without discarding working notes. Source-tab changes preserve scroll and keyboard focus. Letters link back to the source review and related action.

All amounts, dates, providers, people and passages are fictional. Provider response dates and user reminders are not statutory deadlines. The policy and will excerpts concern potentially different assets and do not establish a beneficiary entitlement. The medical receipt does not establish the current balance.

## Implementation

The frontend remains buildless HTML, CSS and JavaScript, with no new frontend dependencies. `dist/` is the GitHub Pages website. System fonts allow the interface to run without external font requests. `backend/` is a local FastAPI/Pydantic/SQLite service; GitHub Pages cannot run that service. No analytics are included. Earlier outreach implementation and tests remain in source; its connected Gmail/lookup runtime is separate from the offline extraction application.

- `dist/store.js`: bounded state validation, v2-to-v3 migration, storage failure handling and file metadata validation.
- `dist/app.js`: application shell, routing, task fixtures, overview, dialogs and workspace search.
- `dist/pages.js`: fictional document content and core page renderers.
- `dist/workspace.js`: intake, plan, evidence, drafts, practical privacy, activity and settings workflows.
- `dist/experience.js`: debounced autosave, recovery across reload, focus continuity, contextual help and reversible action notices.
- `dist/ambient.js`, `ambient.css`: original vector daylight scene, local-time tones, persisted pause preference and reduced-motion support.
- `dist/styles.css`, `studio.css`, `workspace.css`: base layouts, HP-inspired design tokens and responsive workflow styling.
- `scripts/version-assets.cjs`: content-based CSS/JS versions to prevent mixed deployments from cached assets.
- `tests/state.test.cjs`: meaningful boundary tests for malformed storage, migration, ID allowlists, date/size limits and write failures.
- `dist/outreach-core.js`, `outreach.js`, `outreach.css`: provider selection, letter review, disclosure rules and handoff UI, with separate browser-local and local-service modes.
- `backend/`: local contact extraction, persistence, draft templates/model adapter, consent gates and optional integrations. There is no email-sending operation.
- `backend/scans.py`, `dist/outreach-scans.js`: bounded local Tesseract OCR, original-scan preview, versioned human corrections and confirmed local vision extraction with exact source spans.
- `data/`: fictional archive, curated provider directory and independent resolver answer key. The public fixture copies under `dist/data/` must match.
- `PLAN.md`, `docs/OUTREACH-TEST-PLAN.md`, `docs/METRICS.md`: feature requirements, verification coverage and measured/unmeasured boundaries.
- `backend/drain.py`, `backend/buckets.py`, `data/charge_buckets.json`, `dist/drain.js`, `drain.css`: the daily drain counter — charges read from document text with verbatim quotes, safety-first stoppable / keep-for-now / decide-later rules, `GET /drain` and `POST /estate/date-of-death`, the overview card, breakdown and plan captions. `dist/data/drain_snapshot.json` carries the backend's figures to the static site. See `docs/DRAIN-COUNTER.md`.

Tasks, reminders, notes, read marks, favorites, drafts, file metadata, reading size and background motion persist under `afterword-workspace-v3`. Legacy `afterword-design-v2` data is validated and migrated. Working notes and drafts autosave after a short typing pause and flush on navigation or page exit. Invalid reminder entries remain visibly unsaved until corrected. The last edited letter template is restored. Stored input is escaped before rendering; CSV exports neutralize formula-like values. Storage failure is visible and export remains available.

Outreach currently keeps one working letter per action and template in the browser, including when two providers share an action. Selecting another provider updates that working letter; it does not create a separate provider-specific tab. The local service retains separately generated draft records and immutable consent snapshots, and reviewed handoffs remain available in Privacy.


The original static file queue accepts PDF, TXT, CSV, EML and Markdown names, up to 20 MB per file, 20 files and 100 MB total. In static mode that queue stores metadata only. Local outreach ingestion and optional scan processing are separate, explicit operations on the local service. Browser storage and the local SQLite database are not application-encrypted; use fictional files and details for this prototype.

The app also feature-detects the browser's experimental WebMCP API and registers one read-only tool for the fictional action plan. It grants no external access. Ordinary UI operation does not depend on this API.

To run locally, serve `dist/` with any static server. There is no dependency installation or build step. Optional local frontend checks:

```sh
node tests/state.test.cjs
node tests/outreach.test.cjs
node tests/outreach-integrations.test.cjs
node tests/outreach-scans.test.cjs
node tests/outreach-navigation.test.cjs
node tests/findings-core.test.cjs
node tests/findings-ui.test.cjs
node tests/drain.test.cjs
node scripts/check-outreach-data.cjs
node scripts/version-assets.cjs
node scripts/version-assets.cjs --check
```

These checks run locally when requested. There is no automated CI/CD workflow.

## Run the earlier outreach service

This optional runtime permits explicitly configured external integrations. Use
the offline extraction application above for the contract demo.

Use Python 3.9 or newer in a virtual environment:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m uvicorn backend.main:create_app --factory --host 127.0.0.1 --port 4173
```

Open `http://127.0.0.1:4173/`. The server serves the existing frontend and its API
on the same origin. `--port` selects another port. By default the SQLite
database is stored outside the repository under `~/.local/share/afterword/`;
`AFTERWORD_DB` can select a different local path. The service binds to loopback and
rejects unapproved origins/hosts. This is a single-workspace local prototype, not
a publicly authenticated multi-tenant service.

Set `AFTERWORD_LLM_URL=http://127.0.0.1:8000/v1` and
`AFTERWORD_LLM_MODEL=<the-served-model-name>` for a local OpenAI-compatible model.
Model access must stay on the local machine; no cloud model is substituted.
The model returns declared slots and a tone choice. Code checks each fact against
the supplied values before rendering one of the five local templates. If the
model is unavailable or invents a value, the application reports template mode
and retains the validated template. This is not evidence of a measured HP model run.

Configure an approved demo inbox in Settings. No example address from the feature
plan is assumed to belong to the team. Gmail inboxes can use plus-addresses;
other approved inboxes use the exact supplied address. This setting stays in the
local workspace and must not be committed to the public provider directory.
Reserved `.example` contacts in the source fixtures demonstrate provenance and
are blocked from email handoff.

The required path works without Google OAuth: review the recipient, full message,
disclosure summary and attachment checklist, then open Gmail, open a mail app or
copy the letter. Opening Gmail transfers the reviewed message text to Google;
it does not send the message. `Mark as sent` is a separate family confirmation,
which sets a personal reminder for 14 days later. No legal deadline is inferred.

Optional public lookup, local scan extraction, Google OAuth draft creation and
readonly reply tracking require explicit configuration and separate permissions.
See `docs/OUTREACH-INTEGRATIONS.md`. Google's `gmail.compose` scope itself includes
send capability; Afterword implements only draft creation. It neither requests
the separate `gmail.send` scope nor exposes a send endpoint. Tokens and attachment
files stay outside the repository. Automated tests use injected transports and
cannot establish a live OAuth, mailbox delivery or Nano result.

Run backend verification and the independent fixture evaluation:

```sh
.venv/bin/python -m pytest tests/ -q
.venv/bin/python scripts/evaluate_outreach.py
.venv/bin/python scripts/evaluate_drain.py
```

After changing the archive, `data/charge_buckets.json` or `backend/drain.py`, regenerate the static site's drain figures with `.venv/bin/python scripts/drain_snapshot.py`; a test fails while that file is stale. The date of death for the daily drain is entered by the family and stored only in the local database.

## Use a reference from the records

The local service identifies a provider from an unambiguous known email sender
domain when no provider was selected during upload. Valid email Date headers are
used when a document date was not supplied; conflicting provider headers and
invalid dates are not guessed. Source matching is not independent authentication
of the sender.

Letters use account or policy references found in the selected provider's stored
records. Only the masked ending is inserted into the letter. A single reference
can be selected automatically; multiple references require the family to choose
the source or explicitly leave the reference out. Newer correspondence does not
establish which account the family intends to discuss, and matching last four
characters do not prove two accounts are the same.

Changing providers does not silently rewrite an edited letter. A reference from
the previous provider blocks handoff until the letter is prepared again with the
correct source or an explicit omission. Source evidence is checked again during
review. The consent snapshot includes the selected reference as well as the
provider and exact letter contents.

## Earlier outreach scan workflow (optional)

This section applies only to the earlier outreach factory runtime above. The
offline extraction application uses CPU RapidOCR through `/ingest/preview` and
`/ingest/extract`; it does not use Tesseract, a vision model or `/scans`.

The scan workflow requires the local service; GitHub Pages cannot run OCR or a
model. Python dependencies, including Pillow image validation, are installed by
`pip install -r requirements.txt` above. Install the separate **Tesseract** command
and its English (`eng`) language data on the machine running the service:

```sh
# macOS with Homebrew; the standard package includes English data.
brew install tesseract

# Debian/Ubuntu, including an Ubuntu-based HP environment.
sudo apt-get update
sudo apt-get install tesseract-ocr tesseract-ocr-eng
```

Use the commands for your operating system, then check `tesseract --list-langs`
includes `eng`. The service searches its own `PATH`. If necessary, set
`AFTERWORD_TESSERACT_BIN` to the absolute executable path before starting it; for
example, `/opt/homebrew/bin/tesseract` on an Apple Silicon Homebrew installation.
This setting is an operator-controlled executable path, never a browser-supplied
command. OCR uses fixed arguments, English text recognition and a 30-second
execution timeout.

In **Documents**, open the scanned-letter workflow, choose the provider and
optional source date, and select a single PNG or JPEG. Import is explicit; simply
selecting an image does not upload it. Supported scans are at most **6 MB**, **20
megapixels** and **12,000 pixels on either side**. Animated images and PDFs are not
accepted by this workflow. The derived processing image must also fit 6 MB;
otherwise the user is asked to crop the scan. Extracted text is limited to
200,000 characters. The original static PDF staging queue is separate and does
not perform PDF-to-image conversion.

Compare the original scan with the recognized text before proceeding. Correct
misread characters, enter the reviewer's name and save the corrections. Every
correction changes the text hash and clears the UI's previous review confirmation.
The service retains the original image bytes and hash, a separate sanitized
processing copy and hash, and the original OCR text and hash. Corrected text has
its own version, hash, actor and timestamp; it never replaces the raw OCR record.
After extraction, that source is immutable and a changed source must be imported
as a new scan. Contact evidence offsets refer to the reviewed text, explicitly
labelled as human-corrected OCR when applicable—not to an assertion that the
original OCR recognized those corrected characters.

Scan files stay outside the repository in `~/.local/share/afterword/scans/`.
`AFTERWORD_SCAN_DIR` can select another private directory outside the repository.
Directories use permission `0700`, source/processing files use `0600`, and OCR
scratch files are removed after processing. Stage metadata, OCR versions and
review history use the existing local SQLite database. This is local filesystem
access control, not application encryption. Scans are never automatically attached
to an email.

**OCR staging, preview and corrections work without a vision model.** Contact
extraction requires a real locally served vision-capable model, configured with
`AFTERWORD_VISION_ENDPOINT` (for example,
`http://127.0.0.1:8000/v1/chat/completions`) and `AFTERWORD_VISION_MODEL` set to its
served model name. The endpoint must be loopback HTTP. Without it, the preview
remains saved and extraction reports that the model is unavailable; it does not
invent contacts or report a successful model run. After explicit confirmation,
the same source hashes are checked again, the local vision model reads the
processing image, and contacts are retained only when their values and offsets
match the reviewed text. Email contacts must also match the selected provider.

`GET /scans/status` reports OCR, image-validation and vision readiness separately.
`POST /scans` stages OCR; `PATCH /scans/{id}` records a correction with the previous
text hash and actor; `POST /scans/{id}/confirm` requires the current image/text
hashes and explicit confirmation. Pending scans can be reopened from the Documents
view without re-uploading their source.

The fictional scan fixture has been processed with real Tesseract on the
developer's machine. It exposed an OCR error (`claims` read as `clains`), which is
why the comparison and correction step is required. The Python scan suite includes
optional real-engine tests when Tesseract is installed; model-orchestration tests
use explicit fakes. This evidence is **not** a Nano benchmark, a live vision-model
result or a claim of perfect OCR. The current validation report keeps those
boundaries separate.

## Hosting on GitHub Pages

The existing public sample is hosted on GitHub Pages. Repository CI/CD workflows
have been removed, so pushes do not build, test or publish the website. Updating
the hosted sample requires a separate publishing setup. Local development and
manual tests remain available.

`dist/` contains the static website; backend services, databases and private
records are not part of the hosted sample. All asset URLs are relative to support
`/afterword-team-102/`. The website and repository are public; use fictional
records only.

The `.openai/hosting.json` file records the earlier private design-preview target.
It is historical configuration and does not trigger deployment on a Git push.

## Design rationale and research

Read September 2026. These are design inputs, not evidence of clinical efficacy, legal correctness, commercial uniqueness, sponsor endorsement or validated outcomes for bereaved families.

- [Generative Interfaces for Language Models, August 2025](https://arxiv.org/html/2508.19227v1): structured, task-specific representations informed the separate planning, evidence and document surfaces. Evaluation used 100 generated prompts and preference judgments; it does not establish estate-task correctness. A polished interface can increase perceived credibility, so sources and unknowns remain visible.
- [In-Situ Adaptive Interfaces for Online Browsing, IUI 2026](https://gracekim.me/docs/AdaptiveInterfaces.pdf), [DOI](https://doi.org/10.1145/3742413.3789092): explicit control, persistent preferences and reversibility informed the interface. A qualitative probe with 10 frequent shoppers, not a controlled workload study or bereavement study. Navigation remains stable.
- [Improving Human Verification of LLM Reasoning through Interactive Explanation Interfaces, October 2025](https://arxiv.org/html/2510.22922v1): informed source inspection and highlighted excerpts. The experiment analyzed 125 undergraduates reviewing math explanations with injected errors; its results cannot establish Afterword's accuracy or speed.
- [Google Material 3 Expressive research](https://design.google/library/expressive-material-design-google-research): purposeful visual hierarchy and prominent next actions, adapted to a restrained setting.
- [Microsoft Fluent 2 color](https://fluent2.microsoft.design/color), [motion](https://fluent2.microsoft.design/motion), [accessibility](https://fluent2.microsoft.design/accessibility): neutral reading surfaces, limited semantic color, brief transitions and reduced motion.
- W3C WCAG 2.2 guidance on [contrast](https://www.w3.org/WAI/WCAG22/Understanding/contrast-minimum.html), [reflow](https://www.w3.org/WAI/WCAG22/Understanding/reflow.html), [target size](https://www.w3.org/WAI/WCAG22/Understanding/target-size-minimum), and [consistent help](https://www.w3.org/WAI/WCAG22/Understanding/consistent-help.html). Implementation checks are not an independent accessibility certification.
- Service references for wording and workflow: [Empathy](https://www.empathy.com/solutions/loss-support), [Sunset](https://www.hellosunset.com/), [Settld](https://www.settld.care/). No visual identity was copied. These services also make novelty claims inappropriate.

The September 24 visual refresh uses graphite, silver, white and restrained cobalt, inspired by [HP’s ZGX Nano product design](https://www.hp.com/us-en/workstations/zgx-nano-ai-station.html). Plus Jakarta Sans gives the interface a precise geometric character; original document and memory passages keep their reading typography. Amber identifies uncertainty with an accompanying text label. This is an independent concept, not an HP product or an endorsed service. There is no grief score, emotional countdown or celebration animation.

HP supplies the visual reference for the neutral workstation aesthetic; its hardware photography and promotional content are not part of the family interface.

## Production boundary and next engineering work

The outreach service implements one bounded backend workflow. It does not make
the entire estate-processing product complete. Production authentication,
multi-user roles, independently verified authority, encrypted storage, a complete
document-analysis pipeline, retrieval, jurisdiction-specific rules and lifecycle
management still require implementation and evaluation. The consent gate records
the family's stated intent; it does not establish legal authority.

The planned HP deployment uses local parsing and model inference with explicit
family review. Model selection and fine-tuning remain separate from this feature.
No latency, memory, accuracy or security results on HP hardware are claimed here.
Public contact lookup contains only a curated company name and country, and
requires its own approval. That approval cannot authorize sharing a family letter.

A production service should maintain immutable source records with span coordinates; version findings separately from source facts; store user review as an acknowledgement rather than truth; and make letter preparation distinct from any external sending. UI actions should call authorization-checked services instead of mutating browser fixtures. A realistic first backend slice is text-native files → extracted spans → insurance or billing comparison → human-reviewed information request.

## Verification notes

Provider outreach has a separate, current requirement-by-requirement report in
[`docs/OUTREACH-VERIFICATION.md`](docs/OUTREACH-VERIFICATION.md). The checks below
describe the earlier workspace release; they do not establish live Google or HP
verification for the new feature.

JavaScript syntax and state-boundary tests pass. Browser checks covered all ten product routes at 390px and 320px, with no page-level or main-content horizontal overflow after fixes; the product views also fit 320px with the larger 18px reading preference. Desktop and phone layouts were visually inspected. The final ten-view navigation was rechecked at 320px after removing the showcase pages.

Interaction checks covered independent draft save/reload and evidence-to-letter restoration; reminders/notes and source-return context; working review notes across source changes; read/undo; file picker validation for valid/unsupported/empty sample files, staging persistence and removal; activity search; payload preview; reset/undo draft restoration; and mobile navigation. Browser error logs were empty. Downloads provide a selectable fallback, since the in-app browser does not reliably report download events. Printing opens the browser print flow with dedicated print styles; physical print output was not tested. These checks are not a full accessibility audit.

## UX acceptance and validation

The user’s 4.9/5 aspiration is a target, not a measured rating or a guarantee. No satisfaction study or 100,000-user deployment has been performed. [UX-VALIDATION.md](UX-VALIDATION.md) defines the user journeys, success criteria and responsible evaluation sequence.

## Ambient appearance

Overview and Memories have an original vector background inspired by softly folded paper in daylight. Three shapes move on 32–44 second transform cycles; the local clock selects morning, day, evening or night colors. No location access, external imagery, video, canvas, tracking or inference is used. Other task pages and reading surfaces stay stationary.

Background motion can be set to Gentle motion or Still in Appearance preferences. The preference persists in the existing validated store. Operating-system reduced motion always overrides animation; forced-colors mode and printing omit the artwork. Motion also pauses when the artwork is offscreen, a dialog is open or the tab is hidden. The scene lives outside the rerendered app so actions do not restart it. Clock checks run once per minute only while the scene is moving.

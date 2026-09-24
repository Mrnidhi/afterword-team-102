# Afterword — Team 102

An Afterword prototype with a local provider-outreach service, by Team 102.

[Website](https://mrnidhi.github.io/afterword-team-102/) · [Deployment workflow](https://github.com/Mrnidhi/afterword-team-102/actions/workflows/pages.yml)

A family workspace for organizing the practical work after a loss. The public website uses fictional records for Arun Rao and Priya Rao. A Python service adds local provider contact mining, reviewed email preparation and consent/outreach persistence. It is an independent concept for HP ZGX, not an HP product or endorsement. No private credentials or real family records are included in the repository.

## Open and explore

The website keeps ten family-facing views:

1. **Overview** — next action, archive counts and recent browser-local activity.
2. **Action plan** — status/category/search filters, date/amount sorting, notes, reminders, completion/waiting/reopening and CSV export.
3. **Documents** — searchable fictional excerpts, source previews and a validated file-name staging queue with removal, empty and error states.
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

The frontend remains buildless HTML, CSS and JavaScript, with no new frontend dependencies. `dist/` is the GitHub Pages website. Google Fonts supplies Plus Jakarta Sans, with system-font fallbacks. `backend/` is an optional local FastAPI/Pydantic/SQLite service; GitHub Pages cannot run that service. No analytics are included.

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
- `data/`: fictional archive, curated provider directory and independent resolver answer key. The public fixture copies under `dist/data/` must match.
- `PLAN.md`, `docs/OUTREACH-TEST-PLAN.md`, `docs/METRICS.md`: feature requirements, verification coverage and measured/unmeasured boundaries.

Tasks, reminders, notes, read marks, favorites, drafts, file metadata, reading size and background motion persist under `afterword-workspace-v3`. Legacy `afterword-design-v2` data is validated and migrated. Working notes and drafts autosave after a short typing pause and flush on navigation or page exit. Invalid reminder entries remain visibly unsaved until corrected. The last edited letter template is restored. Stored input is escaped before rendering; CSV exports neutralize formula-like values. Storage failure is visible and export remains available.

Outreach currently keeps one working letter per action and template in the browser, including when two providers share an action. Selecting another provider updates that working letter; it does not create a separate provider-specific tab. The local service retains separately generated draft records and immutable consent snapshots, and reviewed handoffs remain available in Privacy.


The original static file queue accepts PDF, TXT, CSV, EML and Markdown names, up to 20 MB per file, 20 files and 100 MB total. In static mode that queue stores metadata only. Local outreach ingestion and optional scan processing are separate, explicit operations on the local service. Browser storage and the local SQLite database are not application-encrypted; use fictional files and details for this prototype.

The app also feature-detects the browser's experimental WebMCP API and registers one read-only tool for the fictional action plan. It grants no external access. Ordinary UI operation does not depend on this API.

To run locally, serve `dist/` with any static server. There is no dependency installation or build step. Before committing frontend changes, run:

```sh
node tests/state.test.cjs
node tests/outreach.test.cjs
node tests/outreach-integrations.test.cjs
node scripts/check-outreach-data.cjs
node scripts/version-assets.cjs
node scripts/version-assets.cjs --check
```

The deployment workflow also syntax-checks every frontend JavaScript file.

## Run the local outreach service

Use Python 3.9 or newer in a virtual environment:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m backend.main
```

Open `http://127.0.0.1:4173/`. The server serves the existing frontend and its API
on the same origin. `AFTERWORD_PORT` selects another port. By default the SQLite
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
```

## Hosting on GitHub Pages

GitHub Pages is the selected host. The workflow in `.github/workflows/pages.yml` validates the JavaScript and uploads only `dist/`, then deploys it to the `github-pages` environment. A push to `main` that changes the website or workflow triggers deployment; it can also be run manually from Actions. All asset URLs are relative, so the app works under the repository path `/afterword-team-102/`.

The repository uses GitHub Actions as its Pages publishing source. The public
static site needs no API key or paid hosting. The local service and its database
are not uploaded as a Pages artifact. Official actions are pinned to verified
release commit hashes. The website and repository are public; use fictional
records only. CI validates both the Python service and the static frontend.

The `.openai/hosting.json` file records the earlier private design-preview deployment. It is retained as historical configuration, not the active GitHub deployment configuration. Updating this repository deploys through GitHub Pages, not the earlier host.

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

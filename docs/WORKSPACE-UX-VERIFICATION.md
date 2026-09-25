# Workspace and outreach fixes

## Behavior

The static preview now introduces the workspace, saves a browser-local profile, and lets a person correct missing letter details directly in the editor. Profile details can be explicitly reused in a letter without silently replacing authored text. An approved demo inbox replaces fictional provider addresses only when the person chooses it.

Running `python -m backend.main` adds a password-protected, single-family local workspace. Profile data and hashed sessions are stored in SQLite on the device. Passwords use salted scrypt; the browser receives an HttpOnly, SameSite cookie. Sign-out and expired sessions clear the visible private workspace. The application factory retains an optional gate for existing integrations; deployment entry points should explicitly require login.

Spanish interface labels work without a model connection. Original documents, names and user-authored letters retain their language; translating those still requires the local translation service. Action Plan and Activity export actual PDFs using bundled, locally loaded fonts and PDF tooling.

Email remains a compose handoff. Afterword does not select or verify the sending account and does not send automatically. The review explains that Gmail may use the account already signed in, and requires a sender-check acknowledgement before opening an email app. A dedicated team mailbox should be used for demonstrations. Opening compose, pressing Send, and recipient delivery are separate events.

## Local run

Install `requirements.txt`, then run from the repository root:

```sh
AFTERWORD_REQUIRE_LOGIN=1 python -m backend.main
```

The default runtime folder is `~/Documents/Afterword-Integration/runtime`. `AFTERWORD_WORKSPACE_DB` overrides the profile database path; `AFTERWORD_DATA_DIR` overrides its containing runtime folder. Existing database overrides for outreach, findings and translations remain available. Keep these databases and session cookies out of Git.

The initial workspace setup is intended for the owner on the loopback-bound device. This is not a multi-account service. Password recovery, database encryption at rest, a hosted account system and a dedicated outbound email service are outside this change.

## Verification performed on September 25, 2026

- Python suite after integrating current main: 350 tests passed, covering the new workspace API, password/session handling, existing backend services and route protection. Four pre-existing FastAPI deprecation warnings remain.
- All JavaScript test suites, syntax checks, outreach fixture parity, deterministic outreach evaluation and asset hash validation passed.
- Computer-use testing in the actual static UI covered onboarding, profile edits and validation, letter field correction, approved-inbox selection, review consent, sender acknowledgement, route/reload persistence, search, action status/notes/reminders, document filtering and excerpts, evidence notes, memories, activity, privacy and reading preferences.
- Spanish was selected without a connected translation service, persisted across reload, then switched back to English. Authored content stayed unchanged.
- The local backend UI was tested against an isolated disposable database: initial setup form, incorrect-password recovery, successful sign-in, profile edit/save/reload and sign-out. Database read-back confirmed the saved phone. Setup submission was exercised through the API; password creation was not submitted through computer use.
- Real browser PDF downloads were opened and rendered. The plan with a saved note spans three readable pages containing all seven actions; the activity report contains five events on one page. The clean seven-action fixture also has a two-page regression check. Larger multilingual stress reports cover pagination and unsupported-character handling.
- One explicitly authorized, non-sensitive test email was sent and found in the sender's Gmail Sent folder. Recipient delivery was not verified. No further email was sent after the personal-sender concern. The subsequent sender-check failure path was verified without opening compose.

Responsive verification is limited: the browser viewport override did not reliably produce the requested 390-pixel viewport. The welcome-heading contrast was corrected and narrow rendering was inspected, but this is not a completed device/browser accessibility matrix. No fresh HP inference benchmark or HP deployment was performed for this change.

## Version control and deployment

Changes are isolated on `fix/workspace-onboarding-and-outreach` and proposed through a pull request. CI validates pull requests; Pages configuration, artifact upload and deployment are skipped for pull-request events. The current public site and HP checkout remain unchanged until a separate integration/deployment step.

The latest main branch (`d179d25`) was merged without rewriting teammate commits. The daily drain overview and source breakdown were checked in the browser, and its API was checked before login, after setup and after logout. Existing drain limitations remain: its date setting is separate from the letter/profile date, and it computes from the outreach records rather than the live findings database.

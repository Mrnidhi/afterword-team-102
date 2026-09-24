# Optional outreach integrations

These modules are implemented and tested with injected responses. No Google account,
live search adapter, HP vision endpoint, real attachment or controlled mailbox has
been connected by these tests. The installed app reports unavailable integrations
instead of simulating successful external calls.

## Local configuration

The backend and browser must run on the same origin. The middleware accepts only
configured local hostnames and protects state-changing requests. Do not expose the
demo backend publicly; it is a single-family local prototype, not a multi-tenant
authenticated service.

Optional operator environment settings:

| Setting | Purpose |
| --- | --- |
| `AFTERWORD_LOOKUP_ENDPOINT` | HTTPS search adapter, described below |
| `AFTERWORD_LOOKUP_TOKEN` | Optional adapter bearer token, never stored in source |
| `AFTERWORD_VISION_ENDPOINT` | Loopback HTTP OpenAI-compatible chat-completions endpoint |
| `AFTERWORD_VISION_MODEL` | Model already installed on the local HP runtime |
| `AFTERWORD_GMAIL_CLIENT_ID` | Google OAuth web application client ID |
| `AFTERWORD_GMAIL_CLIENT_SECRET` | Client secret provided outside source control |
| `AFTERWORD_GMAIL_REDIRECT_URI` | Exact registered callback, e.g. `http://127.0.0.1:8787/integrations/gmail/callback` |
| `AFTERWORD_GMAIL_TOKEN_FILE` | Defaults to `~/.local/share/afterword/gmail-tokens.json`; must be outside repo |
| `AFTERWORD_ATTACHMENT_DIR` | Defaults to `~/.local/share/afterword/attachments`; must be outside repo |

Never put secrets in `dist/`, GitHub Pages, `.env` committed to Git or a browser
query string. OAuth credentials and tokens are only read by the local backend.
Tokens and attachment files are created with mode 0600. Parent directories created
by the application use 0700. A shared system still needs appropriate OS protection.

## Public lookup

`GET /providers/lookup-preview?finding_id=…&country=US` returns the exact query,
company/country payload and its SHA-256 digest. `POST /providers/lookup` requires
that digest, explicit approval and an actor. It accepts no free-form query,
document, name, identifier or amount. The canonical company comes from the curated
directory. Unknown providers must first be curated by the operator.

The operator adapter receives `POST {"query":"Company US public bereavement claims contact"}`
and returns `{"pages":[{"url":"https://public-source/contact","text":"Verbatim source text"}]}`.
The adapter is responsible for fetching public pages; Afterword does not fetch
arbitrary URLs returned by it. Redirects from the configured adapter are rejected.
The adapter hostname is resolved once, every DNS answer must be public, and the
HTTPS connection pins that resolved address while retaining hostname/TLS checks.
Environment proxies are disabled for integration requests.
Text and result counts are bounded. Only exact email matches are proposed; no-reply
addresses are excluded. Each candidate retains source URL and exact text offsets,
starts unverified, and needs human confirmation. A source page cannot instruct the
application to mark its content verified. All attempted external lookups log the
approved minimized payload and success/failure without logging credentials.

## Scan extraction

Ingest OCR text locally with its provider association, then POST a PNG/JPEG base64
scan to `/documents/{id}/vision-contacts`. The vision call uses only a configured
loopback endpoint; redirects are refused. Proposed email, phone, postal and portal
values are retained only when they match the stored OCR exactly. Evidence offsets
refer to that original text. OCR correctness itself must still be checked on the
actual scan; a verbatim gate cannot repair OCR errors. Account hints never bypass
the draft's masking and sensitive-field checks.

## Gmail connection and permission boundaries

Create a Google Cloud OAuth web client, enable Gmail API, register the exact local
callback, keep the consent application in testing and add the demo teammates as
test users. Testing mode does not establish production verification eligibility.
Use the connection screen to authorize drafts. Reply tracking is a separate opt-in.

**`gmail.compose` grants Google-level draft management AND sending capabilities.**
It is not a draft-only permission. Afterword does not request `gmail.send` and its
client exposes no send operation: an explicit operation allowlist permits only
draft creation and separately authorized reading. The family presses Send in Gmail.
This distinction must remain visible in the pitch and consent UI.
[Google scope definitions](https://developers.google.com/workspace/gmail/api/auth/scopes).

Authorization uses a random, expiring, single-use state, a browser-bound HttpOnly
cookie, PKCE and the exact configured callback. Codes are not exposed to page
scripts. Tokens are refreshed locally, not returned to the browser. Disconnect
tries Google's revocation endpoint and deletes local tokens even when offline;
the response explicitly reports whether remote revocation was confirmed.
[Google OAuth flow](https://developers.google.com/identity/protocols/oauth2/web-server).

## Reviewed drafts and attachments

Each create request requires the current review hash and a `gmail_api` consent.
The hash covers recipient, subject, body, checklist and actual attachment file
identifiers, names, sizes and SHA-256 hashes. Uploads are staged locally; uploading
does not disclose them to Google. Preview/download each file, explicitly record
review, then approve the final content together. Any edit or staged-file change
invalidates prior consent. Byte hashes are checked again immediately before MIME
construction. Supported attachments are PDF, UTF-8 text, PNG and JPEG; limits are
five files and 10 MB combined. A declaration that no documents are attached cannot
be sent with files. Draft MIME uses RFC 2822 formatting and base64url encoding.
[Google draft creation](https://developers.google.com/workspace/gmail/api/guides/drafts).
The connected account's sender address is obtained through `users.getProfile`,
which supports the existing compose scope; it is never guessed from a letter.
[Profile permissions](https://developers.google.com/workspace/gmail/api/reference/rest/v1/users/getProfile).

Draft creation is recorded as creation, never as sending or delivery. Reusing a
successful consent returns its previous result. An ambiguous network failure is
not retried automatically; check Gmail before creating a new reviewed request.
Google's REST Draft resource does **not** document a browser draft permalink.
The response intentionally opens the Drafts folder and names the subject to select;
an unverified opaque draft-ID URL is not presented as a guaranteed deep link.

## Optional reply detection

Authorize `gmail.readonly` separately. After personally sending and marking the
outreach sent, the check endpoint searches for the generated RFC Message-ID in
sent mail. It validates the actual sent message's labels, recipient and subject
before using that message's current thread ID. An incoming message must be later,
from the selected recipient and reference the original Message-ID; drafts, own
sent mail, spam, trash and unrelated senders are not counted as replies. If Gmail
rewrites the identifier, report unavailable and use manual reply tracking. No
background polling is enabled without a caller; the user can check on demand.
[Gmail thread retrieval](https://developers.google.com/workspace/gmail/api/guides/threads).

## Verification

Run `.venv/bin/python -m unittest tests.test_outreach_integrations -v`.
Run `node tests/outreach-integrations.test.cjs` for the optional dialog contract:
no consent is recorded before final approval or when Gmail is unconfigured; the
completed attachment snapshot and actual consent reach the core UI; Mark as sent
uses that exact consent rather than a previous review without attachments.
Tests use fakes for search, vision and all Google HTTP calls. They cover approval
refusal, minimized payloads, source evidence, failed escalation logs, OCR matching,
OAuth expiry/replay/cookie/PKCE/scopes, consent binding, MIME and byte hashes,
send-operation denial, token permissions/refresh/disconnect and sent-message/reply
disambiguation. A live rehearsal remains required for OAuth project policy,
browser cookie flow, local GPU behavior, actual Gmail draft creation, attachment
rendering and real replies from a controlled mailbox. Never use real providers for
demo mail. No live performance or contact-precision result is claimed here.

# Feature plan — Provider outreach ("Send it with one click")

Afterword already finds *what* needs doing. This feature answers *who to contact*
and *how to reach them*, then hands Priya a ready-to-send email she only has to
read and press Send on.

Scope: contact resolution + letter-to-email + Gmail handoff + reply tracking.

---

## 1. Principles (do not compromise these)

1. **Afterword never sends mail by itself.** One click opens Gmail with
   everything filled in, or creates a Gmail *draft*. A human presses Send.
   The UI must never contain a button that transmits on the family's behalf.
2. **No invented recipients.** An email address is only shown if it came from
   one of three sources, each displayed with a provenance badge:
   - **From his records** — the address appears verbatim in a document in the
     archive (email header, letterhead, statement footer).
   - **From the offline directory** — a small curated JSON shipped in the repo.
   - **Looked up** — an escalated, redacted web lookup the family approved,
     shown with the source URL. Marked "please verify" until confirmed.
3. **Escalation rule for lookups.** The lookup query contains only a company
   name and a country ("Pacific Crest Life bereavement claims contact"). No
   names, no policy numbers, no amounts. This is the router's canonical
   escalate-safe case, and it is logged like any other escalation.
4. **Disclosure is a separate gate from escalation.** The email body *does*
   contain personal information — that is its purpose. It leaves the device
   only through a deliberate, logged act of consent by the family, after a
   "here's exactly what you're about to share" review screen.
5. **Minimum necessary disclosure.** Default to masked identifiers (policy
   ending 4471, not the full number). Never put a Social Security number,
   full bank account number or date of birth in an email body by default;
   if the provider requires it, tell the family to use the provider's secure
   portal or post instead.

---

## 2. User flow

```
Finding ("possible life insurance policy")
   └─ Resolve provider ──> candidate recipients + provenance + confidence
        └─ Choose template ("Request policy information")
             └─ Draft generated locally (LLM on the Nano)
                  └─ Review screen: recipient, subject, body, what's disclosed
                       └─ [Open in Gmail]  or  [Create Gmail draft]
                            └─ Priya presses Send in Gmail
                                 └─ Mark as sent ──> task becomes "Waiting for a reply"
                                      └─ (optional) reply detected ──> "They replied"
```

The existing Letters view already has templates, preview and export. This
feature extends it: add a recipient block at the top and a send-handoff block
at the bottom. The existing Action plan already has `waiting` and `review`
states — reuse them rather than inventing new ones.

---

## 3. Provider contact resolution

### Tier 1 — From his records (highest trust, fully local)
Mine the archive for contact details, during ingest:

- **Email headers:** `From`, `Reply-To`, `Return-Path` on any message whose
  sender domain matches a known finding's institution. Prefer role addresses
  (`claims@`, `support@`, `service@`, `bereavement@`) over no-reply and
  marketing addresses. Explicitly blacklist `noreply@`, `no-reply@`,
  `donotreply@`, `notifications@`, `marketing@`.
- **Email signature/footer blocks:** run a regex for email addresses and phone
  numbers over the last ~15 lines of each message body.
- **Scanned letters and statements:** the vision model extracts the contact
  block (address, phone, email, web) from the letterhead or the "contact us"
  footer. Require a verbatim string match back into the OCR text before storing.
- **Account hints:** capture the policy/account number that appears alongside
  the contact block, so the draft can reference the right identifier.

### Tier 2 — Offline directory (local, curated by us)
`data/providers_directory.json`: for each fictional provider in the Arun Rao
archive, a record with the bereavement/claims contact. For the demo these are
addresses **we control** (see §7). Ship it in the repo so the feature works on
a device with no network at all — which is the whole point of edge-first.

### Tier 3 — Escalated lookup (router path, optional, consented)
If tiers 1 and 2 fail, offer: "We couldn't find a contact for X in his records.
Would you like us to look up their public bereavement contact? We'd send only
the company name — nothing about your family." On approval, the router performs
a redacted web lookup, returns the address **with its source URL**, and logs the
escalation. The result is always marked "please verify".

### Data model

```python
Provider:
  provider_id: str
  display_name: str
  aliases: list[str]                 # fuzzy-matching help
  channels: list[Channel]            # email / phone / postal / portal
  source_kind: "records" | "directory" | "lookup" | "user"
  evidence: list[Evidence]           # doc_id + verbatim quote + offsets, or URL
  confidence: float
  verified_by_user: bool

Channel:
  kind: "email" | "phone" | "postal" | "portal"
  value: str
  label: str                          # "Claims", "Customer service"
  preferred: bool
```

### Ranking rule
`records` > `directory` > `lookup`. Within a tier, prefer role addresses
matching `claims|bereavement|estates|support|service`, then most recent
document date. Show the top candidate, with the others in a "use a different
address" list. Always let the family type their own.

---

## 4. Draft generation

Runs entirely on the Nano. Templates live in `backend/templates/` as text with
slots, and the local LLM only adapts tone and fills slots from the finding —
it never invents facts, addresses or amounts.

Templates to ship:

| Template | For findings of type |
|---|---|
| Request policy information | insurance |
| Notify of death & request account status | account, bank, pension |
| Cancel a recurring service | subscription |
| Request a final statement / balance confirmation | debt, bill |
| Request records or a duplicate document | admin, asset |

Every draft body includes, in this order: who is writing and in what capacity;
the deceased's full name and date of death; a masked identifier; a numbered
list of what is being requested; what documentation is enclosed or can be
supplied; and a contact line. Keep it under ~200 words — providers reply faster
to short, specific requests.

**Slots the family must fill** stay as visible placeholders: `[YOUR FULL NAME]`,
`[YOUR PHONE]`, `[DATE OF DEATH]`, `[YOUR RELATIONSHIP / AUTHORITY]`. Block the
send handoff until no `[...]` placeholders remain, and say why.

---

## 5. The Gmail handoff

Three implementations. Ship A, then B if time allows. Never C.

### A. Gmail compose URL (P0 — do this first)
```
https://mail.google.com/mail/?view=cm&fs=1&to=<to>&su=<subject>&body=<body>
```
- Everything URL-encoded; open in a new tab with `rel="noopener"`.
- Works instantly for anyone signed into Gmail. No OAuth, no API, no secrets.
- **Limits:** no attachments, and long bodies can be truncated by URL limits.
  Keep bodies under ~1,500 characters and always offer "Copy the letter"
  alongside, plus a `mailto:` fallback for non-Gmail users.
- Attachments are handled by instruction, not automation: the review screen
  lists "Attach: death certificate (PDF)" as a checklist item.

### B. Gmail API draft (P1 — the impressive version)
- OAuth 2.0 with scope **`gmail.compose`** only. Create a *draft* via
  `users.drafts.create` with a base64url-encoded RFC 2822 message; attachments
  ride along as multipart. Then deep-link the family straight to that draft.
- Do **not** request `gmail.send`. Drafts keep the human in the loop and keep
  the consent story clean — say this out loud in the pitch.
- In the Google Cloud console, keep the app in testing mode and add your
  teammates as test users; sensitive-scope verification is not achievable this
  week and is not needed for a demo.
- Tokens are stored on the Nano only, in a file outside the repo, and the UI
  offers "Disconnect Gmail" which deletes them.

### C. Sending directly from the backend — **out of scope.** Don't build it.

### Review screen (required before either path)
A dialog listing: recipient + provenance badge, subject, full body, the
attachment checklist, and a short "What you're sharing" summary — e.g.
*"Arun's full name, date of death, policy ending 4471. Not shared: full policy
number, bank details, your address."* Two buttons: **Open in Gmail** and
**Not yet**. On proceed, write a consent log row.

---

## 6. After sending

- "Mark as sent" flips the task to the existing **Waiting for a reply** state,
  with a gentle follow-up reminder date (default +14 days) shown as a *user
  reminder*, never as a statutory deadline — the README already makes that
  distinction, keep it.
- **Reply tracking (P2):** with `gmail.readonly`, poll the thread id created in
  path B and flip the task to "They replied" with a link. Skip this unless
  everything else is done; the demo can show a manual "They replied" control.
- All outreach appears in a new **Outreach** section of the privacy page:
  who was contacted, when, what fields were disclosed, and by whose consent.

---

## 7. Demo data and safety

- Use only the fictional providers in the Arun Rao archive
  (Pacific Crest Life, Keep-It Storage, Bay Credit Union, …).
- Point their contact addresses at mailboxes **you control** — Gmail
  plus-addressing works well: `team102+pacificcrest@gmail.com`,
  `team102+keepit@gmail.com`. Then the demo can genuinely send and genuinely
  receive a reply, which is far more convincing than a mock.
- **Never send test mail to a real insurer, bank or utility.** Add a guard: if a
  recipient domain is not in the fictional set or the user-verified list, show a
  confirmation warning before the handoff.

---

## 8. Build order and estimates

| # | Task | Pri | Est. | Notes |
|---|---|---|---|---|
| O1 | `Provider` / `Channel` / `Outreach` / `ConsentLog` schemas + tables | P0 | 45m | |
| O2 | Contact mining from email headers + footers during ingest | P0 | 1.5h | biggest accuracy win |
| O3 | `data/providers_directory.json` for every fictional provider | P0 | 30m | |
| O4 | `POST /providers/resolve` — tiered ranking + provenance + confidence | P0 | 1h | |
| O5 | Templates + `POST /outreach/draft` (local LLM fills slots only) | P0 | 1.5h | |
| O6 | Review screen in the Letters view (recipient, provenance, disclosure) | P0 | 1.5h | |
| O7 | Gmail compose URL + `mailto:` + copy fallback + placeholder guard | P0 | 45m | |
| O8 | Mark-as-sent → "Waiting for a reply" + consent log | P0 | 45m | |
| O9 | Contact extraction from scanned letterheads via the vision model | P1 | 1h | |
| O10 | Escalated lookup path wired through `router.py` + approval prompt | P1 | 1.5h | strong pitch material |
| O11 | Gmail API draft with attachment (OAuth, `gmail.compose`) | P1 | 2.5h | |
| O12 | Outreach section on the privacy page | P1 | 45m | |
| O13 | Reply detection via `gmail.readonly` | P2 | 2h | only if ahead |

P0 total is roughly one focused day. Fits Thursday alongside the router work,
since O10 *is* router work.

---

## 9. Metrics to report (this is a scored deliverable)

- **Contact resolution rate:** share of findings for which a contact was found,
  broken down by tier — records / directory / lookup / none.
- **Contact precision:** of the addresses proposed, how many match the answer
  key. Target 100% for tier 1, since a wrong claims address is a real failure.
- **Escalation rate for lookups:** how many lookups were needed, and proof that
  every escalated query contained zero personal fields.
- **Time to first email:** seconds from opening a finding to a reviewed draft,
  measured end to end on the Nano. Compare against the manual baseline of
  hunting for a bereavement address on a company website.
- **Disclosure minimization:** average number of personal fields per email, and
  the count of blocked fields (SSN, full account numbers) that never appear.

Add these to `docs/METRICS.md` with a line each on why they were chosen.

---

## 10. Pitch lines this unlocks

- "Every other tool gives a grieving family a to-do list. We give them the email,
  addressed to the right department, with the right policy number, and they press
  Send."
- "The letter is written on the Nano and never leaves it until Priya decides it
  should. The only thing we ever ask the internet is a company's public
  bereavement address — and we log every time we do."
- "We create drafts, not sends. A machine should not speak for a family."

---

## 11. Risks

| Risk | Mitigation |
|---|---|
| Model invents a plausible support address | Hard rule: an address must match a verbatim source string, a shipped directory entry, or a cited lookup. Enforce in code, not in the prompt. |
| Long letters truncated in the compose URL | Length check + "Copy letter" fallback + the Gmail API draft path. |
| OAuth consent screen blocks the demo | Testing mode + teammates as test users; rehearse the flow the day before. |
| Accidentally emailing a real company | Domain allowlist guard + confirmation dialog. |
| Feature creep eats the core pipeline | O1–O8 only until the ingest pipeline and evaluation are green. |
| Legal impression of giving advice | Keep the README's existing disclaimer tone: these are information requests, not legal notices, and provider reply dates are reminders, not statutory deadlines. |

---

## 12. Claude Code prompts

**Prompt A — schemas + mining**
> Read CLAUDE.md, PLAN.md and this file. Add `Provider`, `Channel`, `Outreach`
> and `ConsentLog` Pydantic models and SQLite tables. Then add contact mining to
> the ingest pipeline: from every parsed email, extract `From`/`Reply-To` and any
> email addresses and phone numbers found in the last 15 lines of the body;
> blacklist noreply-style addresses; prefer role addresses matching
> `claims|bereavement|estates|support|service`. Store each as a Provider channel
> with evidence (doc_id, verbatim quote, char offsets). Write
> `data/providers_directory.json` covering every fictional provider in the
> Arun Rao archive, with contacts pointing at `team102+<provider>@gmail.com`.

**Prompt B — resolution endpoint**
> Implement `POST /providers/resolve` taking a finding_id and returning ranked
> candidate recipients with `source_kind`, evidence and confidence, ordered
> records > directory > lookup. Include a `needs_lookup` flag when nothing is
> found locally. Add unit tests including a case where only a noreply address
> exists (must not be proposed) and one where no contact exists at all.

**Prompt C — drafting**
> Add `backend/templates/` with the five templates in §4 of this file and
> `POST /outreach/draft`, which fills slots from the finding using the local LLM
> on :8000. The model may only adapt tone and fill declared slots; it must not
> introduce any fact not present in the finding. Leave `[PLACEHOLDERS]` for
> anything the family must supply. Return subject, body, the attachment
> checklist and a `disclosed_fields` list.

**Prompt D — UI + Gmail handoff**
> In the existing Letters view in `dist/pages.js`, add a recipient block showing
> the chosen contact with a provenance badge and a "use a different address"
> control, and a send block that opens a review dialog listing recipient,
> subject, body, attachments and `disclosed_fields`. On confirm, open a Gmail
> compose URL in a new tab, `POST /outreach/{id}/sent`, flip the task to
> "Waiting for a reply", and write a ConsentLog row. Block confirmation while
> any `[PLACEHOLDER]` remains and explain why. Add a `mailto:` fallback and a
> copy-to-clipboard fallback. Warn before any recipient domain outside the
> fictional allowlist. Keep the app buildless, no new dependencies.

**Prompt E — escalated lookup (router)**
> Extend `backend/router.py` with a `provider_lookup` task type: a generic,
> redacted query containing only a company name and country. Require explicit
> user approval before escalating, assert the payload contains no personal
> fields, return the address with its source URL marked `verified_by_user:
> false`, and log the decision to the router log like any other escalation.
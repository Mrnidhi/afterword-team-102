Act as a senior engineer responsible for delivering a complete feature within an existing product.

Understand the request and the product before deciding how to implement it. Form your conclusions from the available requirements, code, documentation, and observed behavior. Do not assume a preferred architecture, technology, design style, or solution.

Consider the work from these perspectives:

1. **Product and scope**\
   Identify the problem, intended users, desired outcome, and how the feature fits the product. Separate explicit requirements from assumptions. Define observable acceptance criteria and keep the implementation within the requested scope.
2. **User experience**\
   Follow the complete user journey, including entry points, decisions, successful outcomes, mistakes, interruptions, and recovery. Make each interaction understandable and useful. Where there is an interface, follow the product’s visual language, accessibility needs, and device constraints.
3. **Architecture and engineering**\
   Inspect the existing implementation and project conventions. Trace the relevant data flow, state, dependencies, and integration boundaries. Choose an approach proportionate to the problem. Reuse suitable components and introduce new abstractions or dependencies only when justified.
4. **Data, privacy, and reliability**\
   Determine what information the feature reads, changes, stores, or shares. Apply the controls appropriate to those operations. Consider validation, permissions, persistence, failures, retries, and unintended duplicate actions where relevant.
5. **Implementation**\
   Deliver a working path through every layer the feature requires. Connect interface behavior to actual functionality. Handle relevant loading, empty, success, and error states. Preserve unrelated work and existing behavior. Clearly distinguish implemented functionality, demonstrations, and unavailable integrations.
6. **Verification**\
   Test the acceptance criteria and meaningful failure cases using checks appropriate to the change. Verify the actual user experience when applicable. Check affected existing behavior. Distinguish automated tests, simulated integrations, and real external execution; report only outcomes you observed.
7. **Delivery and maintainability**\
   Review the final changes for correctness, clarity, and unnecessary complexity. Update relevant documentation and configuration guidance. Follow existing authorization for commits, publishing, and external actions. Explain what changed, how it was verified, and any remaining limitations.

Work autonomously on clear, authorized steps. Ask focused questions when missing information materially affects correctness or scope, while continuing independent work where possible. State assumptions instead of silently inventing requirements.

Give a short plan, then implement and verify it. Keep progress updates focused on findings and decisions. Do not stop at recommendations when implementation is requested, and do not expand the task simply to appear thorough.

If completion depends on unavailable access, configuration, hardware, or another person, finish the independent work and identify the precise remaining dependency. Never describe an unverified or blocked outcome as complete.

Feature request and supporting context:\




# Afterword — integration requirements

**Goal:** while the model trains, everything else gets built against a fixed contract. When training finishes, we swap the model weights behind port 8000 and **nothing in the backend or UI changes** — only accuracy improves.

The contract works **today** against the base model. Verified live on hp24.

---

## 0. Do this first — today

**Commit and push the backend.** `backend/`, `MULTILINGUAL-PLAN.md`, `dist/i18n.js` and 7 modified UI files exist only on hp24. The node is wiped after the event, and a public repo is a required deliverable.
```bash
cd ~/afterword-team-102 && git status          # review, then commit and push yourselves
```

Don't commit `backend/afterword.db` (runtime data) — add it to `.gitignore`.

---

## 1. The contract — `afterword.finding/v1`

One call per document:
```python
import sys; sys.path.insert(0, "/home/hp24/afterword/model")
from engine import extract
result = extract(text, source="email", doc_id="mail-0042", reference_date=date_of_death)
```

- `text`: plain text of ONE document (one email, one SMS, one letter/page)
- `source`: `"email"` | `"sms"` | `"letter"`
- `reference_date`: date of death (turns "30 days" into a calendar date); optional
- Never raises on model problems — returns `status: "failed"` instead

It returns (example values show the intended behaviour; today's base model gets `act` wrong on this letter):
```json
{
  "contract": "afterword.finding/v1",
  "id": "mail-0042",
  "source": "letter",
  "status": "needs_review",
  "route": "extract",
  "finding": {
    "cat": "retirement", "inst": "Ironworkers Local 412 Pension Fund", "ref": "4370",
    "amt": 1843.2, "kind": "benefit", "rec": "monthly", "due": 30, "act": "stop_payment",
    "ev": [1, 4, 5, 6],
    "money_at_stake": 11059.2, "triage": "extract", "deadline_date": "2026-10-01"
  },
  "evidence": [{"line": 5, "text": "Monthly benefit: $1,843.20"}, "..."],
  "checks": {"schema_errors": [], "grounded": {"amt": true, "ref": true, "inst": true, "due": true}},
  "meta": {"engine": "0.1", "model": "...", "tier": "L1", "latency_ms": 6982, "output_tokens": 59, "raw": null}
}
```

### What each field means for the UI

| Field                                   | Values                                                                             | Use it for                                                                                                                        |
| --------------------------------------- | ---------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------- |
| `route`                                 | `extract` / `memory` / `drop`                                                      | `extract` → Action plan. `memory` → Memories tab. `drop` → hide (show a count: *"212 irrelevant items ignored"*)                  |
| `status`                                | `accepted` / `needs_review` / `failed`                                             | Badge. `needs_review` = the model's answer couldn't be verified against the document                                              |
| `finding.cat`                           | 14 categories (see `schema.py`)                                                    | Grouping / icons                                                                                                                  |
| `finding.act`                           | `notify` `claim` `cancel` `stop_payment` `verify_debt` `transfer` `close` `review` | The action text on each card                                                                                                      |
| `finding.amt`                           | number                                                                             | "Printed amount"                                                                                                                  |
| `finding.money_at_stake`                | number                                                                             | **"What's actually at stake"** — the headline. e.g. $12.99/month → $155.88/yr; pension → 6 months of clawback; lapsed policy → $0 |
| `finding.deadline_date`                 | ISO date or null                                                                   | Statutory clock / countdown                                                                                                       |
| `evidence[]`                            | `{line, text}`                                                                     | Highlight these lines in the Evidence view                                                                                        |
| `checks.grounded`                       | per-field true/false                                                               | Explain a `needs_review`: *"the reference number isn't on the cited lines"*                                                       |
| `meta.latency_ms`, `meta.output_tokens` | numbers                                                                            | Model panel / telemetry                                                                                                           |

**Sort order for the action plan:** stated deadlines first (soonest first), then largest `money_at_stake`. Same rule as `schema.priority()`.

`finding.ev` line numbers refer to `text.splitlines()` of the exact text you passed in, starting at 1. **Store that exact text** so the evidence view lines up.

---

## 2. What the backend needs ready

| #  | Task                                                                | Notes                                                                                                                                                                                     |
| -- | ------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| B1 | `POST /extract` `{id, source, text, reference_date?}` → contract v1 | Thin wrapper over `engine.extract`                                                                                                                                                        |
| B2 | `POST /extract/batch` → list of results                             | Sequential; the model server is one-at-a-time (\~6 s/doc)                                                                                                                                 |
| B3 | Store results in SQLite                                             | `findings(id, source, status, route, finding_json, evidence_json, checks_json, meta_json, text, created_at)`                                                                              |
| B4 | **Email ingestion**                                                 | `.mbox` / `.eml` → one item per message. Stdlib `mailbox` + `email`. Text = Subject + From + Date + body                                                                                  |
| B5 | **SMS ingestion**                                                   | One item per message. Support a CSV (`date,sender,body`); Android "SMS Backup & Restore" XML if time                                                                                      |
| B6 | **Letter / PDF ingestion**                                          | Text PDFs: `pdfplumber` or `pypdf` (**not PyMuPDF — AGPL**). Scans/images: RapidOCR — reuse `group_lines()` from `~/afterword/model/prep_public.py`. OCR runs on the Arm CPU, not the GPU |
| B7 | `/health` includes `model` and `contract` version                   | So the UI can show which model is live                                                                                                                                                    |
| B8 | No cloud calls anywhere                                             | We demo with the network cable unplugged                                                                                                                                                  |

## 3. What the frontend needs ready

| #  | Task                                                                                                                                                                                                      |
| -- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| F1 | Load findings from the backend instead of the fictional Arun Rao fixtures (keep fixtures as a fallback)                                                                                                   |
| F2 | Action plan from `route == "extract"`, sorted as above                                                                                                                                                    |
| F3 | Evidence view highlights `evidence[].line` in the stored source text                                                                                                                                      |
| F4 | Memories tab from `route == "memory"`                                                                                                                                                                     |
| F5 | Status badge: accepted / needs review (reason from `checks`) / failed                                                                                                                                     |
| F6 | Show `amt` → `money_at_stake` side by side — this is the "judgement" moment in the demo                                                                                                                   |
| F7 | Placeholder panels for numbers the model layer delivers later: **Escalation Ledger** (items per tier, entities that left the device = 0, cloud-equivalent cost) and **model panel** (tokens/doc, latency) |
| F8 | **Offline:** Google Fonts won't load with the cable unplugged — bundle the font files or accept the system-font fallback                                                                                  |

## 4. What the model layer delivers, and when

| When                   | Delivery                                                                     | What changes for you                                                                                 |
| ---------------------- | ---------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------- |
| **Now**                | `engine.py` + contract v1, working on the base model                         | Start building                                                                                       |
| After Step 3 (tonight) | A demo estate: one fictional decedent, \~50 documents, with contract outputs | Load it into the UI                                                                                  |
| After Step 6 (SFT)     | Fine-tuned 4B                                                                | We restart `model_server.py chat --port 8000 --model <path>` — \~1 min downtime, **no code changes** |
| After Step 8           | Calibrated confidence gate                                                   | `status` becomes statistically calibrated. Same field                                                |
| After Step 9           | Final metrics + architecture diagram                                         | For the deck                                                                                         |

## 5. Shared-box rules

- Run `python ~/afterword/model/status.py` before starting anything on the GPU
- Ports in use: **8000** chat model, **8003** embeddings, **8080** UI server, **8090** 32B teacher
- Only \~8 GB of memory is free while the 32B teacher runs — don't load another model until it's stopped
- Never `kill -9` a run; never `pkill` ZRT — use `zrt service stop <label>`
- **Tell Prakhar before restarting the model server on port 8000** — the swap to the fine-tuned model happens there

## 6. For the deck owner — numbers the model layer will provide

Baseline vs fine-tuned field F1 and critical recall · grounding rate · tokens per document · latency · triage savings (items never sent to the LLM) · conformal coverage · cloud-equivalent cost · OCR throughput on the Arm cores (5.5 pages/s, GPU untouched) · text-only ceilings (invoices 77.4%, CORD 92.5%) · the Mamba finding (275 vs 20 tok/s) · architecture diagram.
# Outreach evaluation

These measurements evaluate provider outreach, not estate correctness or legal
advice. Report the dataset version, commit, mode, machine, sample count and date
with every result. Confidence values used to rank contacts are heuristics, not
calibrated probabilities.

## Required metrics

| Metric | Definition | Why it matters |
|---|---|---|
| Contact resolution rate | Findings with a proposed channel / all evaluated findings; report records, directory, lookup and none separately | Shows where the family receives a useful next step and where information is missing |
| Deliverable contact rate | Findings with a non-reserved email that passes handoff verification / all evaluated findings | Separates finding a fictional evidence address from being able to reach a real controlled inbox |
| Contact precision | Correct proposed email addresses / all proposed email addresses, against an independent answer key, by tier | A plausible but incorrect recipient can disclose information to the wrong party; tier 1 target is 100% on the specified set |
| Lookup escalation rate | Actual approved external provider lookups / resolution requests | Measures when local records and the directory were insufficient |
| Lookup disclosure violations | External lookup payloads containing fields beyond canonical company and country, or a value from personal source fields | Every escalation must disclose zero family fields; test denied requests and tampered company identifiers too |
| Time to reviewed draft | Monotonic elapsed time from opening a finding to a fully populated disclosure review, excluding no steps | Measures the complete family workflow rather than model inference alone |
| Manual comparison | Same scenario completed by a person locating contact information and drafting the request; record participant, trials and elapsed times | Makes any time-saving claim reproducible instead of assuming a manual duration |
| Disclosure minimization | Mean distinct personal-field categories in the exact reviewed recipient/subject/body/attachment manifest; additionally record attempted and blocked SSN/full-account/DOB disclosures | Shows what actually leaves through a handoff and whether sensitive values were stopped |

Report the number of cases as well as the percentage. A small synthetic fixture
score does not estimate accuracy on real archives. Keep archived contact discovery,
recipient control verification and successful email delivery as separate outcomes.

## Evidence levels

1. Unit and API tests: deterministic fixtures and injected external transports.
2. Browser integration: actual local service/static site and browser interaction;
   external Gmail navigation may be intercepted so tests do not disclose or send.
3. Live integrations: controlled Google test account, approved lookup provider and
   actual Nano endpoints, with observed logs and timestamps.
4. Nano user study: complete end-to-end scenario and matched human baseline on the
   target device. Laptop timing cannot be reported as HP/Nano timing.

## Current verification record

Executed September 24, 2026 using the version-1 fictional archive and a temporary
CPU-only evaluation workspace. The model transport is disabled in this evaluation.
The approved inbox is supplied locally; its address is omitted from the report.
See `outreach-fixture-results.json` for the machine-readable result and
`OUTREACH-VERIFICATION.md` for the release checks.

| Measurement | Observed result | Limit |
|---|---|---|
| Resolution before inbox configuration | 2/7 findings: records 2, directory 0, lookup 0, none 5 | Both source addresses use reserved fictional domains and cannot receive mail |
| Resolution after inbox configuration | 5/7 findings: records 2, directory 3, lookup 0, none 2 | Unresolved findings have no known provider; directory contacts route to the approved demo inbox |
| Available non-reserved recipient | 5/7 findings | Address validation and user authorization do not establish delivery |
| Tier-1 fixture precision | 2/2 proposed record addresses match the independent answer key | Tiny synthetic set; not a real-world accuracy estimate |
| External lookup attempts | 0 in this fixture evaluation | Payload minimization is exercised separately by injected-transport tests; no live search claim |
| Template disclosure categories | Mean 6 across five template reviews | Name of deceased, writer name, phone, stated relationship, date of death and masked reference; recipient address is also reviewed separately |
| Blocked disclosure probes | All 3 probes blocked: SSN, full account number and date of birth | Additional adversarial tests cover Unicode, filenames and contact-line exemptions; arbitrary prose and file contents still require human review |
| Template length | 92–97 words, 530–572 characters across five samples | Actual edited letters are checked at handoff; long letters require copy or API draft |
| Nano workflow time / manual baseline | Not measured | Requires target hardware and a human baseline; laptop or mocked timings are not substitutes |

No live Nano timing, manual baseline, mailbox delivery, Google OAuth success or
cloud lookup outcome has been measured for this feature. The full acceptance
gate remains open until those requested live checks are performed.

Reproduce the base fixture report with `python scripts/evaluate_outreach.py`.
For the configured-directory case, provide an authorized address through the
`AFTERWORD_EVALUATION_MAILBOX` environment variable. The script never sends mail,
invokes a model or prints the supplied address; its temporary database is removed
after evaluation. Do not put that address into source or CI settings.

## Reproduction and final report

The scan workflow has a separate actual-engine record in
`outreach-ocr-verification.json`. One fictional page was read with local
Tesseract 5.5.3 on macOS; its email contained a character error and needed human
correction. No scan precision percentage or vision success is inferred from that
single OCR run. The original bytes, raw transcription and correction are kept
separate. The scan results do not change the seven-finding resolver denominators.

`scripts/outreach_rehearsal.py` captures new redacted service events and actual
operator-measured baseline durations outside Git. It never substitutes an assumed
baseline or a model-list request for end-to-end Nano timing. Follow
`OUTREACH-LIVE-REHEARSAL.md` and preserve independent runtime/mailbox evidence.

The final verification report must list commands, pass/fail counts, browser
viewport sizes, relevant negative cases and unverified external dependencies.
The benchmark must store source IDs and expected recipients separately from model
or resolver outputs; evaluating output against itself is not an answer key.

For external integrations, record only a redacted summary in the public repository.
Keep Google tokens, family documents and full email content outside version control.

# Live provider-outreach rehearsal

This is the remaining acceptance procedure. Fixture tests and browser mocks are
kept separate from this report. Nothing in these scripts authorizes Google,
searches the web, generates a letter, submits files to a model or sends email.
The family/operator performs the corresponding reviewed UI actions.

## Readiness without secret access

Run on the machine that will host Afterword, using the same environment as the
server:

```sh
.venv/bin/python scripts/outreach_readiness.py
```

This prints configuration booleans, credential-file metadata and next actions.
It never opens tokens, prints client secrets, resolves a lookup host or probes a
model. `GET /integrations/readiness` provides the same inspection inside the
running service and adds registered scan/runtime status. A present token file is
not reported as a successfully connected account.

Only when deliberately checking a configured **local** model service, run:

```sh
.venv/bin/python scripts/outreach_readiness.py --probe-local-models
```

That flag performs only loopback `GET /models` calls with a three-second timeout,
no proxies or redirects. It reports reachability, count and whether the configured
model is listed; it does not run inference or establish model accuracy. No model
names or response content are printed. Other public/cloud URLs are rejected.

Current configuration inspection on the development machine found no model,
vision, search or Gmail OAuth environment settings and no default token file.
Tesseract and image validation were available. This is a configuration observation,
not a successful HP inference, OAuth or mailbox rehearsal. Re-run on the target
device; these conditions can change.

## Prepare a controlled run

1. Run the local backend on the HP with the approved models and local OCR engine.
   Confirm configuration using the commands above. Keep OAuth secrets and tokens
   outside the repository. Add only participating test users to the Google OAuth
   testing application.
2. Use fictional source documents and a real mailbox that your team controls and
   explicitly approves. Do not send any test message to a real provider. Verify
   the mailbox in Afterword Settings. The known fictional `.example` contacts
   remain deliberately undeliverable until a controlled recipient is selected.
3. Save independent hardware evidence locally, such as the device inventory
   shown by the operator. Record the exact Git revision. An ARM architecture alone
   is not evidence that the device is an HP ZGX Nano.
4. Choose a new output path outside the public repository, then begin capture:

```sh
.venv/bin/python scripts/outreach_rehearsal.py begin \
  --report "$HOME/afterword-rehearsals/run-1.json" \
  --api-url http://127.0.0.1:4173 \
  --environment hp-zgx-nano \
  --operator participant-1 \
  --revision "$(git rev-parse HEAD)"
```

Use `other-local-device` for laptop checks. Device labels remain operator claims
until the hardware artifact is independently reviewed. The helper only GETs safe
configuration and redacted audit endpoints on the local service. Reports are
created with owner-only permissions. Existing captures are not overwritten.

## Perform and record the actual workflow

| Check | Action and required evidence |
| --- | --- |
| `hardware_identity` | Capture device identity and running model/runtime configuration without credentials. |
| `local_model` | Open a finding and prepare the letter. Confirm generation is `local_model_guarded`, not template fallback; review all slots against source facts. |
| `scan_ocr` | Add the fictional scan through Documents. Compare the image and OCR, correct errors, and approve the current image/OCR hashes. Retain evidence showing the reviewed version. |
| `vision_contacts` | Run the actual local vision extraction. Check that every contact exactly matches the reviewed OCR and source image. Retain the source and result for independent scoring. |
| `lookup_approval` | Inspect the precise company/country preview. Cancel once and verify no escalation; then explicitly approve one lookup. Inspect the actual logged minimized payload and unverified source URL. |
| `gmail_oauth` | Approve draft connection with a Google test account. Inspect Google's actual scope screen: `gmail.compose` includes sending capability even though Afterword exposes no send operation. |
| `gmail_draft` | Review the recipient and complete letter. Create the draft, inspect it in the correct Google account and verify that it remains unsent. |
| `attachments` | Upload a fictional file locally, download/review its contents, approve the final manifest, and compare the file visible in the actual Gmail draft. Edit/remove a file before approval and verify stale consent is rejected. |
| `human_send` | Only the operator presses Send in Gmail to the controlled mailbox. Then use Afterword's separate Mark as sent action. Retain the Gmail sent-message evidence. |
| `gmail_reply` | Explicitly approve read-only tracking separately. A teammate replies manually from the controlled mailbox. Check the correlation result, actual Gmail reply and Afterword state. Own sent messages must not count as replies. |
| `disconnect` | Disconnect, confirm local tokens are removed and record whether remote revocation succeeded. An offline failure must remain visibly unconfirmed. |

After each actual observation, record its result and a local evidence artifact:

```sh
.venv/bin/python scripts/outreach_rehearsal.py record \
  --report "$HOME/afterword-rehearsals/run-1.json" \
  --check gmail_draft --outcome observed_pass \
  --evidence "$HOME/afterword-rehearsals/gmail-draft-observation.png"
```

Replace the check and path with what you actually observed. Use `observed_fail`
or `blocked` when applicable. Passing observations require an artifact. Only its
hash and byte count are retained; screenshot/log contents are not copied or
uploaded. Preserve the artifacts privately so the hashes can later be verified.
Do not create mock evidence and record it as a live pass.

## Measure end-to-end time and compare a human baseline

Begin capture before opening the finding. Afterword records the elapsed interval
from its finding-session event to a complete review. Repeat the same scenario
several times and report every measured trial, not only the fastest one. These
timestamps measure the configured local service; they become HP results only when
the device identity and runtime are independently established.

Have a participant separately perform the matching manual task: locate the right
contact and prepare the same information request. Use a stopwatch, retain the
observation and record the actual value using `manual-baseline --seconds`:

```sh
.venv/bin/python scripts/outreach_rehearsal.py manual-baseline \
  --report "$HOME/afterword-rehearsals/run-1.json" \
  --seconds "$AFTERWORD_MEASURED_SECONDS" \
  --evidence "$HOME/afterword-rehearsals/manual-stopwatch.png"
```

Set `AFTERWORD_MEASURED_SECONDS` to the measured duration. There is no default,
estimated baseline or automatically invented speedup. Match the scenario,
completion criteria and participant conditions before comparing medians.

Finally collect only the audit events added during this run:

```sh
.venv/bin/python scripts/outreach_rehearsal.py finish \
  --report "$HOME/afterword-rehearsals/run-1.json"
```

The report preserves initial/final readiness, redacted event hashes, observed
workflow times, manual durations and remaining gates. It distinguishes automatic
service observations from operator assertions. Finalizing capture does not mark
acceptance complete. A reviewer must reconcile actual Google/runtime artifacts,
the independent contact answer key and hardware identity. Public summaries may
include aggregate results, but never OAuth data, full mailbox content or private
documents.

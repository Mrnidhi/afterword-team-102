# Deploying Afterword with the fine-tuned model (engine 0.3)

Everything here runs on the HP ZGX Nano (`hp24`, 100.79.40.125). Nothing is sent off the box.

## 0. What changed and why

| Where | Change |
| --- | --- |
| `model/engine.py` | 0.2: removes values the document does not contain (and says so in `checks.removed_ungrounded`), per-field confidence gate from token probabilities (thresholds fitted on the reserved calibration set), tags + priority |
| `model/schema.py` | `assess()` / `rank()`: 14 tags, 0-100 `priority_score`, P1/P2/P3, `priority_reasons`, printed-date reading, same-account merging |
| `backend/extraction_engine.py` | Extraction may use loopback port **8091** via `AFTERWORD_EXTRACT_URL`. Every other model use stays on 8000 only |
| `dist/findings-core.js`, `findings.js`, `findings.css` | Action plan sorts by `priority_score` (older results keep the old rule); cards show the P-band and tags; evidence view shows "Why it is ranked here" |
| `model/engine.py` 0.3 | `finding.contacts`: web links, emails and phone numbers read from the document by code |
| `dist/chat.js`, `dist/chat.css` | The Overview chat: paste text or screenshots, drop files; ranked cards; category rollup (same account counted once) |
| `deploy/afterword.sh`, `deploy/push_hp24.sh` | One-command deploy to the HP box; start/stop/status/check/logs on the box |
| `.github/workflows/pages.yml` | Restored deploy-only publishing of `dist/` on push to `main` |
| `vercel.json` | Static Vercel deployment of `dist/` with security headers |
| tests | hash pins updated for the two model files; new tests for the port boundary, tags/rank, malformed values, contacts, chat helpers |

**Why port 8091 and not 8000:** the model on 8000 is shared by letter drafting (`backend/drafting.py`),
drain buckets (`backend/buckets.py`) and translation (`backend/app.py`). The fine-tuned model only ever
returns extraction JSON, so putting it on 8000 would break all three. It runs beside the general model.

Contract stays `afterword.finding/v1`; every new field is additive.

## 1. Deploy the whole app to the HP box (one command)

From any laptop with SSH access, in this checkout:

```bash
bash deploy/push_hp24.sh
```

It copies the source (no `.git`, virtualenvs or databases) to `hp24:~/afterword-app`, installs
`requirements.txt` into `.venv` when it changed, starts the model if it is not already serving,
restarts the app and prints its health. On the box itself:

```bash
cd ~/afterword-app
bash deploy/afterword.sh status     # app :4190 + model :8091, engine, sent_to_cloud
bash deploy/afterword.sh check      # one fictional letter through the whole pipeline
bash deploy/afterword.sh logs       # follow the app log
bash deploy/afterword.sh stop       # stops the app only; the model keeps serving
```

Runtime databases and logs live in `~/afterword-app/.runtime/` (git-ignored). The app and the
model listen on **loopback only**; neither is reachable from the network.

## 2. Open it

On a laptop: `ssh -N -L 4190:127.0.0.1:4190 hp24@100.79.40.125`, then open
**http://127.0.0.1:4190**. (Or open the same address in a browser on the box.)

The Overview opens with the chat: paste text, paste a screenshot, or drop PDFs, `.eml` and photos
of letters. Files are parsed and OCR'd on the box's Arm CPU, read by the fine-tuned model on its
GPU, and returned as ranked cards. The Plan, Documents and Evidence views update from the same data.

## 3. The model

`sft3` is served by vLLM on `:8091` with `HF_HUB_OFFLINE=1 VLLM_NO_USAGE_STATS=1 DO_NOT_TRACK=1`
(`~/afterword/model/serve_model.sh`). `deploy/afterword.sh start` starts it when needed.
If the box was wiped, rebuild it from the backup (Mac `afterword/model/out/sft3_adapter`, or the
private Hugging Face repo `prakharsinghAI/afterword-sft3`):

```bash
cd ~/afterword/model && python merge_adapter.py out/sft3_adapter out/sft3_merged
```

The shared general model on `:8000` (drafting, drain buckets, translation) is teammate-owned and
untouched. Before claiming "nothing leaves the box", restart it with
`HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1` (coordinate with its owner).

## 4. Public website (Vercel, or GitHub Pages)

The public site is the **static** `dist/` folder: the landing page and the fictional sample
workspace. It has no model - the fine-tuned model needs the box's GPU, and the app is
loopback-only by design. `dist/runtime-config.js` reports `extraction:false`, so the chat stays
hidden there. **The live AI demo is the HP box (sections 1-2).**

**Vercel** (`vercel.json` at the repo root: no install, no build, publish `dist/`, security headers):

1. vercel.com -> Add New -> Project -> import `Mrnidhi/afterword-team-102`.
2. Framework preset: *Other*. Root directory: repository root. Leave build settings to `vercel.json`.
3. Production branch: `main`. Every other branch (e.g. `prod/model-integration`) gets its own
   preview URL on each push - use that to review before merging.
4. No environment variables or secrets are needed.

CLI alternative, from this checkout: `npx vercel` (preview) then `npx vercel --prod`.

**GitHub Pages** still works too: `.github/workflows/pages.yml` publishes `dist/` on a push to
`main`. Using both is fine; pick one URL for the slides.

## 5. Tests

```bash
.venv/bin/python -m pytest tests backend/tests -q        # 333 on the Mac; 331 + 2 skipped on hp24 (no tesseract)
for t in tests/*.test.cjs; do node "$t"; done            # Node is not installed on hp24; run these on a laptop
node scripts/version-assets.cjs --check
```

## 6. Numbers for the slides (every one is in `~/afterword/model/results/`)

| Claim | Value | File |
| --- | --- | --- |
| Fine-tuned 4B vs 32B, fresh held-out set (405 docs) | field F1 0.984 vs 0.786 | `overnight_summary.md` |
| Same, strict scoring | 0.982 vs 0.780 | `rescore.json` |
| Critical recall (amount / reference / deadline) | 0.989 vs 0.983 | `overnight_summary.md` |
| Speed and energy per document | 25 s vs 218 s for 405 docs; 3.8 J vs 33.7 J | `energy.jsonl`, `sft3_hard2.json` |
| Output tokens per document | 42.0 vs 62.7 | `sft3_hard2.json`, `base32b_hard2.json` |
| Batching 64 vs 1 request | 1.6 J vs 48 J per document | `energy.jsonl` (bench_sft2_c*) |
| L0 triage (CPU) | 18% of docs skip the LLM, 16.5% fewer LLM tokens, 0 money docs dropped | `l0_triage.json` |
| Prefix cache | 192 of 416 prompt tokens per doc shared (46%) | measured, see `demo.py` ledger |
| Gate | accepted fields 0.8% wrong; flags 12% of unfamiliar docs; 32B disagreement = 64% real errors | `cascade_verify.json` |
| Training | 3,658 docs, 105 min, 268 kJ GPU | `energy.jsonl`, `runs_archive/sft3` |
| Rejected ideas (say so) | line selection (-2.3 F1 for 6.7% tokens); 32B overwriting (fixed 5, broke 7) | `l0_lines.json`, `cascade_replace.json` |

**Caveats to state:** all test sets are synthetic; the hard v1 gains are optimistic (v3 data was
designed after seeing its errors) - hard v2 is the unbiased number; energy is GPU power only.

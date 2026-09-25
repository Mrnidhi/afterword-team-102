# Handoff: multilingual summaries and letters

Written for whoever (human or Claude Code session) picks this up next, with no prior context on this conversation. Read this first, then [MULTILINGUAL-PLAN.md](MULTILINGUAL-PLAN.md) for the full phase-by-phase design and status detail — this file is orientation and resumption instructions, not a repeat of it.

**Repo:** `/home/hp24/afterword-team-102` (Afterword, Team 102's HP ZGX demo). **Machine:** this is the Nano itself (GB10 GPU), not a dev laptop.

## What's done

Phases 0–7 of [MULTILINGUAL-PLAN.md](MULTILINGUAL-PLAN.md) are complete — everything P0, the P1 prewarm/metrics phase, and the P2 stretch label table. (Phase 7's other stretch item, voice memo transcripts, is correctly *not* built — there's no actual audio anywhere in this demo, only text framed as a transcript, and the plan's own condition for building it was "if audio is in the demo.") On top of that, a **gap resolution pass** (see the plan's own section by that name, right after phase 7) went back through the "Known gaps" list this file used to carry and closed most of what was actually closeable — read that section for the full detail; this file's gap list below has been updated to match. Each phase's section in the plan has a "**Status: done**" block with what was built, how it was verified, and every bug found along the way — read those before changing anything, they contain hard-won detail.

In one line: a language toggle translates finding summaries, task instructions and letters into Spanish, Vietnamese or Hindi, on-device, with protected tokens (amounts/dates/names) guaranteed never to be altered, a round-trip confidence check, and a bilingual letter view where English is always what actually gets sent. A small static label table also translates the 9 nav headings and the 3 letter-page action buttons, independent of the backend being reachable.

## Is the environment already running?

This session left four processes running. Check before starting anything new:

```sh
ss -ltnp 2>/dev/null | grep -E ":(8000|8003|8010|8080)\b"
```

If all four ports show up, skip to "Verify it still works" below. If a machine/session restart killed them, bring them back in this order:

```sh
# 1. Chat model stand-in (Qwen3-4B-Instruct-2507) — swap for whatever the real Nano serves
cd /home/hp24/afterword-team-102/backend
/home/hp24/miniforge3/envs/zgx/bin/python dev/model_server.py chat --port 8000 &

# 2. Embedding model stand-in (BAAI/bge-small-en-v1.5)
/home/hp24/miniforge3/envs/zgx/bin/python dev/model_server.py embed --port 8003 &

# 3. The actual translation backend (needs the zgx conda env: fastapi/uvicorn/httpx)
/home/hp24/miniforge3/envs/zgx/bin/python -m uvicorn app:app --port 8010 &

# 4. The frontend, static
cd /home/hp24/afterword-team-102/dist
python3 -m http.server 8080 --bind 127.0.0.1 &
```

Open `http://127.0.0.1:8080/` in a browser. Wait for `curl -s localhost:8010/health` to report `prewarm: "39/39"` before demoing — a genuinely cold cache (nothing translated yet) takes a few minutes (Hindi is slow, ~20s+ round-trip per item, all serialized through one model lock); a warm cache (the normal case) reports 39/39 in under a few seconds. (This count grew from the original 30 during the gap resolution pass — the 3 letter subjects are now prewarmed too, since `dist/i18n.js` translates them for the "For you to read" column.)

**There are now two ways to run the demo, since the gap resolution pass:**
- **The dev setup above** (dist/ on :8080, backend on :8010, cross-origin, CORS-dependent) — what every phase in this plan was actually verified against.
- **Same-origin, the way a real demo should run it:** `backend/app.py` now also serves `dist/` itself. Skip step 4 above, and open `http://<device>:8010/` instead of `:8080` — no CORS, and `dist/i18n.js`'s dev-port URL guess (described below) is never exercised because it doesn't need to be.

**Important, if using the dev setup on :8080:** `dist/i18n.js` guesses the backend's URL from `location.port` (`:8080` → `http://127.0.0.1:8010`, otherwise same-origin) purely as a local-dev convenience. Before any real demo, use the same-origin path above (or set `window.AFTERWORD_API` explicitly) so nothing depends on that guess.

## Real model vs. the stand-in used so far

Nothing was listening on :8000/:8003 when this work started, so `backend/dev/model_server.py` — a small FastAPI stand-in speaking the same OpenAI-style API vLLM would — was used throughout, serving `Qwen/Qwen3-4B-Instruct-2507` (chosen over the also-present `nvidia/NVIDIA-Nemotron-3-Nano-4B-BF16` for noticeably better Hindi/Vietnamese) and `BAAI/bge-small-en-v1.5`. **If the real Nano serves a different model, re-run `backend/dev/phase0_spike.py` before trusting any of the numbers below** — phase 0 already found real, model-specific weaknesses (see "Known gaps" below), and a different model could have different ones. The harness makes this a one-line rerun.

## Verify it still works

```sh
cd /home/hp24/afterword-team-102
/home/hp24/miniforge3/envs/zgx/bin/python -m unittest discover -s backend/tests   # 44 tests, offline (fakes the model calls)
```

**`node` is now available**, installed during the gap resolution pass into its own conda env (no `sudo`, no system-wide change): `conda create -n node-tools -c conda-forge nodejs`. Run the repo's own frontend tests for real, not via the old browser-based substitute:

```sh
/home/hp24/miniforge3/envs/node-tools/bin/node tests/state.test.cjs
/home/hp24/miniforge3/envs/node-tools/bin/node scripts/version-assets.cjs --check
```

(`backend/dev/store-test-harness.html` still exists from phase 3, from before `node` was available here — it's no longer the primary way to check `store.js`, but it's harmless to keep.)

For a live check against the real backend:
```sh
curl -s localhost:8010/health
curl -s localhost:8010/translate -H 'content-type: application/json' \
  -d '{"text":"Ask for an updated itemized balance.","target_lang":"hi","kind":"instruction"}'
```

## File map

| Path | What it is |
|---|---|
| `MULTILINGUAL-PLAN.md` | The full plan, phase by phase, with a status block per phase |
| `backend/translate.py` | Protected-token extraction/restoration (phase 1) |
| `backend/app.py` | `POST /translate`, `GET /languages`, `GET /health`, SQLite cache, prewarm (phases 2, 6) |
| `backend/demo_content.py` | Extracts the demo archive's text straight from `dist/pages.js` — the single source of truth for what gets translated, used by the prewarm, `metrics.py` and the phase 0 spike |
| `backend/metrics.py` | Produces `backend/metrics.json` (phase 6) |
| `backend/metrics.json` | Real numbers from the last run — round-trip scores, latency, token preservation, coverage |
| `backend/afterword.db` | The live SQLite translation cache. Has a `negation_flip` column now (auto-migrates an older file); `PROMPT_VERSION` is `3`, so rows from before the gap resolution pass are superseded, not deleted |
| `backend/dev/model_server.py` | The stand-in model server (see above) |
| `backend/dev/phase0_spike.py` → `backend/dev/phase0_results.json` | Phase 0's measurements |
| `backend/dev/store-test-harness.html`, `backend/dev/glyph-test.html` | Browser-based test pages, used because `node` isn't available |
| `backend/dev/gen_labels.py` → `backend/dev/labels_raw.json` | Phase 7's raw (pre-review) label translations — the reviewed, corrected versions actually used live in `UI_LABELS` in `dist/i18n.js` |
| `dist/i18n.js` | All frontend translation logic: language preference, fonts, the translated-block component, letter staleness/checkbox/Gmail handoff (phases 3–5), the static `UI_LABELS` nav/button table (phase 7), `translatedInline` for the letter subject (gap resolution pass) |
| `dist/pages.js`, `dist/workspace.js`, `dist/store.js` | Existing app files, edited in place — see each phase's diff notes in the plan for exactly what changed and why |
| `dist/workspace.css` | New CSS for translated blocks, the bilingual letter layout, and print rules |

## Known gaps and simplifications (the honest list)

Pulled together from every phase's status block, updated after the gap resolution pass — read the plan's "Gap resolution pass" section (right after phase 7) for the full detail on anything marked resolved below, and the relevant phase section for anything still open.

**Resolved in the gap resolution pass:**

1. ~~Only the letter body is translated, not the subject~~ — **fixed.** The subject now translates too, as its own small independent request (never combined with the body, so there was no re-splitting to make fragile).
2. ~~Round-trip cosine doesn't catch a negation~~ — **mitigated.** A narrow negation-word guard now catches the exact case phase 0 found ("was applied" → "was not applied"). Not a general fact-checker, but the specific named gap is closed.
4. ~~Two specific Hindi weaknesses ("policy", "provider")~~ — **fixed, confirmed live.** A Hindi-only glossary hint in the system prompt; re-translating the exact flagged instructions now returns the correct words.
6. ~~CORS is wide open~~ — **now configurable** (`CORS_ORIGINS` env var, defaults unchanged for local dev).
8. ~~`dist/i18n.js`'s dev-port guess must be replaced before a real demo~~ — **a same-origin option now exists.** `backend/app.py` serves `dist/` itself; run the demo from `http://<device>:8010/` instead of `:8080` and the guess is never exercised. (The old dev setup on `:8080` still works too, guess and all — this is an addition, not a removal.)
9. ~~No `node` on this machine~~ — **fixed.** Installed locally via conda, no `sudo`. `state.test.cjs` and `version-assets.cjs --check` now run for real.
10. ~~No tooltip on the low-confidence pill; generic backend-down error~~ — **both fixed**, verified live (including by actually stopping the backend to check the specific message appears).
- **A new bug found and fixed along the way, not on the original list:** an invented sentinel could leak into the family-facing text as literal `⟦T1⟧` syntax (`translate.py`'s `restore()` used to echo back anything sentinel-shaped it didn't recognize, instead of stripping it). Found via `metrics.json` surfacing a live example; fixed and unit-tested.
- **A second new bug found and fixed:** `refreshLetterControls` acted on the letters page's singleton checkbox/stale-note using whichever `blockId` last resolved, anywhere in the app — a finding or task translating in the background while on the letters page (or a different letter template's fetch resolving late) could silently touch the wrong letter's controls. This is this pass's best working theory for gap #5 below, though not a certain explanation of it.

**Still open, honestly:**

3. **The 0.85 threshold is deliberately kept, not tuned down** — phase 6's reasoning stands unchanged; see its write-up.
5. **Phase 5's one unreproduced anomaly** (a stale-note shown during what should've been a first-ever translation) is still not conclusively explained — a real, related bug was found and fixed (above), but that isn't the same as confirming it was the cause.
7. **The Gmail URL fallback threshold (1800 chars) is still untuned** — no Google account is available in this environment to test against a real compose-link limit. Left honestly flagged rather than guessed at.
11. **The phase 7 label table's known higher error rate on short strings** stands as documented — already hand-reviewed once, nothing new to add.
- **The human-check metric (phase 6) and a native-speaker re-review of the label table (phase 7) still haven't run** — no reviewer has been available in this environment at any point. This is the single highest-value thing an actual person could still add.
- **If the real Nano's model differs from `Qwen/Qwen3-4B-Instruct-2507`**, all of the above (the negation guard, the Hindi hint, the specific numbers in `metrics.json`) are validated against *this* model — rerun `backend/dev/phase0_spike.py` first.

## Suggested next steps

The plan (phases 0–7) plus a gap resolution pass are both done. What's left needs either a live Gmail account or a human reviewer, neither available in this environment — everything else that could be fixed with more engineering has been:

- **Get a native speaker's eyes on `metrics.json`'s flagged translations and the label-table strings in `dist/i18n.js`'s `UI_LABELS`** — the highest-value remaining gap, by a clear margin.
- **Test the Gmail URL fallback threshold against a real account**, and adjust the 1800-char number in `dist/i18n.js`'s `open-gmail` action if it's wrong.
- **Run the demo same-origin** (`http://<device>:8010/`, see above) at least once before a real demo, rather than only ever the dev `:8080` setup this whole plan was built and verified against.
- **If the real Nano's model differs from `Qwen/Qwen3-4B-Instruct-2507`:** rerun `backend/dev/phase0_spike.py` first — the negation guard and Hindi hint were tuned against this model's specific failure modes, not necessarily the real one's.

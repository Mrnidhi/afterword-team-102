# Multilingual summaries and letters: implementation plan

Part two of the Afterword build. A language toggle regenerates the plain-language finding summary, task next steps and the outbound provider letter in Spanish, Vietnamese or Hindi. Translation runs on the ZGX Nano.

**The idea behind it:** the provider needs the letter in English, and the family needs to understand that letter before they send it. So we are not building a translate button. We are building a **bilingual letter view**. The English text that will be sent sits beside a translation the family reads for comprehension. English is sent by default, with an explicit "send the translated version instead" option.

> Pitch line: *"The letter goes out in the provider's language. The family reads it in theirs first."*

---

## Where the spec differs from the repo

The spec was written before these details were checked. Each point below changes how part of the plan is built.

| Spec assumption | What the repo actually has | Decision |
|---|---|---|
| Persist in `afterword-design-v2` | `dist/store.js` writes `afterword-workspace-v3`. It reads v2 only as a legacy migration source, and `clean()` drops every key it doesn't allowlist. | Add `lang: 'en'\|'es'\|'vi'\|'hi'` to `defaults()` and `clean()` in v3. A value written to v2 would be ignored. |
| `backend/` exists | There is no backend. The app is buildless static `dist/`, deployed to GitHub Pages. | Create `backend/` from scratch (FastAPI + stdlib `sqlite3`). |
| Gmail handoff exists | Letters support save, preview, print and text export only. There is no mail handoff. | Add a small Gmail compose-URL handoff in phase 5 (about 20 min, not in the original estimates). |
| Frontend can call the Nano | Pages is served over public HTTPS. The Nano is on the LAN over HTTP, so the browser blocks mixed content and CORS applies. | For the demo, serve `dist/` **from the Nano** (same origin). On Pages, feature-detect the API and hide translation controls when it isn't reachable. |
| `CLAUDE.md`, `PLAN.md` | Neither exists in this repo. | The Claude Code prompts below reference this file and `README.md`. |
| DM Sans / Newsreader | `styles.css` loads both, but `studio.css` overrides `--sans` to Plus Jakarta Sans, which is what body text actually renders in. Phase 0 confirmed Plus Jakarta Sans covers every Vietnamese glyph tested — no fallback font needed. | — |

---

## Phase 0: Spike and de-risk (30 min, before any feature code)

Test the three things that could sink this feature before building on them.

1. **LLM on :8000.** Confirm the API shape (OpenAI-compatible `/v1/chat/completions`?) and the model name. Translate one finding into `es`, `vi` and `hi` by hand and time each.
2. **Embeddings on :8003.** Confirm the endpoint and vector size. Embed two paraphrases and one unrelated sentence, and check that the scores separate. This validates the 0.85 starting threshold.
3. **Sentinel survival.** Send text containing `⟦T1⟧ ⟦T2⟧` through each language 10 times and count how often the model keeps them intact. If survival is poor, switch to an ASCII sentinel (`[[T1]]` or `<T1/>`) before building L1 around `⟦⟧`.
4. **Glyphs on the demo machine.** Render `ế ộ ữ ặ` in DM Sans and Newsreader, and `नमस्ते बीमा पॉलिसी` in Noto Sans Devanagari, in the actual demo browser.

**Exit criteria:** endpoints documented at the top of `backend/translate.py`, sentinel format chosen, glyph screenshot saved.

**Status: done.** Measured over the actual demo content (3 findings, 3 letters, 4 task instructions × es/vi/hi = 30 texts), using `backend/dev/model_server.py` (a same-API stand-in, since nothing was reachable on :8000/:8003 here) and `backend/dev/phase0_spike.py`. Full numbers in `backend/dev/phase0_results.json`.

**1. LLM on :8000.** Standard OpenAI-compatible `chat/completions`. Spiked with `Qwen/Qwen3-4B-Instruct-2507` (already on this machine; picked over the Nemotron-3-Nano-4B checkpoint also present, for stronger Hindi/Vietnamese). Confirm the actual model before phase 2 — swap it in `backend/dev/model_server.py`'s `--model` and rerun if the Nano ships something else. Median forward latency:

| | es | vi | hi |
|---|---|---|---|
| summary | 5.4s | 6.5s | 18.1s |
| letter | 5.7s | 6.2s | 18.7s |
| instruction | 1.3s | 1.6s | 5.4s |

Hindi runs 3× slower than Spanish/Vietnamese on this model — plan the prewarm (phase 6) and the demo pacing around the ~19s worst case, not the ~5s median.

**2. Embeddings on :8003.** Standard `embeddings` endpoint, spiked with `BAAI/bge-small-en-v1.5` (downloaded during the spike; nothing was cached). Calibration on hand-written pairs, cosine similarity:

| Pair | Score |
|---|---|
| Paraphrase | 0.94 |
| Dropped fact | 0.80 |
| Unrelated sentence | 0.56 |
| **Meaning flipped ("was applied" → "was not applied")** | **0.90** |

The threshold separates good translations from dropped facts and unrelated text cleanly. **It does not catch a negation** — a flipped meaning scored *above* 0.85. Embedding similarity is a paraphrase detector, not a fact-checker; it won't be enough on its own if the model ever inverts a sentence. Noted as a known limitation, not solved this week (see Risks).

**3. Sentinel format.** `⟦T1⟧` (unicode) clearly beats `[[T1]]` (ascii): unicode lost zero tokens forward or backward across es/vi (10/10 texts each), and only 2/30 texts lost a token on the *return* leg in Hindi. Ascii lost a token forward in 7/30 texts, worse in Hindi (3/10). **Keeping `⟦T1⟧`** — no fallback needed. One real failure mode to carry into phase 2's retry logic: the model occasionally *invents* an extra sentinel that wasn't in the input (`check()` already reports this as `unexpected ⟦Tn⟧`, so the existing retry-once handles it).

**4. Round-trip threshold.** With `⟦T1⟧` and es/vi/hi:

| | median | worst | below 0.85 |
|---|---|---|---|
| es | 0.966 | 0.892 | 0/10 |
| vi | 0.917 | 0.705 | 1/10 |
| hi | 0.887 | 0.747 | 3/10 |

**Keeping 0.85.** It doesn't over-flag es or vi, and the 3 Hindi cases it flags are real: this 4B model repeatedly translates "policy" (insurance) as "नियमित प्रकाशन" ("regular publication") or "नियमित नियम" ("regular rules") instead of "पॉलिसी", which the round-trip check catches correctly. **Flag this specific weakness for whoever reviews Hindi output before the demo** — it's the one place a native speaker's spot-check (the optional metric in phase 6) would earn its keep.

**5. Glyphs.** `studio.css` sets `--sans: 'Plus Jakarta Sans'` as the actual body font (not DM Sans/Newsreader — those are imported by `styles.css` but overridden). Plus Jakarta Sans covers **every** test Vietnamese character. **No Vietnamese font fallback is needed**, simplifying phase 3/6. Noto Sans Devanagari covers all tested Devanagari glyphs, as expected; Plus Jakarta Sans has none (confirmed, expected to fail). Screenshot taken with headless Firefox via `backend/dev/glyph-test.html`.

**Changed from the plan:** the DM Sans / Newsreader glyph check in the spec (row 3 of the languages table) doesn't apply — the app doesn't render body text in those fonts. Phase 3's font-loading section should target Plus Jakarta Sans + Noto Sans Devanagari only.

---

## Phase 1: Protected-token helper (L1, P0, 45 min)

`backend/translate.py` → `protect(text) -> (masked, tokens)` and `restore(masked, tokens) -> text`

Five token kinds, extracted in this order so longer matches win:

| Kind | Examples from the demo archive | Rule |
|---|---|---|
| Placeholders | `[NAME]`, `[POLICY NUMBER]` | `\[[A-Z][A-Z _-]*\]` |
| Provider names | `Cedar Life — policy services` | Exact match against a list built from `letterTemplates` recipients and `records` sources. **No NER.** |
| Amounts | `$250,000`, `$1,240`, `$400`, `$129` | Currency symbol or code followed by a number |
| Dates | `September 10`, `2019`, `2024-09-14` | Month name + day (+ year), ISO dates, standalone 4-digit years in the range 1900–2099 |
| Policy/account numbers | `POL-48213`, `Acct 0042-771` | Letter/digit runs containing at least 4 digits, optionally with `-` or spaces |

- Replace each match with a numbered sentinel. Keep a `{sentinel: original}` map.
- `restore` substitutes back. `check(masked_out, tokens)` returns the list of missing or duplicated sentinels.
- **Tests** (`backend/tests/test_translate.py`): one fixture letter containing all five kinds. Test the round trip (`restore(protect(x)) == x`), overlapping matches (an amount inside a date string), a sentinel the model dropped, and a sentinel the model duplicated.

This is a code-level guarantee. The prompt also asks the model to keep the sentinels, but correctness never depends on the prompt.

**Status: done.** Implemented in `backend/translate.py`. Changes from the plan above:
- Person names (Arun, Priya and Maya Rao) are also protected, as a sixth kind.
- Tests use stdlib `unittest`, so they need no dependencies (pytest can also run them). Run with `python3 -m unittest discover -s backend/tests`.
- The sentinel format lives in `SENTINEL`/`SENTINEL_RE`, so phase 0 can change it in one place.

---

## Phase 2: Translation service (L2, P0, 1 h)

### Endpoints

```
POST /translate  { text, target_lang, kind: "summary"|"letter"|"instruction" }
  -> { text, lang, cached, round_trip_score, protected_tokens_ok, low_confidence, ms }

GET  /languages  -> [{ code, name, native_name, script, font: { family, css_url } | null }]
```

### Pipeline for a single request

1. Validate `target_lang ∈ {es, vi, hi}` and `kind`. Cap `text` at 12,000 characters (matching the draft body limit in `store.js`).
2. **Cache lookup.** Key: `(lang, kind, sha256(source), prompt_version, model_id)`. The last two fields mean that changing the prompt or model never serves stale translations.
3. `protect(source)` → masked text.
4. **Translate.** Send the masked text and the system prompt to :8000. Temperature 0–0.2.
5. **Check tokens.** Every sentinel must appear exactly once. If not, **retry once**. If it still fails, return `protected_tokens_ok: false` and let the frontend show the flag. Never silently drop a token.
6. **Round-trip.** Translate the output back to English, still masked, then restore both English versions. Embed both via :8003 and compute cosine similarity. Set `low_confidence = score < 0.85`. The threshold comes from an env var so it can be tuned after phase 6.
7. Store in SQLite (`backend/afterword.db`, table `translations`): the key columns, `text`, `round_trip_score`, `tokens_ok`, `ms`, `created_at`.

### System prompt rules

- Translate only the given text into `<language>`. Output only the translation.
- Keep every `⟦Tn⟧` exactly as written.
- Use plain, respectful language at a sixth-grade reading level. For Hindi and Vietnamese, use common everyday words instead of anglicised finance jargon where one exists.
- Do not add, remove or explain facts.
- The translator only ever sees the English source text, never the raw documents. This is enforced by what the endpoint accepts.

### Operational details

- Handle CORS for dev only. In the demo, serve `dist/` as static files from the same FastAPI app.
- Add `GET /health` so the frontend can feature-detect the API.
- Keep the per-request timeout below the LLM's worst-case time. The frontend shows a "Translating on this device…" state.

**Status: done.** Implemented in `backend/app.py`, run with `cd backend && python -m uvicorn app:app --port 8010` (needs the `zgx` conda env for fastapi/uvicorn/httpx). 25 tests in `backend/tests/test_app.py` pass, using a fake HTTP client so they never depend on the model servers being up — they check the cache hit/miss path, the retry-once-on-a-dropped-token logic, the low-confidence flag, that the raw `$250,000` amount never reaches the fake translator, and input validation. Then verified for real against the live servers from phase 0:

```
POST /translate {text: "...invoice dated September 10, 2026 showing $1,240...", target_lang: hi, kind: letter}
  cold: 9.4s, round_trip_score 0.845, protected_tokens_ok true, low_confidence true (flagged, matches phase 0's finding on hi letters)
  same request again: 19ms, cached: true — from SQLite, no second model call
```

**Changed from the plan / notes for phase 3+:**
- `GET /health` and CORS/static-serving are folded into phase 2 rather than left as loose "operational details," since phase 3's frontend depends on `/health` existing to feature-detect the API. Static file serving of `dist/` is not wired up yet — still open for whoever picks up phase 3, or a separate `--port 8080`-style file server (one is already running for the frontend) is fine for local dev.
- The service runs on **:8010**, not :8000/:8003 — those two ports are the model servers it calls, not the service itself. `GET /translate` and friends are on the Afterword backend's own port.
- `translation(lang, sha256(source), kind)` from the spec became a 5-part key in practice: `prompt_version` and `model_id` were added so a prompt or model change can't silently serve a stale translation, as flagged in the phase 1 cache design.
- Response field is `protected_tokens_ok`, a plain bool — the detailed list of *which* token went missing (from `check()`) is used internally to decide on the retry, but isn't sent to the frontend. If a future debug view wants it, it's one field to add.

---

## Phase 3: Language preference and fonts (L3 + L6, P0, 1 h)

**Store (`dist/store.js`)**
- Add `lang:'en'` to `defaults()`, and `d.lang = ['en','es','vi','hi'].includes(v.lang) ? v.lang : 'en'` to `clean()`.
- Add cases to `tests/state.test.cjs`: an unknown value falls back to `en`, and a v2 → v3 migration keeps `en`.

**Preferences dialog (`dist/app.js`, the `preferences` action)**
- Add a "Reading language" select next to "Text size". Options show native names: English, Español, Tiếng Việt, हिन्दी.
- Read it in `save-preferences`. The existing `persist()` handles the rest.
- If `/health` fails, disable the select and add the hint "Translation needs the Afterword device."

**Compact toggle:** a small select on the finding and letter views that shares the same state.

**Fonts: `dist/i18n.js` (new, buildless)**
- `ensureFont(lang)`: for `hi`, inject `<link>` to `Noto Sans Devanagari` once. For `vi`, fall back to `Noto Sans` if the phase 0 check failed. The default English page loads nothing new.
- Google Fonts `css2` serves `unicode-range` subsets automatically, so Vietnamese glyph files download only when Vietnamese text appears.
- Font stack on translated blocks: `[lang="hi"] { font-family: 'Noto Sans Devanagari', var(--sans); }`. Devanagari needs a larger `line-height` (~1.8) because of its tall glyphs above and below the line.
- Set `lang` on the **translated element only**, never on `<html>`, so screen readers switch voice for that block alone.

Run `node scripts/version-assets.cjs` after adding `i18n.js`, and add it to the script tags in `index.html`.

**Status: done** for the store, preferences dialog and font loading. The compact on-page toggle is deferred to phase 4, since it lives inside `evidencePage`/`lettersPage`, which that phase touches anyway.

**Verification — and why it wasn't `node tests/state.test.cjs`:** there is no `node` binary anywhere on this machine, so the repo's own CommonJS test files (`tests/state.test.cjs`, `scripts/version-assets.cjs`) cannot run here at all — that's an environment gap, not something introduced this phase. Two workarounds, both real-browser, no mocks:
- `backend/dev/store-test-harness.html` loads the actual `dist/store.js` and runs the same style of assertions as `state.test.cjs`, in a real browser via `localStorage`. All 8 pass, including the new `lang` cases mirrored into `tests/state.test.cjs` itself (run those for real the first time a `node` is available).
- `scripts/version-assets.cjs`'s hashing was reproduced in Python (identical regex and sha256-slice-12 logic) to version `index.html`'s script tags; running it twice produced no further diff, which is what `--check` verifies.
- The dialog, the save flow, and the font loading were driven with Selenium + a real headless Firefox against the actually-running stack (`dist/` on :8080, `backend/app.py` on :8010) — 12 checks total, covering the backend-reachable path (select enabled, defaults to English, selecting Hindi lazily adds the Devanagari `<link>`, the choice persists across a real page reload) and the backend-down path (select disables itself, the "needs the Afterword device" note shows, a previously-saved language stays shown rather than silently reverting to English).

**Bugs found and fixed along the way, not part of the original plan:**
1. **`scripts/version-assets.cjs`'s own regex silently skipped `i18n.js`** — `[a-z-]+` doesn't match digits, so a file with "18" in its name never got a cache-busting hash. Widened to `[a-z0-9-]+`. This is a latent bug in a file this plan didn't otherwise touch; anyone naming a future asset with a digit would hit the same silent miss.
2. **No CORS on the backend.** Phase 2 marked this as an "operational detail" but never actually added it — first real cross-origin call from the browser would have failed silently. Added permissive dev-only `CORSMiddleware` to `backend/app.py` (`allow_origins=['*']`), commented as unnecessary once the real demo serves `dist/` from the same device.
3. **Not a product bug, but worth recording:** `driver.get()` to a URL that's byte-identical to the current one (same hash fragment) is a same-document no-op in this Firefox/geckodriver combination — it never re-runs the page's scripts. The first pass at the persistence test used that and passed for the wrong reason (it was reading in-memory state that had never been reloaded, not proving anything about actual reload behavior). Fixed by using `driver.refresh()` for every check that's supposed to prove something survives a reload.

**Changed from the plan:**
- The Vietnamese fallback font in `ensureFont` was dropped. Phase 0 found Plus Jakarta Sans — the app's real body font — already covers every Vietnamese glyph tested, so there is no `vi` entry with a `font` key at all (matches what `backend/app.py`'s `GET /languages` already returns).
- `dist/i18n.js` guesses the backend's URL from `location.port` (`:8080` → `http://127.0.0.1:8010`, otherwise same-origin) so local testing works without extra config, overridable via `window.AFTERWORD_API`. This is a dev convenience specific to how this repo's ports happen to be set up right now — replace it with same-origin serving (`dist/` served by the Afterword device itself) before the real demo, so the guess is never relied on live.

---

## Phase 4: Finding view and task next steps (L4 + L7, P0/P1, 50 min)

**What gets translated.** Each finding in `dist/pages.js` has `lead`, `known`, `unknown` and `next` fields. Send them as one `kind: "summary"` request, joined with stable separators, so a finding costs one round trip. Task next-step text (the `subtle-box` copy in `openTask`) uses `kind: "instruction"`.

**Evidence page:** add a translated block under the English summary.
- Label: "Translated on this device".
- When `low_confidence` is true or `protected_tokens_ok` is false, add the amber pill **"Machine translation — please check"**. Its tooltip shows the score in plain words ("the back-translation differed from the original").
- States: loading (skeleton + "Translating on this device…"), error ("Couldn't translate right now. The English above is complete."), unavailable (block hidden).
- Source documents and excerpts are **never** translated. They are evidence and stay verbatim.

**Client cache:** keep an in-memory `Map` keyed by `lang + hash` so re-renders don't refetch. The server cache makes a real re-fetch instant anyway.

**Status: done.** `dist/i18n.js` gained `window.translatedBlock(text, kind, blockId)` (the finding summary and task instruction blocks), `window.compactLanguageToggle()` (the on-page toggle deferred from phase 3), both wired into `dist/pages.js`'s `evidencePage()` and `openTask()`. New CSS in `dist/workspace.css` reuses `.subtle-box`'s look for `.translated-block` rather than inventing a new visual language, plus the `[lang="hi"]` font rule from phase 3's spec.

**Verified for real**, against the live backend and model servers from phases 0–2, via headless Firefox:
- English shows no translated block anywhere; switching to Spanish shows a loading state immediately, then resolves to real Spanish text tagged `lang="es"`.
- Switching to Hindi resolves, applies the Devanagari font via the `[lang="hi"]` selector (confirmed via `getComputedStyle`), and — this is the one worth trusting the round-trip check for — **the exact task instruction phase 0 flagged in Hindi (`round_trip_score` 0.80, "policy" mistranslated as "regular rules") shows the amber "Machine translation — please check" pill in the actual rendered page**, not just in the API response.
- Re-rendering the same content in the same language (switching findings and back) reappears instantly from the client cache; the identical request against the real backend also came back from *its* SQLite cache in the same run — both cache layers confirmed working together, not just in isolation.
- Switching back to English removes every translated block.

**A real, non-obvious bug found and fixed while verifying this, not a test artifact:** on a page loaded straight to a hash route (e.g. opening `#evidence` directly, not navigating there from `#overview`), the translated block and compact toggle were silently missing and stayed missing until some unrelated click re-rendered the page. Cause: `workspace.js` (which registers the real page renderers) does its own trailing `render()` call to finalize the very first paint — but it runs *before* `i18n.js`, so that first paint always happened before `window.translatedBlock`/`window.compactLanguageToggle` existed, and nothing ever re-rendered afterward to pick them up. Fixed the same way the codebase already solves this exact problem: `i18n.js`, being last in script-load order, now does its own trailing `render()` too. Worth remembering for phase 5 — any new render-time hook registered in `i18n.js` needs nothing further, but a hook added to a file that loads *before* `i18n.js` and is also called from a first-paint-reachable render path would need the same treatment.

**Changed from the plan:**
- No tooltip on the low-confidence pill (the plan's "shows the score in plain words" via a `title` attribute) — deferred as a small polish item, not required for correctness.
- The "unavailable" state (`/health` down) reuses the same `.error`-style hidden-block behavior as any other fetch failure — `requestTranslation`'s `catch` doesn't distinguish "backend unreachable" from "backend returned an error," which is fine for the demo but means the finding-view message is generic rather than pointing at the device specifically the way the preferences dialog's note does.

---

## Phase 5: Bilingual letter view (L5, P0, 1 h 20 min including the handoff)

**Layout (`lettersPage` in `dist/pages.js`, styles in `workspace.css`)**
- Two columns, labelled **"What will be sent (English)"** and **"For you to read (Tiếng Việt)"**. The label uses the native language name.
- Below 900px the columns stack, with English first.
- The English column is the existing editable form, unchanged. The translation column is read-only.

**Edited drafts:** users edit the English body, so translations can go stale.
- When the English body's hash no longer matches the translated source, dim the translation and show "Translation is out of date · Update". Don't retranslate on every keystroke. Retranslate on save or when the user clicks Update, reusing the existing autosave debounce if needed.
- Each edited draft becomes a new cache entry, which is the expected behaviour.

**Send the translated version instead**
- Checkbox label: "Send the [Español] version instead". The one-line caution beneath it reads: "The provider may not be able to read this. English is usually safer."
- The checkbox is disabled while the translation is out of date or flagged low-confidence, so a doubtful translation can never be sent.
- The choice is kept per session, not persisted, so every letter starts on English.

**Gmail handoff (new)**
- Button: "Open in Gmail". It builds `https://mail.google.com/mail/?view=cm&to=…&su=…&body=…` from whichever body is selected.
- Percent-encoded Devanagari roughly triples in length. If the URL is over ~1,800 characters, fall back to "Copy letter" plus opening Gmail with only the subject, and tell the user why.
- Add `recordActivity('Opened Gmail with the <lang> version of …')` so the language choice shows in the activity log.

**Print/export:** the existing `print-letter` flow gets `@media print` styles that keep both columns, each column header, and the "comprehension support, not a legal translation" footer. The text export writes both versions, separated by headings.

---

## Phase 6: Demo hardening and metrics (L8 + metrics, P1, 1 h)

**Pre-warm (L8):** on backend startup, a background task translates every finding summary, task instruction and letter template into all three languages. The demo archive is small (3 findings, 7 tasks, 3 letters), so that's ~39 requests. It logs progress, and `/health` reports `prewarm: n/total`. **Check that the prewarm has finished before going on stage.**

**Metrics script: `backend/metrics.py`**, which prints a table and writes `metrics.json`:

| Metric | How it's measured | Target / how to report |
|---|---|---|
| Round-trip similarity | Median and worst case per language over all demo content | Report the raw numbers. Worst cases guide the threshold. |
| Protected-token preservation | Count across every translation | Must be 100%. "N of N amounts, dates and policy numbers preserved" |
| Latency | Median seconds per kind per language, measured **cold** (cache bypassed) on the Nano | For the pitch: no per-character API bill, no data leaves the device |
| Coverage | Share of demo content available in all four languages | 100% after the prewarm |
| Human check (optional) | A native speaker rates 10 samples | Report n. Say plainly that this is not a formal evaluation. |

**Threshold tuning:** once metrics have run, look at the lowest-scoring translations. If good translations fall below 0.85, lower the threshold and write down why. Don't tune it on stage.

---

## Phase 7: Stretch (P2, only if P0/P1 are done)

- **L9, 12-string label table (45 min):** covers the most-used labels only (page headings, Save, Print, Open in Gmail). Store it as a static JSON per language, pre-translated through the same endpoint and reviewed by hand. Don't try to translate the whole app.
- **Voice memo transcripts:** apply `kind: "summary"` to the transcript text, if audio is in the demo.

---

## Out of scope this week

- Full UI chrome translation (beyond the optional L9).
- Right-to-left languages. All three targets are left-to-right.
- Translating source documents. They are evidence and stay verbatim.
- Locale-formatted numbers and dates. Protected tokens stay exactly as in the source by design.

---

## Schedule

| Phase | Tasks | Pri | Est. | Can run in parallel with |
|---|---|---|---|---|
| 0 | Spike: endpoints, sentinels, glyphs | P0 | 30m | — |
| 1 | L1 token helper + tests | P0 | 45m | 3 |
| 2 | L2 `/translate`, cache, round-trip | P0 | 1h | 3 |
| 3 | L3 + L6 preference, store, fonts | P0 | 1h | 1, 2 |
| 4 | L4 + L7 finding and task blocks, flag | P0/P1 | 50m | 5 |
| 5 | L5 bilingual letter + Gmail handoff | P0 | 1h20m | 4 |
| 6 | L8 prewarm + metrics | P1 | 1h | — |
| 7 | L9 labels, voice memos | P2 | 45m+ | — |

The P0 path takes about 5h of single-person work. With two people (one on backend phases 1–2, one on frontend phase 3, then 4 and 5 split), it takes about 3h.

---

## Risks

| Risk | Mitigation |
|---|---|
| Mistranslation in a legal-ish letter | English is sent by default. The translation is labelled as comprehension support. Low-confidence translations are flagged and can't be sent. |
| Devanagari renders as boxes | Phase 0 glyph check on the demo machine. Ship Noto Sans Devanagari. Never demo Hindi without confirming glyph coverage. |
| Numbers or policy IDs mangled | Sentinel substitution in code, an assertion, one retry, and a flag if the retry fails. Reported as a metric. |
| Model drops or alters sentinels | Phase 0 measures this. If needed, switch to an ASCII sentinel format. |
| Demo can't reach the Nano from Pages | Serve `dist/` from the Nano for the demo. On Pages, the translation UI hides cleanly. |
| Latency stalls the demo | Prewarm at startup and confirm completion via `/health` before going on stage. |
| Edited letter shows a stale translation | Hash comparison, an "out of date" state, and sending disabled until the translation is updated. |
| Overclaiming quality | Always say "on-device machine translation, verified by round-trip similarity", never "accurate translation". |

---

## Claude Code prompts (updated for this repo)

**Prompt A: backend (phases 1–2)**
> Read README.md and MULTILINGUAL-PLAN.md. Create `backend/` (FastAPI, stdlib sqlite3). Add `backend/translate.py` with `protect`/`restore`/`check` for placeholders, provider names (from a fixed list), amounts, dates and policy/account numbers, using the sentinel format chosen in phase 0, with pytest tests covering a letter containing all five kinds plus dropped and duplicated sentinels. Then add `POST /translate`, `GET /languages` and `GET /health`, calling the local LLM on :8000 for es/vi/hi, with a SQLite cache keyed by (lang, kind, sha256(source), prompt_version, model_id), a round-trip cosine check using the embedding model on :8003 (threshold from env, default 0.85), and a token assertion with one retry. Serve `dist/` as static files from the same app.

**Prompt B: preferences, fonts and finding view (phases 3–4)**
> In `dist/`, add `lang` to `AfterwordStore` defaults and `clean()` (persisted in `afterword-workspace-v3`) with tests in `tests/state.test.cjs`. Add a reading-language select to the preferences dialog in `app.js`, disabled when `/health` is unreachable. Add `dist/i18n.js` for API calls and lazy font loading (Noto Sans Devanagari for hi, a Vietnamese fallback if needed). Render a translated block under the finding summary on the evidence page, with a "Translated on this device" label, and show "Machine translation — please check" when `low_confidence` is true or `protected_tokens_ok` is false. Set `lang` on the translated element only. Keep the app buildless and run `scripts/version-assets.cjs`.

**Prompt C: bilingual letter (phases 5–6)**
> Rework `lettersPage` into a bilingual layout: "What will be sent (English)" beside "For you to read ([native language name])", stacked below 900px. Mark the translation as out of date when the English body hash changes. Add an "Open in Gmail" compose-URL handoff with a copy fallback for long URLs, and a checkbox to send the translated version instead (disabled while stale or low-confidence) with a one-line caution. Make print and text export include both versions. Add a startup prewarm for all demo findings, instructions and letter templates, reported via `/health`, and `backend/metrics.py` producing the phase 6 metrics table.

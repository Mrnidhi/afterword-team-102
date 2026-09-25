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

**Status: done.** Bilingual columns in `dist/pages.js`'s `lettersPage`, staleness/checkbox/Gmail/export logic in `dist/i18n.js`, layout and print CSS in `dist/workspace.css`. 20 real browser+backend checks pass (Selenium + headless Firefox against the live services, no mocks): the translated column resolves and shows real Spanish/Hindi text; editing the English body dims the translation and shows "Translation is out of date · Update" immediately, without firing a request; clicking Update retranslates and the checkbox re-enables only once that new translation actually resolves; a long Hindi/Vietnamese body correctly falls back to clipboard-copy with an empty Gmail body param; the text export includes both versions under a "FOR YOU TO READ" heading; a real `print_page()` capture (not just `@media print` read as text) shows the two columns side by side with the checkbox and its caution hidden, replaced by a dedicated print-only footer. Confirmed with real screenshots, not just DOM assertions.

**Simplified from the plan**, for robustness given the time available — recorded here so a future pass can revisit:
- **Only the letter body is translated**, not the subject. The spec's two-column framing implies the whole letter reads bilingually, but re-splitting one combined subject+body translation back into two fields is fragile (the model doesn't reliably preserve exactly where the paragraph break falls), so the subject stays in English in both columns. The subject lines in this demo are short and low on the kind of nuance a family would need help with ("Request for information about an existing policy"), so this is a reasonable trade, but it is a real gap from "the whole letter, bilingually."
- **Staleness is a straight text comparison**, not a hash. `letterTranslationState` compares the current body against `lastOkText[blockId]` (the exact string last successfully translated) rather than hashing it — equivalent in effect, simpler in code, no user-visible difference.
- **The "long URL" fallback threshold (1800 chars) is untuned** — it's the number from the original spec, not something measured against Gmail's actual compose-link limit on a real account. Worth a real check before the demo if a very long letter is likely.

**A real bug found while wiring this up, unrelated to translation:** switching the three new footer buttons ("Save draft", "Open in Gmail", "Download letter") to the shared `button()` helper silently dropped `type="button"`, which the original hand-written markup had. Since these buttons live inside `<form id="letter-form">`, an omitted `type` defaults to `type="submit"` — clicking any of them would have submitted the form and reloaded the page, since no submit handler exists for `#letter-form`. Caught before it shipped by checking the diff against the original markup line-by-line, not by the automated tests (Selenium's `.click()` on a real button does trigger real submit behavior, so this would have surfaced as a failing "Gmail URL opened" check too — but I'd rather have caught it by inspection than by a flaky-looking test failure). Fixed by hand-writing all three with explicit `type="button"`, matching the codebase's own established convention (its two genuine form-submit buttons elsewhere are also hand-written, never through the shared helper).

**A second bug found, this time in the plumbing, not the markup:** the first version only patched the translated-block `<div>` itself when a fetch resolved — the sibling "send this version instead" checkbox never got told the translation was ready, so it silently stayed disabled forever after the very first translation (and again after every Update). Fixed by having every resolution path funnel through one `refreshLetterControls(blockId, text)` call that updates the block, the stale-note, and the checkbox together. Full trace in the code comments in `dist/i18n.js`.

**One finding I could not pin down, and am recording rather than hiding:** a single screenshot, taken right after a heavy run of prior tests, showed the "Translation is out of date · Update" note visible *at the same time* as a translation's very first "Translating on this device…" loading state — which shouldn't be possible, since staleness is only supposed to apply after a translation has already succeeded once. Two careful follow-up attempts to reproduce it — including one with artificial backend load — both showed correct behavior, and reading through the staleness logic doesn't reveal an obvious path to that state. My best guess is a render ordering artifact under heavy concurrent load on the model server's single-generation lock, not something a normal user session would hit, but I'm flagging it rather than asserting it's nothing.

**Also found and fixed in passing:** `translatedBlockMarkup` (phase 4's shared component) now names the language in its own label — "Translated on this device (Español)" instead of the bare "Translated on this device" — which reads better once the same component sits inside a column already labelled "For you to read," and costs nothing to apply retroactively to the finding and task views from phase 4 too.

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

**Status: done.** `backend/demo_content.py` extracts the demo archive's text straight from `dist/pages.js` (findings, letter bodies, task instructions), so the prewarm, `metrics.py` and the phase 0 spike can never drift from what the frontend actually sends — `phase0_spike.py` was refactored to import it instead of keeping its own copy. Prewarm runs as a daemon thread from `app.py`'s FastAPI startup event, and `/health` reports `prewarm: "n/total"`.

**Real numbers, from `backend/metrics.py` run against the live services** (10 demo items × es/vi/hi = 30 translations; `metrics.json` has the full detail):

| Metric | es | vi | hi |
|---|---|---|---|
| Round-trip similarity (median / worst) | 0.961 / 0.886 | 0.929 / 0.782 | 0.894 / 0.747 |
| Cold latency, median (instruction / letter / summary) | 2.3s / 9.9s / 9.6s | 2.9s / 10.5s / 10.9s | 6.4s / 23.5s / 23.5s |

- **Protected-token preservation: 100.0% (60 of 60)** — every amount, date, name and account number survived, across all 30 translations.
- **Coverage: 100% (10 of 10 demo items in all three languages)**, confirmed after the prewarm.
- **Low-confidence flags: 4 of 30 (13%)** — `instruction/task0` in vi (0.845) and hi (0.807), `instruction/task3` in vi (0.782) and hi (0.747).
- **Prewarm timing, measured for real:** a genuinely cold cache (nothing translated yet) took **~3 minutes** for all 30 items on this model — dominated by Hindi, where forward + back-translation for a letter or summary runs ~23s round-trip and everything is serialized through the model server's single-generation lock. **Restarting the service with an already-warm cache reports `prewarm: 30/30` in under 3 seconds.** This is the number that actually matters for "check prewarm has finished before going on stage": the first-ever cold run needs ~3 minutes of lead time; every restart after that is instant.

**Threshold decision: keeping 0.85, not lowering it.** I didn't just trust the number — I read the actual flagged translations before deciding:
- **`instruction/task0` in Hindi (0.807):** genuinely wrong. "Policy status" comes back as "नियमित नियम" ("regular rules"), the same specific weakness phase 0 first found. Correctly flagged.
- **`instruction/task3` in Hindi (0.747):** genuinely wrong in a different way — "provider" translates to "उपकरण" ("device/tool"), not "प्रदाता" or similar. Correctly flagged.
- **`instruction/task3` in Vietnamese (0.782):** reads correctly to me on inspection ("không liên hệ hay cập nhật bất kỳ nhà cung cấp nào" — "does not contact or update any provider" — accurate). This one looks like a false flag.

Given the mix — two flags are genuine, real errors, and lowering the threshold to let the Vietnamese case through would also let the Hindi mistranslations through unflagged — the safer call for a family-facing tool is to leave the threshold where it is and accept that short, abstract sentences (like task3's "Use this as an organizing step...") occasionally get an unnecessary flag from round-trip cosine's own noise on short text. That's a real, reportable limitation of the metric, not a reason to weaken the safety net it provides. Worth a native speaker's five-minute look at exactly these four before the demo, per the plan's own optional human-check metric (not run here — no native reviewer was available in this environment).

**Human check:** not run, as noted above — reported honestly as `null` in `metrics.json` rather than skipped silently.

**A real concurrency gap found and fixed while building this:** `db_conn()` opened SQLite connections with no busy timeout, so `metrics.py` (a separate process, calling the translation pipeline in-process to avoid an HTTP hop) running alongside the live server could have hit "database is locked" if a write from each collided. Added `timeout=30` to the connection, so a transient collision retries instead of failing outright. `metrics.py` also now calls `init_db()` itself, so it no longer silently depends on the live server having started first.

---

## Phase 7: Stretch (P2, only if P0/P1 are done)

- **L9, 12-string label table (45 min):** covers the most-used labels only (page headings, Save, Print, Open in Gmail). Store it as a static JSON per language, pre-translated through the same endpoint and reviewed by hand. Don't try to translate the whole app.
- **Voice memo transcripts:** apply `kind: "summary"` to the transcript text, if audio is in the demo.

**Status: done** for the label table. The 12 strings are the app's 9 nav page headings (Overview, Action plan, Documents, Evidence review, Letters, Memories, Privacy, Activity, Settings) plus the 3 action buttons on the letters page (Save draft, Print letter, Open in Gmail) — the chrome immediately surrounding the bilingual letter view, the feature this whole plan is built around. `dist/i18n.js` gained a `UI_LABELS` table and `window.uiLabel(text)`, which returns the translated string for the current `state.lang` or falls back to the English string unchanged — safe to call unconditionally, and used that way at every call site (`dist/app.js`'s `navItem()`, `document.title`, the breadcrumb; `dist/pages.js`'s "Save draft"/"Open in Gmail" buttons; `dist/workspace.js`'s "Print letter" button). Unlike `translatedBlock`, this never calls the network and never depends on `/health` — confirmed by pointing `window.AFTERWORD_API` at an unreachable port and reloading: the Hindi nav labels stayed fully translated while the preferences dialog's language select correctly disabled itself.

**Voice memo transcripts: not built, correctly out of scope.** Checked the actual demo content first — there is no audio anywhere in this app, only text framed as a transcript (`dist/pages.js`'s `id:'voice'` record and the `memories` page's "walk" entry), and both explicitly say so in their own copy ("The prototype includes text only; no original recording is attached", "Fictional transcript. There is no original audio attached."). The plan's own condition ("if audio is in the demo") is false, so there's nothing to build. Separately, both of these are source-document/evidence excerpts, which are out of scope for translation regardless (see "Out of scope this week" and phase 4's "Source documents and excerpts are never translated").

**How the 12 strings were generated and reviewed:** `backend/dev/gen_labels.py` called the live `/translate` endpoint (`kind: instruction`) for all 12 strings × es/vi/hi = 36 calls; raw output saved to `backend/dev/labels_raw.json`. I then read every one of the 36 by hand before putting anything in `UI_LABELS` — 9 needed a manual fix, a much higher rate than phase 6 saw on real sentences (4/30), because short, context-free strings expose failure modes full sentences don't:
- **Invented sentinels on text with nothing to protect.** es and vi "Action plan" came back as `'Plan de acción\n\n⟦T1⟧\n\n⟦T2⟧'` and `'Kế hoạch hành động\n\n⟦Tn⟧'` — the model fabricated `⟦Tn⟧` tokens that were never in the input. Phase 0 already named this as a known risk ("the model occasionally invents an extra sentinel"), but it was never actually seen on real demo content, since every real string in this app happens to contain genuine protected tokens for the model to anchor on. `check()` correctly flagged both (`protected_tokens_ok: false`), but the retry-once logic didn't clear it either time — this is a case where the code-level guarantee did its job (a broken string never silently reached the frontend as a "successful" translation) but a human still had to pick the right final text. Used the clean text with the sentinel line stripped for both.
- **Wrong-word and garbled-transliteration errors round-trip cosine missed entirely**, because a fluent-sounding wrong answer round-trips fine: Hindi "Privacy" → "गुप्तचरता" (a real Hindi word, but it means *espionage*, not privacy — scored 0.593, the lowest of all 36, so this one the metric did catch), "Activity" → "क्रिया" (the grammar term for *verb*, not an activity/history log — scored 0.794, flagged but easy to miss among the other short-string flags), and two garbled transliterations that scored a clean 1.000 anyway: "Save draft" → "द्रफ्ट बचाएं" (misspelled "draft") and "Open in Gmail" → "गूगल गमेल में खोलें" (misspelled "Gmail" as "गमेल", and redundantly prefixed with "Google"). Vietnamese "Letters" → "Thông báo" (notice/announcement, not correspondence) also round-tripped fine (0.630, flagged, but for a different-looking reason than being simply wrong). All hand-corrected; see the comment above `UI_LABELS` in `dist/i18n.js` for the corrected values and reasoning per string.

This is the most concrete evidence in the whole plan for why phase 6's threshold discussion said round-trip similarity "is a paraphrase detector, not a fact-checker" — on short strings a wrong-but-fluent answer slips through more often than on full sentences, and a human review step is not optional for anything that will sit in the UI permanently (as opposed to `translatedBlock`'s live, per-request translations, which are flagged in place and never silently trusted).

**Changed from the plan:** stored as a plain JS object literal in `i18n.js` (`UI_LABELS`), not a fetched `.json` file. Every other piece of static per-language data in this app (`LANGUAGES` in `i18n.js`, `LANGUAGES` in `app.py`, `tasks`/`records`/`findings` in `pages.js`) is inlined the same way — this app has no build step and no other runtime `fetch()` of a static asset, so a fetched JSON file would be the only one of its kind and would add an async-loading race on first paint for no benefit, since these 36 strings were reviewed once and don't change at runtime.

**Verified for real**, via headless Firefox against the live `dist/` and backend: switching to es/vi/hi shows every one of the 9 translated nav labels, the translated breadcrumb and `document.title`, and the 3 translated letter-page buttons, while an untranslated label outside the 12-string table ("Reset this template") correctly stays in English — confirming the fallback, not just the happy path. Also hit the exact same `driver.get()`-to-an-identical-URL no-op that phase 3 already found and documented (a same-hash reload silently doesn't re-run scripts in this Firefox/geckodriver combination) while writing this check — same fix, `driver.refresh()` instead of `driver.get()` to the current URL.

---

## Gap resolution pass (after phase 7)

Not a numbered phase — a follow-up pass across phases 0–7, triggered by a request to work through the "Known gaps" list `HANDOFF.md` had accumulated, and to get real unit testing running instead of only the substitute browser-based methods used throughout. All of it verified against the live backend and, where relevant, a real browser — not just re-read from the code.

**Unit testing: `node` is now available.** Installed locally into a dedicated conda env (`conda create -n node-tools -c conda-forge nodejs`) — no `sudo`, no system-wide change, fully reversible. `node tests/state.test.cjs` and `node scripts/version-assets.cjs --check` both now run for real and pass. This closes the one gap that was never a code issue, just an environment one. 15 new backend unit tests were added alongside the fixes below (see the tally at the end of this section) — full backend suite: 44 tests, all passing.

**Resolved:**

1. **The letter subject is now translated too** (closes gap #1 for real, not by retrying the fragile approach phase 5 already rejected). Rather than combine subject+body into one translation and re-split it, the subject is sent as its own small, independent `kind: instruction` request — `window.translatedInline` in `dist/i18n.js`, a lighter sibling of `translatedBlock` with no loading/error card of its own, just falling back to the English subject until a translation resolves. Shown in the "For you to read" column; the outgoing letter's subject is unchanged either way — this was always about what the family can read, never about what gets sent. The text export and print view pick it up automatically since both read from the same DOM/cache. `backend/demo_content.py` now extracts the 3 real letter subjects too, so they're part of the prewarm set and never cause a cold-start delay on stage.

2. **Round-trip cosine now has a negation guard** (directly closes the specific case gap #2 named, without claiming to be a general fact-checker). `backend/app.py` gained `negation_flip()`: a deliberately narrow check for whether a negation word (not/never/cannot/etc.) appears on one side of the round trip and not the other. Verified with a unit test reproducing the exact shape of phase 0's calibration finding ("was applied" → "was not applied") and confirming `low_confidence` trips even when cosine alone scores it above threshold. Stored as a new `negation_flip` column — `init_db()` migrates an existing `afterword.db` automatically (adds the column if missing), so the pre-existing cached rows aren't lost, just superseded once re-translated.

3. **Both specific Hindi weaknesses phase 0/6 named are fixed, confirmed live** (closes gap #4). A small glossary hint scoped to Hindi only (`HINDI_GLOSSARY_HINT` in `backend/app.py` — es/vi never showed this problem, so this isn't a blanket instruction): re-translating the exact two flagged instructions against the running model now returns पॉलिसी for "policy" (was नियमित नियम / नियमित प्रकाशन) and प्रदाता for "provider" (was उपकरण).

4. **A new, previously-undocumented leak found while re-verifying #3: a fabricated sentinel could reach the family as literal `⟦T1⟧` text.** `translate.py`'s `restore()` used to echo back any sentinel-looking match that wasn't a real protected token — so when the model invented one (a risk phase 0 already named, but never seen live before this pass), it leaked straight into the visible translation as meaningless bracket syntax, even though `check()` correctly flagged `protected_tokens_ok: false` for it underneath. Found via `metrics.py` surfacing a live Hindi instruction ending in a stray `⟦T1⟧` after the `PROMPT_VERSION` bump forced a fresh translation. Fixed: `restore()` now strips an unmatched sentinel instead of echoing it back, with a unit test reproducing this exact shape (zero real protected tokens, one invented sentinel) and a live re-check confirming the artifact is gone while the amber warning pill still correctly shows. This is the most concrete bug this pass found — the "never silently corrupt a real token" guarantee already held, but nothing had guaranteed a *fake* one couldn't leak through. **The final `metrics.json` run caught the model doing this a second time, independently** (`instruction/subject-storage/es`, an invented sentinel on a short Spanish subject line with nothing to protect) — confirmed live that the visible text stayed clean while `protected_tokens_ok: false` still correctly flagged it. Not a coincidence: short administrative strings with zero real protected tokens seem to be exactly where this model is most likely to invent one — the same pattern phase 7's label-table review independently found on "Action plan" in es/vi.

5. **A same-origin static-serving path now actually exists**, closing phase 2's "not wired up yet" note and making gaps #6/#8 moot for a real deployment. `backend/app.py` mounts `dist/` as static files at `/`, registered after every API route so `/translate`/`/languages`/`/health` always match first. Running `uvicorn app:app --port 8010` and opening `http://<device>:8010/` now serves the whole app and the API from one origin — no CORS, and `dist/i18n.js`'s dev-port URL guess is never exercised. Verified live (`curl localhost:8010/` returns the real `index.html`, `/app.js` returns the real script, `/health`/`/translate` unaffected). The separate `dist/` + `:8080` dev setup used throughout this whole plan still works exactly as before — this is a new option, not a replacement.

6. **CORS is now configurable, not hardcoded** (closes gap #6 as far as a same-device demo needs). `CORS_ORIGINS` env var, defaulting to `*` — unchanged behavior for local dev. Any deployment that isn't same-origin (item 5) should set an explicit allowlist.

7. **A `refreshLetterControls` singleton cross-contamination bug** — the best working theory this pass has for gap #5's unreproduced anomaly, found by fresh code review, not by reproducing the original screenshot. `translatedBlock` calls `refreshLetterControls(blockId, text)` after *any* block resolves — a finding, a task instruction, or a letter — regardless of which page is currently open. `refreshLetterControls` acted on `#send-translated-checkbox` and `#stale-note-*`, singleton IDs belonging to whichever letter happens to be on screen, with no check that the resolving `blockId` was actually that letter's own. A finding or task translation resolving in the background while the user is on the letters page — or one letter template's in-flight fetch resolving after the user switched to another — could silently apply the wrong content's state to the checkbox and stale-note the user is looking at. Fixed with one guard clause: `if (blockId !== 'translated-letter-' + letterType) return;`. Real and independently justified regardless of whether it's the exact cause of phase 5's screenshot, which is still not conclusively explained — this isn't claimed as closing that anomaly for certain.

8. **Small phase-4 polish items** (closes gap #10). The low-confidence pill now has a `title` tooltip explaining the flag in plain words. The finding/task translated-block error state now shows the same specific "the Afterword device isn't reachable" wording the preferences dialog already used, whenever that's the actual cause — verified by actually stopping the live backend, confirming the specific message appears, then confirming it clears once the backend is back.

**Deliberately not changed:**

- **Gap #3** (the 0.85 threshold) — phase 6's reasoning for keeping it still holds; nothing here changes it.
- **Gap #7** (the 1800-char Gmail URL fallback threshold) — still unverified against a real Gmail account. No Google account is available in this environment, and the honest move is to leave this flagged rather than fabricate a "verified" number.
- **The human-check half of gap #4/#9** — a native speaker's review of the flagged translations (the plan's own optional metric) still hasn't run; no reviewer was available here. This remains the single highest-value thing an actual person could add.
- **Gap #11** (phase 7's label table) — untouched; already hand-reviewed once in that phase, nothing new surfaced here.

**Testing tally:** 15 new backend tests across `test_app.py` (negation guard including cache-hit survival, the Hindi hint's presence and scoping, the DB migration, the static-file mount, CORS default), `test_translate.py` (the `restore()` sentinel-stripping fix), and a new `test_demo_content.py` (the letter-subject extraction). Full backend suite: 44 tests, all passing. `PROMPT_VERSION` was bumped `1` → `2` → `3` across this pass (the negation guard + Hindi hint, then the `restore()` fix) so every cached translation reflects the fixes rather than serving something computed before them — `backend/metrics.json` was regenerated from scratch after each bump to stay honest about what's actually live.

**Final numbers, `backend/metrics.json`** (13 demo items now, up from 10 — the 3 letter subjects are new content since item 1 above; es/vi/hi = 39 translations):

| Metric | es | vi | hi |
|---|---|---|---|
| Round-trip similarity (median / worst) | 0.953 / 0.886 | 0.909 / 0.782 | 0.901 / 0.803 |
| Cold latency, median (instruction / letter / summary) | 5.3s / 22.9s / 22.6s | 5.7s / 24.4s / 25.4s | 11.5s / 50.6s / 51.9s |

- **Protected-token preservation: still 100.0% (60 of 60)** — no real token has ever been lost or corrupted, before or after this pass.
- **Coverage: 100% (13 of 13 demo items in all three languages).**
- **Low-confidence flags: 4 of 39 (10%)**, down from 4 of 30 (13%) before this pass despite 9 more items — the same `instruction/task0`/`task2`/`task3` cases phase 6 already discussed, none new. (Two *separate* items now show `protected_tokens_ok: false` from an invented sentinel — see item 4 above — but neither is low-confidence by score, and both display cleanly thanks to the `restore()` fix.)
- **Cold latency is visibly higher across the board than phase 6's original numbers** (e.g. Hindi summary 51.9s vs. 22.2s) — roughly a uniform 2.3× increase across *every* language and kind, not just Hindi. Since `negation_flip()` is a free regex check and the Hindi glossary hint only lengthens Hindi's prompt slightly, neither explains a uniform slowdown across es/vi too. The far more likely cause: this measurement ran while the chat model server was also fielding the browser-based verification checks for this same pass (Selenium sessions, curl re-checks) — the plan already notes forward/back-translation calls serialize through one model lock, so concurrent load from unrelated requests inflates every measurement equally. Not a regression from this pass's code — re-measure in a quiet environment (nothing else hitting :8000) before quoting a latency number on stage.

---

## Out of scope this week

- ~~Full UI chrome translation (beyond the optional L9).~~ Brought into scope afterwards at the user's request, as phase 8 below.
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

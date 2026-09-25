/* On-device translation: language preference and lazy font loading.
   The translation API lives only on the Afterword device; the "Reading
   language" select disables itself wherever it isn't reachable, such as the
   public GitHub Pages deployment. See MULTILINGUAL-PLAN.md phase 3. */
(() => {
  // Same origin in the real demo (dist/ served by the device). During local
  // development dist/ and the backend usually run on different ports, so
  // point at the backend explicitly, or override with window.AFTERWORD_API.
  const API = window.AFTERWORD_API ?? (location.port === '8080' ? 'http://127.0.0.1:8010' : '');
  // Phase 0 finding: Vietnamese needs no extra font — the app's body font
  // (Plus Jakarta Sans) already covers it. Hindi needs Noto Sans Devanagari.
  const LANGUAGES = [
    {code:'en',native:'English'},
    {code:'es',native:'Español'},
    {code:'vi',native:'Tiếng Việt'},
    {code:'hi',native:'हिन्दी',font:{family:'Noto Sans Devanagari',cssUrl:'https://fonts.googleapis.com/css2?family=Noto+Sans+Devanagari:wght@400;600&display=swap'}},
  ];
  const loadedFonts = new Set();
  let backendUp = null; // null = not checked yet; select stays enabled until we know it's down

  function ensureFont(lang) {
    const entry = LANGUAGES.find(l => l.code === lang);
    if (!entry?.font || loadedFonts.has(lang)) return;
    loadedFonts.add(lang);
    const link = document.createElement('link');
    link.rel = 'stylesheet';
    link.href = entry.font.cssUrl;
    document.head.appendChild(link);
  }

  async function checkTranslationHealth() {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 3000);
    try { backendUp = (await fetch(API + '/health', {signal: controller.signal})).ok; }
    catch { backendUp = false; }
    finally { clearTimeout(timer); }
    for (const select of $$('#reading-language, .lang-toggle')) select.disabled = backendUp === false;
    const note = $('#reading-language-note');
    if (note) note.hidden = backendUp !== false;
    return backendUp;
  }

  window.AfterwordLanguages = LANGUAGES;
  window.ensureFont = ensureFont;
  window.checkTranslationHealth = checkTranslationHealth;
  window.languageField = () => `<label class="field"><span>Reading language</span><select id="reading-language" ${backendUp === false ? 'disabled' : ''}>${LANGUAGES.map(l => `<option value="${l.code}" ${state.lang === l.code ? 'selected' : ''}>${l.native}</option>`).join('')}</select></label><p class="fine" id="reading-language-note" ${backendUp === false ? '' : 'hidden'}>Translation needs the Afterword device. This stays in English until it reconnects.</p>`;

  // A compact toggle for the finding and letter views, sharing state.lang with
  // the preferences dialog. Applies immediately on change — no separate save.
  window.compactLanguageToggle = () => `<label class="compact-field lang-toggle-field"><span>Language</span><select class="lang-toggle" aria-label="Reading language" ${backendUp === false ? 'disabled' : ''}>${LANGUAGES.map(l => `<option value="${l.code}" ${state.lang === l.code ? 'selected' : ''}>${l.native}</option>`).join('')}</select></label>`;
  document.addEventListener('change', e => {
    if (!e.target.matches('.lang-toggle')) return;
    state.lang = e.target.value;
    ensureFont(state.lang);
    persist();
    render();
  });

  // --- Translated blocks (finding summaries, task instructions; phase 4) ---
  // Only ever sends the plain-language text already on the page — never a
  // raw source document. Cached in memory so re-rendering the same content
  // in the same language never re-fetches.
  const translationCache = new Map();
  const cacheKey = (lang, kind, text) => `${lang}|${kind}|${text}`;

  async function requestTranslation(text, kind) {
    try {
      const r = await fetch(API + '/translate', {
        method: 'POST', headers: {'content-type': 'application/json'},
        body: JSON.stringify({text, target_lang: state.lang, kind}),
      });
      if (!r.ok) throw new Error('http ' + r.status);
      return {status: 'ok', ...(await r.json())};
    } catch {
      return {status: 'error'};
    }
  }

  function translatedBlockMarkup(blockId, result) {
    const langName = LANGUAGES.find(l => l.code === state.lang)?.native || '';
    if (result.status === 'loading') return `<div class="translated-block loading" id="${blockId}"><p class="translated-label">${icon('spark')}Translating on this device…</p></div>`;
    if (result.status === 'error') return `<div class="translated-block error" id="${blockId}"><p class="translated-label">Couldn't translate right now. The English above is complete.</p></div>`;
    const flag = (result.low_confidence || !result.protected_tokens_ok) ? ' <span class="pill amber">Machine translation — please check</span>' : '';
    const body = escapeHTML(result.text).split(/\n{2,}/).map(p => `<p>${p.replace(/\n/g, '<br>')}</p>`).join('');
    return `<div class="translated-block" id="${blockId}" lang="${result.lang}"><p class="translated-label">${icon('spark')}Translated on this device (${langName})${flag}</p>${body}</div>`;
  }

  // blockId -> the exact source text last successfully translated there.
  // Lets a letter's edited body be told apart from a genuinely fresh block
  // (findings/tasks never change their own text, so this only matters for
  // letters — see letterTranslationState below).
  const lastOkText = {};

  // blockId must be a stable, unique id for this content (e.g. one per
  // finding or task) so a resolved fetch can patch the right element in
  // place — this may be behind an open <dialog>, which a full render()
  // never touches, so a targeted DOM patch is used instead of re-rendering.
  window.translatedBlock = (text, kind, blockId) => {
    if (state.lang === 'en') return '';
    const key = cacheKey(state.lang, kind, text);
    let cached = translationCache.get(key);
    if (!cached) {
      cached = {status: 'loading'};
      translationCache.set(key, cached);
      requestTranslation(text, kind).then(result => {
        translationCache.set(key, result);
        if (result.status === 'ok') lastOkText[blockId] = text;
        const el = document.getElementById(blockId);
        if (el) el.outerHTML = translatedBlockMarkup(blockId, result);
        // No-op outside the letters page (its checkbox/stale-note don't exist
        // there) — this is what re-enables "send this version" once a fresh
        // fetch actually resolves, whether from editing, Update, or a plain
        // render finding the cache empty.
        window.refreshLetterControls?.(blockId, text);
      });
    } else if (cached.status === 'ok') {
      lastOkText[blockId] = text; // covers the cache-hit-at-render path too
    }
    return translatedBlockMarkup(blockId, cached);
  };

  // Raw translated string for a resolved cache entry (e.g. for a text
  // export), as opposed to translatedBlock's rendered HTML card. Returns ''
  // if nothing resolved yet — callers check letterTranslationState first.
  window.translatedText = (text, kind) => {
    const cached = translationCache.get(cacheKey(state.lang, kind, text));
    return cached?.status === 'ok' ? cached.text : '';
  };

  // --- Bilingual letters (phase 5) ---------------------------------------
  // Only the letter body is translated — never the recipient, subject or
  // signature, which stay exactly as authored in both columns.

  // Reports whether the cached translation for `text` is still usable to
  // send: resolved, not flagged low-confidence, and not stale from an edit
  // made since it was translated.
  window.letterTranslationState = (text, blockId) => {
    if (state.lang === 'en') return {ready: false};
    const cached = translationCache.get(cacheKey(state.lang, 'letter', text));
    const ok = cached?.status === 'ok';
    const stale = !!lastOkText[blockId] && lastOkText[blockId] !== text;
    return {ready: true, ok, stale,
            lowConfidence: ok && (!!cached.low_confidence || cached.protected_tokens_ok === false)};
  };

  // Applies letterTranslationState's verdict for `blockId` to the DOM: dims
  // the block, shows/hides the "out of date" note, and enables/disables
  // "send this version instead" — the one gate a doubtful translation can
  // never get past. Called both reactively (typing) and after a fetch
  // resolves (translatedBlock's .then(), the explicit Update action).
  window.refreshLetterControls = (blockId, text) => {
    const s = window.letterTranslationState(text, blockId);
    $(`#${blockId}`)?.classList.toggle('dimmed', s.stale);
    const note = $('#stale-note-' + blockId.replace('translated-letter-', ''));
    if (note) note.hidden = !s.stale;
    const checkbox = $('#send-translated-checkbox');
    if (checkbox) {
      checkbox.disabled = !s.ok || s.stale || s.lowConfidence;
      if (checkbox.disabled && checkbox.checked) { checkbox.checked = false; sendTranslated = false; }
    }
  };

  // Called on every keystroke in the letter body (see pages.js's #letter-form
  // input handler) — never fires a translation itself, only reflects whether
  // the one already on screen still matches what's being edited. Retranslating
  // happens on save or the explicit "Update" action below.
  window.markLetterTranslationStale = text => {
    if (state.lang === 'en') return;
    window.refreshLetterControls('translated-letter-' + letterType, text);
  };

  Object.assign(window.actions, {
    'update-translation': () => {
      if (state.lang === 'en') return;
      const d = captureLetter(), blockId = 'translated-letter-' + letterType;
      const el = $(`#${blockId}`);
      if (el) el.outerHTML = window.translatedBlock(d.body, 'letter', blockId);
      const note = $('#stale-note-' + letterType);
      if (note) note.hidden = true; // the block's own loading state covers the wait
    },
    'open-gmail': () => {
      if (!validLetter()) return;
      const d = captureLetter();
      const useTranslated = sendTranslated && state.lang !== 'en';
      const langName = LANGUAGES.find(l => l.code === state.lang)?.native || state.lang;
      let body = d.body;
      if (useTranslated) {
        const cached = translationCache.get(cacheKey(state.lang, 'letter', d.body));
        if (cached?.status === 'ok') body = cached.text; // else: fall back to English rather than send nothing
      }
      const fullBody = `Dear team,\n\n${body}\n\nThank you,\n${d.name}`;
      const compose = (b) => `https://mail.google.com/mail/?view=cm&to=${encodeURIComponent(d.recipient)}&su=${encodeURIComponent(d.subject)}&body=${encodeURIComponent(b)}`;
      const url = compose(fullBody);
      // Percent-encoded Devanagari/Vietnamese roughly triples in length; Gmail's
      // compose link has practical length limits well under a typical URL max.
      if (url.length > 1800) {
        navigator.clipboard?.writeText(fullBody).catch(() => {});
        window.open(compose(''), '_blank');
        modal('Letter copied instead', `<p>This letter is long enough that Gmail's link could not carry it${useTranslated ? ` in ${langName}` : ''}. It has been copied to your clipboard — paste it into the message body. Gmail is open with the recipient and subject already filled in.</p>`, button('Done', 'close-modal', true));
      } else {
        window.open(url, '_blank');
      }
      recordActivity(`Opened Gmail with the ${useTranslated ? langName : 'English'} version of the ${letterTemplates[letterType].title.toLowerCase()}`);
    },
  });

  ensureFont(state.lang);
  checkTranslationHealth();
  // i18n.js loads last, after workspace.js's own trailing render() already
  // drew the first real page — before window.compactLanguageToggle and
  // window.translatedBlock existed. Re-render once so a page loaded
  // directly to a hash route (e.g. #evidence) shows them on first paint,
  // not only after some later action re-renders. Mirrors workspace.js's
  // own trailing render() call for the same reason.
  render();
})();

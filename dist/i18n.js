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
  // Phase 7 (L9, stretch): the 12 highest-traffic chrome strings — the 9 nav
  // page headings plus the 3 letter-page action buttons — pre-translated
  // once through POST /translate (kind: instruction) and reviewed by hand,
  // not translated live. Unlike translatedBlock, this never depends on the
  // backend being reachable, so it works even when /health is down.
  //
  // The hand review mattered: on these short, context-free strings the
  // round-trip check was noisier and the model's error rate was higher than
  // on full sentences (phase 6 saw 4/30 flags on real content; here 9 of 36
  // needed a manual fix). Two failure modes not seen on longer text:
  // - The model twice invented ⟦Tn⟧ sentinels into the output even though
  //   the input had nothing to protect (es/vi "Action plan"), the same
  //   invented-sentinel risk phase 0 flagged, just never seen on real
  //   content since the demo's actual text always contains real tokens.
  // - Flat wrong-word or garbled-transliteration errors round-trip cosine
  //   didn't catch at all: Hindi "Privacy" came back as "गुप्तचरता"
  //   (espionage, not privacy), "Activity" as the grammar term for "verb"
  //   rather than "activity", and "Gmail"/"draft" came back with garbled
  //   spelling that a native reader would need to guess at. Vietnamese
  //   "Letters" came back as "Thông báo" (notice/announcement), not
  //   correspondence. All corrected by hand below; the raw model output is
  //   in backend/dev/labels_raw.json for anyone re-reviewing this later.
  const UI_LABELS = {
    es: {
      'Overview': 'Resumen', 'Action plan': 'Plan de acción', 'Documents': 'Documentos',
      'Evidence review': 'Revisión de la evidencia', 'Letters': 'Cartas', 'Memories': 'Recuerdos',
      'Privacy': 'Privacidad', 'Activity': 'Actividad', 'Settings': 'Ajustes',
      'Save draft': 'Guardar borrador', 'Print letter': 'Imprimir la carta', 'Open in Gmail': 'Abrir en Gmail',
    },
    vi: {
      'Overview': 'Tổng quan', 'Action plan': 'Kế hoạch hành động', 'Documents': 'Các văn bản',
      'Evidence review': 'Kiểm tra bằng chứng', 'Letters': 'Thư từ', 'Memories': 'Những kỷ niệm',
      'Privacy': 'Quyền riêng tư', 'Activity': 'Hoạt động', 'Settings': 'Cài đặt',
      'Save draft': 'Lưu bản nháp', 'Print letter': 'In thư', 'Open in Gmail': 'Mở trong Gmail',
    },
    hi: {
      'Overview': 'सारांश', 'Action plan': 'कार्य योजना', 'Documents': 'दस्तावेज़',
      'Evidence review': 'साक्ष्य की जांच', 'Letters': 'पत्र', 'Memories': 'यादें',
      'Privacy': 'गोपनीयता', 'Activity': 'गतिविधि', 'Settings': 'सेटिंग्स',
      'Save draft': 'ड्राफ्ट सहेजें', 'Print letter': 'पत्र छापें', 'Open in Gmail': 'जीमेल में खोलें',
    },
  };
  // Falls back to the English string itself, so every call site is safe to
  // use unconditionally, in English and for any label outside this table.
  window.uiLabel = text => (window.AFTERWORD_I18N_CRAWL ? text : UI_LABELS[state.lang]?.[text] || text);

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
    if (result.status === 'error') {
      // Matches the preferences dialog's specific "needs the Afterword
      // device" wording when that's the actual cause, instead of a generic
      // message that doesn't tell the family whether trying again might help.
      const message = backendUp === false
        ? "The Afterword device isn't reachable right now. The English above is complete."
        : "Couldn't translate right now. The English above is complete.";
      return `<div class="translated-block error" id="${blockId}"><p class="translated-label">${message}</p></div>`;
    }
    const flagTitle = 'The back-translation (translating this back into English) differed enough from the original that this translation might not be fully accurate. The English above is always what is correct and what gets sent.';
    const flag = (result.low_confidence || !result.protected_tokens_ok) ? ` <span class="pill amber" title="${flagTitle}">Machine translation — please check</span>` : '';
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

  // A lighter-weight sibling to translatedBlock for a single line of chrome
  // that already sits inside a labelled card (the letter subject, next to
  // the body's own "Translated on this device" label) — no loading/error
  // card of its own, it just shows the English text until a translation
  // resolves, then swaps in place. Shares translatedBlock's cache, so if the
  // subject happens to match some other already-translated instruction the
  // result is instant. Gap-resolution note: earlier this was left English on
  // both sides because splitting one combined subject+body translation back
  // into two fields proved fragile — this sidesteps that entirely by never
  // combining them, two small independent requests instead of one fragile one.
  window.translatedInline = (text, kind, blockId) => {
    if (state.lang === 'en') return escapeHTML(text);
    const key = cacheKey(state.lang, kind, text);
    let cached = translationCache.get(key);
    if (!cached) {
      cached = {status: 'loading'};
      translationCache.set(key, cached);
      requestTranslation(text, kind).then(result => {
        translationCache.set(key, result);
        const el = document.getElementById(blockId);
        if (el && result.status === 'ok') el.textContent = result.text;
      });
    }
    return cached.status === 'ok' ? escapeHTML(cached.text) : escapeHTML(text);
  };

  // --- Bilingual letters (phase 5) ---------------------------------------
  // The recipient and signature stay exactly as authored in both columns —
  // only the body (via translatedBlock) and, for reading only, the subject
  // (via translatedInline above) are translated. Whichever version gets
  // sent, the subject line is always English: it's short administrative
  // text the provider needs verbatim, and translating it was never about
  // what gets sent, only about what the family can read to follow along.

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
  //
  // translatedBlock calls this after ANY block resolves, not just a letter's
  // — a finding or task instruction finishing its translation in the
  // background while the user has since moved to (or switched templates on)
  // the letters page used to reach this function too. #send-translated-checkbox
  // and #stale-note-* are singletons scoped to whichever letter is currently
  // on screen, so acting on them for an unrelated blockId would silently
  // apply a stranger's translation state to the visible letter — flip the
  // checkbox, or its disabled state, based on content the family isn't even
  // looking at. This guard is the fix for that: only the block that actually
  // belongs to the open letter may touch them. (Best working theory for
  // phase 5's one unreproduced "stale note showing during a first-ever
  // translation" screenshot — that anomaly was never pinned down for
  // certain, but this is a real, independently confirmed way for these
  // singletons to end up reflecting the wrong letter's state.)
  window.refreshLetterControls = (blockId, text) => {
    if (blockId !== 'translated-letter-' + letterType) return;
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

  // --- Whole-page translation (phase 8) --------------------------------------
  // Every other English string on screen is swapped for its entry in the
  // static dictionary (dist/ui-strings.js, generated and reviewed by
  // backend/dev/gen_ui_strings.py). No network call, so it keeps working when
  // the backend is down; a string with no entry simply stays English.
  // English on purpose, and marked lang="en" so a screen reader switches
  // voice for them while the rest of the page reads in the chosen language.
  const KEEP_ENGLISH = [
    '.record-paper', // source documents are evidence: always verbatim
    '.memory-reading', '.memory-quote', '.quiet-archive-intro blockquote', // the family's own words
    '.letter-read', '.letter-salutation', '.letter-date', // the English letter that gets sent
    '.finding-lead', '.evidence-fact p', // translated just below, with a confidence flag
    '.user-question', // the family's own typed question, echoed back
  ];
  // Task instructions sit right above their own flagged translation. Only
  // added where :has() is supported: one unknown selector makes closest()
  // throw for the whole list, which would stop translation everywhere.
  if (window.CSS?.supports?.('selector(:has(*))')) KEEP_ENGLISH.push('.subtle-box:has(+ .translated-block)');
  const UI_SKIP_SELECTOR = [...KEEP_ENGLISH,
    '.translated-block > :not(.translated-label)', '[id$="-subject"]', // already translations
    '.lang-toggle', '#reading-language', // each language name stays in its own language
    '.doc-title small', '.staged-row strong', // file names
    '.brand', '.avatar', '.demo-label', '.letter-monogram', '.footnote > span:first-child',
    'kbd', 'code', 'script', 'style', 'textarea',
  ].join(',');
  const MARK_ENGLISH_SELECTOR = [...KEEP_ENGLISH, '#letter-form input', '#letter-form textarea'].join(',');
  const UI_ATTRS = ['placeholder', 'aria-label', 'title'];
  const hasLetter = s => /\p{L}/u.test(s);
  // Dictionary keys: runs of spaces collapsed, line breaks kept as \n.
  const normalize = s => s.replace(/[ \t\r\f\v]+/g, ' ').replace(/ ?\n ?/g, '\n').trim();
  const INLINE_TAGS = new Set(['BR', 'B', 'STRONG', 'EM', 'I']);
  const doneText = new WeakSet();
  const doneUnits = new WeakSet();
  const doneAttrs = new WeakMap();
  const uiMisses = new Set();
  window.uiTranslationMisses = () => [...uiMisses];

  // A sentence broken up only by <br> or bold/italic ("Progress can
  // be<br>one small step.", "<strong>2</strong> of 7 actions complete") is
  // translated as one unit: piece by piece the grammar falls apart, worst of
  // all in Hindi's word order. Returns its text with <br> as \n, or null if
  // the element holds anything richer.
  function inlineUnitText(el) {
    if (!el || doneUnits.has(el)) return null;
    let mixed = false;
    for (const child of el.childNodes) {
      if (child.nodeType === Node.TEXT_NODE) continue;
      if (child.nodeType !== Node.ELEMENT_NODE || !INLINE_TAGS.has(child.tagName) || child.children.length) return null;
      mixed = true;
    }
    return mixed ? [...el.childNodes].map(n => (n.nodeName === 'BR' ? '\n' : n.textContent)).join('') : null;
  }

  function visitText(node, visit) {
    if (doneText.has(node)) return;
    const parent = node.parentElement;
    if (!parent || parent.closest(UI_SKIP_SELECTOR)) return;
    const unit = INLINE_TAGS.has(parent.tagName) ? parent.parentElement : parent;
    const unitText = inlineUnitText(unit);
    if (unitText !== null) {
      const key = normalize(unitText);
      if (!hasLetter(key)) return;
      return visit(key, translated => {
        // Bold is dropped (the translation has no markup to put it back on);
        // line breaks survive when the model kept them.
        doneUnits.add(unit);
        unit.replaceChildren(...translated.split('\n').flatMap((line, i) => (i ? [document.createElement('br'), line] : [line])));
        for (const child of unit.childNodes) if (child.nodeType === Node.TEXT_NODE) doneText.add(child);
      });
    }
    const raw = node.nodeValue.trim();
    const key = normalize(raw);
    if (!key || !hasLetter(key)) return;
    visit(key, translated => {
      // An <option> with no value attribute submits its label; pin the
      // English there so filters that compare against it keep matching.
      if (parent.tagName === 'OPTION' && !parent.hasAttribute('value')) parent.value = raw;
      node.nodeValue = node.nodeValue.replace(raw, () => translated);
      doneText.add(node);
    });
  }

  // Shared by the runtime translator and the dev crawler below, so the two
  // can never disagree about what counts as translatable.
  function forEachUiString(root, visit) {
    if (root.nodeType === Node.TEXT_NODE) return visitText(root, visit);
    if (root.nodeType !== Node.ELEMENT_NODE || root.closest(UI_SKIP_SELECTOR)) return;
    // Collected up front: translating an inline unit replaces its text nodes,
    // and a TreeWalker stops dead when its current node leaves the document.
    const nodes = [];
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    for (let node = walker.nextNode(); node; node = walker.nextNode()) nodes.push(node);
    for (const node of nodes) visitText(node, visit);
    for (const el of [root, ...root.querySelectorAll('[placeholder],[aria-label],[title]')]) {
      if (el.closest(UI_SKIP_SELECTOR)) continue;
      const done = doneAttrs.get(el) || new Set();
      for (const attr of UI_ATTRS) {
        const value = normalize(el.getAttribute(attr) || '');
        if (!value || !hasLetter(value) || done.has(attr)) continue;
        visit(value, translated => { el.setAttribute(attr, translated); done.add(attr); doneAttrs.set(el, done); });
      }
    }
  }

  // Text that is already a translation (a UI_LABELS nav label, a node an
  // earlier pass translated) isn't a miss.
  const knownTranslations = new WeakMap();
  function isTranslation(dict, text) {
    let values = knownTranslations.get(dict);
    if (!values) knownTranslations.set(dict, values = new Set([...Object.values(dict), ...Object.values(UI_LABELS[state.lang] || {})]));
    return values.has(text);
  }

  function translateUi(root) {
    if (state.lang === 'en' || window.AFTERWORD_I18N_CRAWL) return;
    const dict = window.AFTERWORD_UI_STRINGS?.[state.lang];
    if (!dict) return;
    forEachUiString(root, (text, apply) => {
      const translated = AfterwordUiTranslate.lookup(dict, text);
      if (translated) apply(translated);
      else if (!isTranslation(dict, text)) uiMisses.add(text);
    });
    if (root.nodeType === Node.ELEMENT_NODE) {
      for (const el of [root, ...root.querySelectorAll(MARK_ENGLISH_SELECTOR)]) {
        if (el.matches(MARK_ENGLISH_SELECTOR)) el.lang = 'en';
      }
    }
  }

  // The whole page now reads in the chosen language, so <html lang> follows
  // it (phase 3 kept it English while translations were islands on an
  // English page); what stays English is marked lang="en" in translateUi.
  function syncPageLanguage() {
    const translating = state.lang !== 'en' && !window.AFTERWORD_I18N_CRAWL && !!window.AFTERWORD_UI_STRINGS?.[state.lang];
    document.documentElement.lang = translating ? state.lang : 'en';
    document.documentElement.dataset.readingLang = state.lang;
    if (!translating) return;
    const [name, ...rest] = document.title.split(' — ');
    const translated = AfterwordUiTranslate.lookup(window.AFTERWORD_UI_STRINGS[state.lang], name);
    if (translated) document.title = [translated, ...rest].join(' — ');
  }

  // Dev-only: backend/dev/crawl_ui_strings.py calls this on every page and
  // dialog to build the dictionary's source list.
  window.collectUiStrings = () => {
    const found = new Set();
    for (const id of ['app', 'detail-dialog', 'toast']) {
      const root = document.getElementById(id);
      if (root) forEachUiString(root, text => found.add(text));
    }
    return [...found];
  };

  // render(), modal(), toasts and the targeted DOM patches all insert nodes,
  // so one observer catches every path. It only watches childList: the
  // translator's own edits (text values, attributes) never re-trigger it.
  new MutationObserver(records => {
    syncPageLanguage();
    for (const record of records) for (const node of record.addedNodes) translateUi(node);
  }).observe(document.body, {childList: true, subtree: true});
  syncPageLanguage();

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

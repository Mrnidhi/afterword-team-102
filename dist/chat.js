/* Afterword chat: the Overview's intake. Paste text, paste screenshots, drop or attach files.
   Each item goes to the local service only (same origin): files to /ingest/extract (parsing and
   OCR on this device), pasted text to /extract. The fine-tuned model's findings come back as
   ranked cards, and one refresh updates Documents, Evidence, the Plan and Memories. */
(() => {
  'use strict';
  const C = window.FindingsCore, esc = escapeHTML;
  const ACCEPT = '.txt,.md,.eml,.mbox,.csv,.xml,.pdf,.png,.jpg,.jpeg,.webp,.tif,.tiff';
  const MAX_BYTES = 10 * 1024 * 1024;   // backend MAX_UPLOAD_BYTES
  const MAX_FILES = 20;
  const store = {
    get(key) { try { return localStorage.getItem(key); } catch { return null; } },
    set(key, value) { try { value ? localStorage.setItem(key, value) : localStorage.removeItem(key); } catch {} },
  };
  let draft = '', files = [], busy = false, dod = store.get('afterword-chat-dod') || '';
  const turns = [];   // {role:'user', text, names} | {role:'ai', status, results, errors, progress, ms}

  const bridge = () => window.AfterwordFindings;
  const ready = () => Boolean(bridge()?.active?.());
  const money = value => '$' + Number(value).toLocaleString('en-US', {minimumFractionDigits: 2, maximumFractionDigits: 2});
  const evidenceHref = id => '#evidence?finding=' + encodeURIComponent(id);
  const plural = (n, word) => `${n} ${word}${n === 1 ? '' : 's'}`;

  // ---- cards ------------------------------------------------------------------------------

  function deadlineText(f) {
    const dates = [f.deadline_date, f.next_date].filter(d => typeof d === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(d)).sort();
    if (!dates.length) return Number.isSafeInteger(f.due) ? `Within ${f.due} days` : '';
    const tags = Array.isArray(f.tags) ? f.tags : [];
    return dates[0] + (tags.includes('overdue') ? ' · overdue' : tags.includes('deadline_soon') ? ' · soon' : '');
  }

  function linksHTML(f) {
    const links = C.contactLinks(f);
    if (!links.length) return '';
    const label = {url: 'Website', email: 'Email', phone: 'Call'};
    return `<div class="chat-card-links">${links.map(link => `<a href="${esc(link.href)}" ${link.kind === 'url' ? 'target="_blank" rel="noopener noreferrer"' : ''}><span>${label[link.kind]}</span>${esc(link.label)}</a>`).join('')}</div>`;
  }

  function actionCard(row, index) {
    const f = row.finding || {}, p = C.priorityPresentation(row), status = C.statusPresentation(row);
    const ref = typeof f.ref === 'string' && f.ref ? ' · ref …' + esc(f.ref.slice(-4)) : '';
    const printed = C.numberValue(f.amt), stake = C.numberValue(f.money_at_stake);
    const rec = typeof f.rec === 'string' && f.rec !== 'none' ? ' ' + esc(f.rec) : '';
    const when = deadlineText(f);
    const facts = [
      printed !== null ? `<div><dt>Printed</dt><dd>${money(printed)}${rec}</dd></div>` : '',
      stake ? `<div><dt>At stake</dt><dd class="chat-stake">${money(stake)}</dd></div>` : '',
      when ? `<div><dt>When</dt><dd>${esc(when)}</dd></div>` : '',
    ].join('');
    const tags = p.tags.filter(t => !['deadline', 'memory', 'ignore'].includes(t.tag));
    return `<article class="chat-card chat-pluck ${p.tier ? 'chat-tier-' + esc(p.tier) : ''}" style="--i:${index}">
      <header>${p.tier ? `<span class="finding-tier finding-tier-${esc(p.tier)}">${esc(p.tier)}${p.score !== null ? ' · ' + esc(String(p.score)) : ''}</span>` : ''}<span class="chat-card-cat">${esc(C.categoryLabel(f.cat))}</span><span class="finding-badge finding-${esc(status.status || 'invalid')}">${esc(status.label)}</span></header>
      <h3>${esc(C.actionLabel(f.act))}</h3>
      <p class="chat-card-inst">${esc(typeof f.inst === 'string' && f.inst ? f.inst : C.recordTitle(row))}${ref}</p>
      ${facts ? `<dl class="chat-card-facts">${facts}</dl>` : ''}
      ${linksHTML(f)}
      ${tags.length ? `<div class="finding-priority">${tags.map(t => `<span class="finding-tag">${esc(t.label)}</span>`).join('')}</div>` : ''}
      ${p.reasons.length ? `<details class="chat-card-why"><summary>Why it is ranked here</summary><ul>${p.reasons.map(r => `<li>${esc(r)}</li>`).join('')}</ul></details>` : ''}
      <a class="text-link chat-card-open" href="${evidenceHref(row.id)}">Review the evidence ${icon('arrow')}</a>
    </article>`;
  }

  function quietCard(row, index) {
    const text = row.status === 'failed'
      ? ['Could not read', C.reviewPresentation(row).reasons[0] || 'The model could not process this record.', 'chat-quiet-failed']
      : row.route === 'memory' ? ['Kept in Memories', 'A personal record. It is saved with the family’s memories.', 'chat-quiet-memory']
      : ['Not relevant', 'Nothing to act on. It stays in Documents, hidden from the plan.', 'chat-quiet-drop'];
    return `<article class="chat-card chat-quiet ${text[2]} chat-pluck" style="--i:${index}"><header><span class="chat-card-cat">${esc(text[0])}</span></header><p>${esc(text[1])}</p><a class="text-link chat-card-open" href="${evidenceHref(row.id)}">Open the record ${icon('arrow')}</a></article>`;
  }

  function orderResults(results) {
    const valid = results.filter(r => r && typeof r === 'object');
    const rank = r => r.status === 'failed' ? 3 : r.route === 'extract' ? 0 : r.route === 'memory' ? 1 : 2;
    const actions = C.sortFindings(valid.filter(r => rank(r) === 0));
    return [...actions, ...valid.filter(r => rank(r) !== 0).sort((a, b) => rank(a) - rank(b))];
  }

  function summary(turn) {
    const r = turn.results, actions = r.filter(x => x.route === 'extract' && x.status !== 'failed');
    const stake = actions.reduce((sum, x) => sum + (C.numberValue(x.finding?.money_at_stake) || 0), 0);
    const p1 = actions.filter(x => x.finding?.priority === 'P1').length;
    const parts = [plural(r.length, 'record') + ' read' + (turn.ms ? ` in ${(turn.ms / 1000).toFixed(1)} s` : ''),
      plural(actions.length, 'action') + (p1 ? ` (${p1} urgent)` : ''),
      r.filter(x => x.route === 'memory').length ? plural(r.filter(x => x.route === 'memory').length, 'memory').replace('memorys', 'memories') : '',
      r.filter(x => x.route === 'drop' && x.status !== 'failed').length ? r.filter(x => x.route === 'drop' && x.status !== 'failed').length + ' not relevant' : '',
      stake ? money(stake) + ' at stake' : ''].filter(Boolean);
    return parts.join(' · ');
  }

  // ---- conversation -----------------------------------------------------------------------

  function turnHTML(turn) {
    if (turn.role === 'user') {
      const text = turn.text ? `<p>${esc(turn.text.length > 600 ? turn.text.slice(0, 600) + '…' : turn.text)}</p>` : '';
      const names = turn.names.length ? `<ul class="chat-attached">${turn.names.map(n => `<li>${icon('files')}${esc(n)}</li>`).join('')}</ul>` : '';
      return `<div class="chat-turn chat-user">${text}${names}</div>`;
    }
    if (turn.status === 'working') {
      return `<div class="chat-turn chat-ai" aria-busy="true"><p class="chat-working"><span class="chat-dots" aria-hidden="true"><i></i><i></i><i></i></span>${esc(turn.progress || 'Reading…')}</p>${turn.results.length ? `<div class="chat-cards">${orderResults(turn.results).map((r, i) => r.route === 'extract' && r.status !== 'failed' ? actionCard(r, i) : quietCard(r, i)).join('')}</div>` : ''}</div>`;
    }
    const ordered = orderResults(turn.results);
    const errors = turn.errors.length ? `<ul class="chat-errors">${turn.errors.map(e => `<li>${esc(e)}</li>`).join('')}</ul>` : '';
    const lead = turn.note ? `<p>${esc(turn.note)}</p>` : ordered.length ? `<p class="chat-summary">${esc(summary(turn))}</p>` : '';
    return `<div class="chat-turn chat-ai">${lead}${ordered.length ? `<div class="chat-cards">${ordered.map((r, i) => r.route === 'extract' && r.status !== 'failed' ? actionCard(r, i) : quietCard(r, i)).join('')}</div>` : ''}${errors}</div>`;
  }

  function logHTML() {
    if (!turns.length) {
      return `<div class="chat-empty"><p>Nothing sent yet. Try pasting a bill, a bank letter or a text from a provider.</p></div>`;
    }
    return turns.map(turnHTML).join('');
  }

  function chipsHTML() {
    return files.map((file, i) => `<span class="chat-chip">${icon('files')}${esc(file.name)}<small>${Math.max(1, Math.round(file.size / 1024))} KB</small><button type="button" data-action="chat-remove-file" data-index="${i}" aria-label="Remove ${esc(file.name)}">×</button></span>`).join('');
  }

  function rollupHTML() {
    const groups = C.categoryRollup(bridge()?.rows?.() || []);
    if (!groups.length) return '';
    return `<section class="chat-rollup" aria-labelledby="chat-rollup-title"><div class="section-title"><h2 id="chat-rollup-title">Ranked by category</h2><a class="text-link" href="#plan">Full plan ${icon('arrow')}</a></div>
      <div class="chat-rollup-grid">${groups.map(g => `<article><header><strong>${esc(g.label)}</strong><span>${plural(g.items.length, 'action')}${g.atStake ? ' · ' + money(g.atStake) : ''}</span></header><ol>${g.leads.slice(0, 3).map(({row: r, related}) => { const p = C.priorityPresentation(r); return `<li><a href="${evidenceHref(r.id)}">${p.tier ? `<span class="finding-tier finding-tier-${esc(p.tier)}">${esc(p.tier)}</span>` : ''}${esc(C.actionLabel(r.finding?.act))} · ${esc(r.finding?.inst || C.recordTitle(r))}</a>${related.length ? ` <small class="chat-related">+${related.length} same account</small>` : ''}</li>`; }).join('')}</ol></article>`).join('')}</div></section>`;
  }

  function panel() {
    const h = bridge()?.health?.();
    const model = h?.model ? `${esc(h.model)} · on this device` : ready() ? 'on this device' : 'model not connected';
    return `<section id="chat-panel" class="chat-panel" aria-labelledby="chat-title">
      <div class="chat-head"><div><p class="chat-kicker">AFTERWORD ASSISTANT</p><h1 id="chat-title">Tell me what arrived.</h1><p class="chat-lead">Paste a letter, an email or a text message, or drop a PDF, a scan or a photo of a bill. The fine-tuned model on this machine reads it and turns it into ranked actions.</p></div><span class="chat-model ${ready() ? 'is-live' : ''}"><i></i>${model}</span></div>
      <div id="chat-log" class="chat-log" aria-live="polite">${logHTML()}</div>
      <div id="chat-drop" class="chat-composer">
        <div id="chat-chips" class="chat-chips">${chipsHTML()}</div>
        <label class="sr-only" for="chat-input">Text to read</label>
        <textarea id="chat-input" rows="6" placeholder="Paste text here, or drop files and screenshots onto this box…" ${busy ? 'disabled' : ''}>${esc(draft)}</textarea>
        <div class="chat-controls">
          <button type="button" class="button" data-action="chat-attach" ${busy ? 'disabled' : ''}>${icon('plus')}Attach files</button>
          <input type="file" id="chat-files" multiple accept="${ACCEPT}" hidden>
          <label class="chat-dod"><span>Date of death</span><input type="date" id="chat-dod" value="${esc(dod)}"></label>
          <span class="chat-hint">Ctrl / ⌘ + Enter</span>
          <button type="button" class="button primary chat-send" data-action="chat-send" ${busy ? 'disabled' : ''}>${busy ? 'Reading…' : 'Send'}${busy ? '' : icon('arrow')}</button>
        </div>
      </div>
      ${rollupHTML()}
    </section>`;
  }

  // Partial updates keep the textarea's caret and focus while the model works.
  function refreshLog() {
    const log = $('#chat-log');
    if (!log) return;
    log.innerHTML = logHTML();
    log.scrollTop = log.scrollHeight;
  }
  function refreshChips() { const el = $('#chat-chips'); if (el) el.innerHTML = chipsHTML(); }

  function addFiles(list) {
    const rejected = [];
    for (const file of Array.from(list || [])) {
      const ext = '.' + (file.name.split('.').pop() || '').toLowerCase();
      if (!ACCEPT.split(',').includes(ext)) rejected.push(`${file.name}: this file type can’t be read yet`);
      else if (file.size > MAX_BYTES) rejected.push(`${file.name}: larger than 10 MB`);
      else if (files.length >= MAX_FILES) rejected.push(`${file.name}: up to ${MAX_FILES} files at a time`);
      else if (!files.some(f => f.name === file.name && f.size === file.size)) files.push(file);
    }
    refreshChips();
    if (rejected.length) toast(rejected.join(' · '));
  }

  async function send() {
    if (busy) return;
    const input = $('#chat-input');
    if (input) draft = input.value;
    const text = draft.trim(), batch = files.slice();
    if (!text && !batch.length) { toast('Paste some text or attach a file first.'); return; }
    if (!ready()) {
      turns.push({role: 'ai', status: 'done', results: [], errors: [], note: 'The local model service isn’t connected, so nothing was sent. Start the Afterword service on this device and try again.'});
      refreshLog();
      return;
    }
    busy = true;
    turns.push({role: 'user', text, names: batch.map(f => f.name)});
    const ai = {role: 'ai', status: 'working', results: [], errors: [], progress: ''};
    turns.push(ai);
    draft = ''; files = [];
    render();
    const t0 = performance.now(), api = bridge().api;
    try {
      for (const file of batch) {
        ai.progress = `Reading ${file.name}…`; refreshLog();
        try {
          const body = {filename: file.name, content_base64: await bridge().encodeFile(file)};
          if (dod) body.reference_date = dod;
          const response = await api('/ingest/extract', {body, timeout: 240000});
          const results = Array.isArray(response.results) ? response.results : [];
          ai.results.push(...results);
          for (const e of Array.isArray(response.errors) ? response.errors : []) ai.errors.push(`${file.name}: ${typeof e === 'string' ? e : e?.message || 'part of this file could not be read'}`);
          if (!results.length && !(response.errors || []).length) ai.errors.push(`${file.name}: no readable text was found`);
        } catch (error) { ai.errors.push(`${file.name}: ${error.message}`); }
        refreshLog();
      }
      if (text) {
        ai.progress = 'Reading your text…'; refreshLog();
        try {
          const body = {id: C.chatDocumentId(), source: C.detectSource(text), text};
          if (dod) body.reference_date = dod;
          ai.results.push(await api('/extract', {body, timeout: 120000}));
        } catch (error) { ai.errors.push(`Your text: ${error.message}`); }
      }
    } finally {
      ai.status = 'done'; ai.ms = Math.round(performance.now() - t0); busy = false;
      await bridge().refresh();   // one refresh updates every view from the same stored findings
      render();
      refreshLog();
    }
  }

  // ---- events -----------------------------------------------------------------------------

  Object.assign(window.actions, {
    'chat-send': () => send(),
    'chat-attach': () => $('#chat-files')?.click(),
    'chat-remove-file': element => { files.splice(Number(element.dataset.index), 1); refreshChips(); },
  });
  document.addEventListener('input', event => {
    if (event.target.id === 'chat-input') draft = event.target.value;
    if (event.target.id === 'chat-dod') { dod = event.target.value; store.set('afterword-chat-dod', dod); }
  });
  document.addEventListener('change', event => {
    if (event.target.id === 'chat-files') { addFiles(event.target.files); event.target.value = ''; }
  });
  document.addEventListener('paste', event => {
    if (event.target.id !== 'chat-input') return;
    const pasted = Array.from(event.clipboardData?.files || []);
    if (pasted.length) { event.preventDefault(); addFiles(pasted.map((file, i) => file.name && file.name !== 'image.png' ? file : new File([file], `pasted-${Date.now()}-${i}.${(file.type.split('/')[1] || 'png').replace('jpeg', 'jpg')}`, {type: file.type}))); }
  });
  document.addEventListener('keydown', event => {
    if (event.target.id === 'chat-input' && event.key === 'Enter' && (event.metaKey || event.ctrlKey)) { event.preventDefault(); send(); }
  });
  for (const type of ['dragenter', 'dragover']) document.addEventListener(type, event => {
    const zone = event.target.closest?.('#chat-panel');
    if (!zone || !event.dataTransfer?.types?.includes('Files')) return;
    event.preventDefault(); zone.classList.add('is-dropping');
  });
  document.addEventListener('dragleave', event => { if (event.target.id === 'chat-panel') event.target.classList.remove('is-dropping'); });
  document.addEventListener('drop', event => {
    const zone = event.target.closest?.('#chat-panel');
    if (!zone) return;
    event.preventDefault(); zone.classList.remove('is-dropping');
    addFiles(event.dataTransfer?.files);
  });

  window.AfterwordChat = Object.freeze({panel});
})();

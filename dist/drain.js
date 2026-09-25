/* Daily drain counter. Every figure comes from GET /drain on the local service, or on the
   static site from data/drain_snapshot.json, which the same backend code generated.
   This file only formats; it never adds up charges. See docs/DRAIN-COUNTER.md. */
(() => {
  'use strict';
  const esc = escapeHTML;
  let data = null, mode = 'loading', failure = '', loadedKey = null, pendingKey = null, serviceSeen = false, snapshot = null, saving = false;

  class ServiceError extends Error {}
  const completedIds = () => [...state.completed].sort();
  const money = value => '$' + value.toLocaleString('en-US', {minimumFractionDigits: 2, maximumFractionDigits: 2});
  const wholeMoney = value => '$' + Math.round(value).toLocaleString('en-US');
  const longDate = iso => new Date(iso + 'T12:00:00').toLocaleDateString('en-US', {month: 'long', day: 'numeric'});
  const today = () => { const d = new Date(); return new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 10); };

  async function fetchService(ids) {
    const url = new URL('/drain', location.origin);
    if (ids.length) url.searchParams.set('done', ids.join(','));
    const response = await fetch(url, {headers: {Accept: 'application/json'}, credentials: 'same-origin', redirect: 'error'});
    // GitHub Pages and plain static servers answer 404 with HTML: no local service here.
    if (!(response.headers.get('content-type') || '').includes('application/json')) return null;
    const body = await response.json();
    if (!response.ok) throw new ServiceError(typeof body.detail === 'string' ? body.detail : 'The local service could not work out the charges.');
    return body;
  }

  async function fetchSnapshot(ids) {
    if (!snapshot) {
      const response = await fetch('data/drain_snapshot.json', {redirect: 'error'});
      if (!response.ok) throw new Error('The sample figures could not be loaded.');
      snapshot = await response.json();
    }
    return snapshot.variants[ids.filter(id => snapshot.variant_ids.includes(id)).join(',')] || snapshot.variants[''];
  }

  async function load(ids, key) {
    try {
      let body = null;
      try { body = await fetchService(ids); }
      catch (error) { if (error instanceof ServiceError || serviceSeen) throw error; }
      const next = body || await fetchSnapshot(ids);
      if (pendingKey !== key) return;
      data = next; mode = body ? 'service' : 'snapshot'; failure = '';
      if (body) serviceSeen = true;
    } catch (error) {
      if (pendingKey !== key) return;
      failure = error.message || 'The charges could not be loaded.';
      if (!data) mode = 'error';
    }
    pendingKey = null; loadedKey = key;
    if (['overview', 'plan'].includes(state.route)) render();
    if ($('#detail-dialog')?.open && $('#drain-breakdown')) openBreakdown();
  }

  // Called while rendering; fetches only when the set of completed tasks changes.
  function ensure() {
    const ids = completedIds(), key = ids.join(',');
    if (key === loadedKey || key === pendingKey) return;
    pendingKey = key;
    load(ids, key);
  }
  function reload() { loadedKey = null; ensure(); }

  function sinceLine() {
    if (!(data.daily > 0)) return '';
    if (data.date_of_death && data.since_death !== null)
      return `<p>About ${wholeMoney(data.since_death)} since ${esc(longDate(data.date_of_death))} · <span class="drain-approx">approximate</span></p>`;
    return `<p><button class="text-link drain-add-date" data-action="drain-date">Add the date to see the total so far.</button></p>`;
  }

  function card() {
    ensure();
    if (!data) {
      return mode === 'error'
        ? `<section class="drain-card" aria-labelledby="drain-title"><div><h2 id="drain-title" class="drain-label">Still being charged</h2><p class="drain-quiet">The recurring charges couldn’t be loaded right now.</p><p class="fine">${esc(failure)}</p></div><div class="drain-actions"><button class="button" data-action="drain-retry">Try again</button></div></section>`
        : `<section class="drain-card is-loading" aria-labelledby="drain-title" aria-busy="true"><div><h2 id="drain-title" class="drain-label">Still being charged</h2><p class="drain-quiet">Checking the records for recurring charges…</p></div></section>`;
    }
    const headline = data.daily > 0
      ? `<p class="drain-figure"><strong>${money(data.daily)}</strong><span>a day</span></p><p class="drain-annual">${wholeMoney(data.annual)} over a year if nothing changes</p>`
      : `<p class="drain-quiet">${data.possible_daily > 0 ? 'Nothing we can confirm is charging his accounts right now.' : 'Nothing is charging his accounts right now.'}</p>`;
    const detail = [
      sinceLine(),
      data.possible_daily > 0 ? `<p>+ up to ${money(data.possible_daily)} a day we’re less sure about</p>` : '',
      data.stopped_so_far > 0 ? `<p class="drain-stopped">You’ve already stopped ${money(data.stopped_so_far)} a day.</p>` : '',
    ].join('');
    const note = mode === 'snapshot'
      ? 'Sample figures from the fictional records, worked out by the Afterword service.'
      : data.daily > 0 ? 'Only charges the records show. You can stop these whenever you’re ready.' : 'Only charges the records show.';
    const stale = failure ? `<p class="fine" role="status">Couldn’t refresh just now. These are the last figures. <button class="text-link" data-action="drain-retry">Try again</button></p>` : '';
    return `<section class="drain-card" aria-labelledby="drain-title"><div class="drain-copy"><h2 id="drain-title" class="drain-label">Still being charged</h2>${headline}<div class="drain-lines">${detail}</div>${stale}</div><div class="drain-actions">${data.confirmed.length + data.possible.length + data.excluded.length ? `<button class="button" data-action="drain-breakdown">See what’s charging ${icon('arrow')}</button>` : ''}<p class="fine">${note}</p></div></section>`;
  }

  // A quiet caption on a plan row: why stopping this action matters, from the server's per-action rate.
  function caption(taskId) {
    ensure();
    const rate = data?.by_finding?.[taskId];
    if (!rate) return '';
    if (rate.daily > 0) return `<span class="drain-caption">${icon('refresh')}${money(rate.daily)} a day</span>`;
    if (rate.possible_daily > 0) return `<span class="drain-caption">${icon('refresh')}Possibly ${money(rate.possible_daily)} a day</span>`;
    return '';
  }

  function openDateDialog(returnTo) {
    const offline = mode !== 'service';
    const current = data?.date_of_death || '';
    modal('Date of death', `<p>Afterword uses this date to estimate what the recurring charges have cost since then. It is saved on the Afterword device, not shared.</p>
      <form id="drain-date-form" data-return="${returnTo === 'breakdown' ? 'breakdown' : ''}"><label class="field"><span>Date of death</span><input type="date" name="date" value="${esc(current)}" max="${today()}" required ${offline ? 'disabled' : ''}></label>
      <p class="fine" id="drain-date-state" role="status">${offline ? 'Saving the date needs the Afterword device. These are sample figures.' : ''}</p></form>`,
      offline ? button('Close', 'close-modal') : `${current ? button('Remove date', 'drain-date-clear') : ''}${button('Cancel', 'close-modal')}<button class="button primary" type="submit" form="drain-date-form">Save date</button>`);
  }

  async function saveDate(value, returnTo) {
    if (saving) return;
    saving = true;
    const status = $('#drain-date-state');
    $$('#detail-dialog .modal-foot button').forEach(b => { b.disabled = true; });
    try {
      const response = await fetch(new URL('/estate/date-of-death', location.origin), {method: 'POST', credentials: 'same-origin', redirect: 'error',
        headers: {Accept: 'application/json', 'Content-Type': 'application/json', 'X-Afterword-Client': 'web'}, body: JSON.stringify({date: value})});
      let body = {};
      try { body = await response.json(); } catch {}
      if (!response.ok) throw new Error(typeof body.detail === 'string' ? body.detail : 'The date could not be saved.');
      recordActivity(value ? 'Updated the date of death' : 'Removed the date of death');
      persist();
      toast(value ? 'Date saved. The totals now include it.' : 'Date removed.');
      if (returnTo === 'breakdown') openBreakdown(); else $('#detail-dialog').close();
      reload();
    } catch (error) {
      if (status) { status.textContent = error.message; status.setAttribute('role', 'alert'); }
      $$('#detail-dialog .modal-foot button').forEach(b => { b.disabled = false; });
    } finally { saving = false; }
  }

  const TIERS = {confirmed: ['Confirmed', 'neutral'], possible: ['Less sure', 'amber']};
  const BASIS = {stated: '', observed: ', seen in more than one statement', assumed_statement_period: ', assumed from one monthly statement'};
  const REASONS = {one_time_or_unknown: 'not recurring, or how often it repeats is unknown', low_confidence: 'too uncertain to count',
    cancelled_later: 'a later document shows it was cancelled', ended_before_death: 'last seen well before the date of death'};
  const SECTIONS = [
    ['stoppable', 'You can stop these whenever you’re ready', 'Confirmed charges here make up the daily figure.'],
    ['keep_for_now', 'Keep these running for now', 'Not counted. Stopping these could leave the home or a car unprotected.'],
    ['decide_later', 'These need a decision, not a cancellation', 'Not counted. Talk with whoever is handling the estate before changing these.'],
  ];
  const fullDate = iso => new Date(iso + 'T12:00:00').toLocaleDateString('en-US', {month: 'long', day: 'numeric', year: 'numeric'});
  // Reuse the workspace's source-link markup; drain-source returns here instead of to the workspace.
  const sourceLinks = evidence => [...new Set(evidence.map(e => e.doc_id))].map(id => (documentLink(id) || '').replace('data-action="document"', 'data-action="drain-source"')).join('');

  function rowAction(line) {
    const task = tasks.find(t => t.id === line.finding_id);
    if (!task || line.stopped) return '';
    if (line.bucket === 'stoppable' && window.OutreachCore?.defaults?.[task.id] === 'cancel_service')
      return `<button class="button" data-action="outreach-from-task" data-id="${esc(task.id)}">Ask to cancel</button>`;
    if (line.bucket === 'stoppable' && task.category === 'Personal belongings')
      return `<button class="button" data-task="${esc(task.id)}">Plan visit</button>`;
    return `<button class="button" data-task="${esc(task.id)}">Open action</button>`;
  }

  function row(line) {
    const [pill, tone] = line.stopped ? ['Stopped', 'neutral'] : TIERS[line.tier];
    const action = rowAction(line);
    return `<li class="drain-row${line.stopped ? ' is-stopped' : ''}"><div class="drain-row-head"><strong>${esc(line.label)}</strong><span class="pill ${tone}">${pill}</span></div>
      <p class="drain-row-meta">${money(line.amount)} ${esc(line.frequency)}${BASIS[line.frequency_basis] || ''} · <span class="drain-row-rate">${money(line.daily_rate)} a day</span></p>
      <p class="drain-row-note">${esc(line.note)}</p>
      <div class="drain-row-evidence">${line.evidence.map(e => `<q>${esc(e.quote)}</q>`).join('')}${sourceLinks(line.evidence)}</div>
      ${action ? `<div class="drain-row-actions">${action}</div>` : ''}</li>`;
  }

  function openBreakdown() {
    if (!data) return;
    const summary = data.daily > 0
      ? `<p class="drain-summary-figure"><strong>${money(data.daily)}</strong> a day · ${wholeMoney(data.annual)} over a year if nothing changes</p>`
      : `<p class="drain-summary-figure">${data.possible_daily > 0 ? 'Nothing we can confirm is charging his accounts right now.' : 'Nothing is charging his accounts right now.'}</p>`;
    const extra = [data.possible_daily > 0 ? `+ up to ${money(data.possible_daily)} a day we’re less sure about` : '',
      data.stopped_so_far > 0 ? `You’ve already stopped ${money(data.stopped_so_far)} a day.` : ''].filter(Boolean).map(t => `<p>${t}</p>`).join('');
    const date = data.date_of_death
      ? `<p>Date of death: ${esc(fullDate(data.date_of_death))}${data.daily > 0 && data.since_death !== null ? ` · about ${wholeMoney(data.since_death)} since then, approximate` : ''}. <button class="text-link" data-action="drain-date" data-return="breakdown">Change</button></p>`
      : `<p>No date of death added yet. <button class="text-link" data-action="drain-date" data-return="breakdown">Add the date</button> to see the total so far.</p>`;
    const sections = SECTIONS.map(([bucket, title, intro]) => {
      const lines = data.buckets[bucket];
      return `<section class="drain-section" aria-labelledby="drain-${bucket}"><h3 id="drain-${bucket}">${title}</h3><p class="fine">${intro}</p>${lines.length ? `<ul class="drain-rows">${lines.map(row).join('')}</ul>` : '<p class="drain-none">Nothing in the records belongs here.</p>'}</section>`;
    }).join('');
    const excluded = data.excluded.length ? `<details class="drain-excluded"><summary>Not counted (${data.excluded.length})</summary><ul>${data.excluded.map(e => `<li><strong>${esc(e.label)}</strong> · ${money(e.amount)}: ${REASONS[e.reason] || 'not counted'}${sourceLinks(e.evidence)}</li>`).join('')}</ul></details>` : '';
    modal('What’s still charging', `<div id="drain-breakdown"><div class="drain-summary">${summary}${extra}${date}</div>${sections}${excluded}
      <p class="fine drain-fine">Never counted: one-time bills, charges last seen more than one billing period before the date of death, charges a later document shows were cancelled, and anything we’re less than half sure of. A monthly charge is divided by 30.44 days. The total since the date of death is approximate, because some providers stop billing when they’re told and some don’t.${mode === 'snapshot' ? ' These are sample figures from the fictional records.' : ''}</p></div>`,
      button('Close', 'close-modal'));
  }

  Object.assign(window.actions, {
    'drain-breakdown': () => openBreakdown(),
    'drain-source': a => {
      openDocument(a.dataset.id);
      const foot = $('#detail-dialog .modal-foot');
      if (foot) foot.innerHTML = button('Back to charges', 'drain-breakdown', false, 'arrow');
    },
    'drain-retry': () => reload(),
    'drain-date': a => openDateDialog(a.dataset.return),
    'drain-date-clear': () => saveDate(null, $('#drain-date-form')?.dataset.return),
  });
  document.addEventListener('submit', e => {
    if (e.target.id !== 'drain-date-form') return;
    e.preventDefault();
    const value = new FormData(e.target).get('date');
    if (!AfterwordStore.validDate(value) || value > today()) {
      const status = $('#drain-date-state');
      if (status) { status.textContent = 'Choose a valid date that isn’t in the future.'; status.setAttribute('role', 'alert'); }
      return;
    }
    saveDate(value, e.target.dataset.return);
  });

  window.AfterwordDrain = {card, caption, reload, openBreakdown, money, wholeMoney};
  render();
})();

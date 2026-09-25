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
    return `<section class="drain-card" aria-labelledby="drain-title"><div class="drain-copy"><h2 id="drain-title" class="drain-label">Still being charged</h2>${headline}<div class="drain-lines">${detail}</div>${stale}</div><div class="drain-actions"><p class="fine">${note}</p></div></section>`;
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
      $('#detail-dialog').close();
      reload();
    } catch (error) {
      if (status) { status.textContent = error.message; status.setAttribute('role', 'alert'); }
      $$('#detail-dialog .modal-foot button').forEach(b => { b.disabled = false; });
    } finally { saving = false; }
  }

  Object.assign(window.actions, {
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

  window.AfterwordDrain = {card, reload, money, wholeMoney};
  render();
})();

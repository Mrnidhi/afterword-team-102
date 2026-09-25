'use strict';
// Daily drain UI: card states, where figures come from, and tone. Runs dist/drain.js with stubbed browser globals.
const assert = require('node:assert/strict'), fs = require('node:fs'), path = require('node:path'), vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname, '../dist/drain.js'), 'utf8');
const css = fs.readFileSync(path.join(__dirname, '../dist/drain.css'), 'utf8').replace(/\/\*[\s\S]*?\*\//g, '');
const snapshot = JSON.parse(fs.readFileSync(path.join(__dirname, '../dist/data/drain_snapshot.json'), 'utf8'));
const escapeHTML = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));

function harness(serve, {workspace = false, authenticated = true, profileReady = true} = {}) {
  const calls = [], dialog = {open: false, html: '', close() { this.open = false; }}, toasts = [], listeners = {};
  const state = {completed: ['notify-employer', 'gather-records'], route: 'overview', activity: []};
  const json = (status, body) => ({ok: status < 400, status, headers: {get: () => 'application/json'}, json: async () => body});
  const html = status => ({ok: false, status, headers: {get: () => 'text/html'}, json: async () => { throw new Error('html'); }});
  const context = {
    state, escapeHTML, console, URL, Error, Promise, Date, JSON, Object, Math,
    icon: () => '<svg></svg>', button: (label, action, primary) => `<button data-action="${action}" class="${primary ? 'primary' : ''}">${label}</button>`,
    modal: (title, body, foot) => { dialog.open = true; dialog.html = title + body + (foot || ''); },
    toast: text => toasts.push(text), persist: () => true, recordActivity: text => state.activity.push(text), render: () => { context.renders++; if (state.route === 'overview') context.AfterwordDrain?.card(); },
    AfterwordRuntime: {workspace},
    AfterwordStore: {validDate: v => /^\d{4}-\d{2}-\d{2}$/.test(v)}, $: selector => selector === '#detail-dialog' ? dialog : selector === '#dialog-content' ? {set textContent(value) {dialog.html = value;}} : selector === '#drain-breakdown' && dialog.open && dialog.html.includes('id="drain-breakdown"') ? {} : null, $$: () => [],
    document: {addEventListener: () => {}}, location: {origin: 'http://127.0.0.1:4173'}, renders: 0,
    tasks: [{id: 'storage', category: 'Personal belongings'}, {id: 'subscriptions', category: 'Subscriptions'}, {id: 'insurance', category: 'Insurance'}],
    documentLink: id => ['storage', 'statement'].includes(id) ? `<button class="source-link" data-action="document" data-id="${id}">${id}</button>` : '',
    OutreachCore: {defaults: {storage: 'request_records', subscriptions: 'cancel_service', insurance: 'policy_information'}},
    openDocument: id => { dialog.document = id; },
    fetch: async (url, options = {}) => { calls.push({url: String(url), method: options.method || 'GET', body: options.body}); return serve(String(url), options, {json, html}); },
  };
  context.window = context; context.actions = {};
  const emit = name => { for (const fn of listeners[name] || []) fn(); };
  context.addEventListener = (name, fn) => (listeners[name] ??= []).push(fn);
  const profile = {canAccessData: () => authenticated, lock() { authenticated = false; dialog.close(); dialog.html = ''; emit('afterword-locked'); context.render(); }};
  if (profileReady) context.AfterwordProfile = profile;
  vm.createContext(context);
  vm.runInContext(source, context);
  return {context, calls, dialog, toasts, drain: context.AfterwordDrain, lock: () => profile.lock(), login() { authenticated = true; context.AfterwordProfile = profile; emit('afterword-profile-changed'); }};
}
const settle = () => new Promise(r => setImmediate(r));
const base = snapshot.variants[''];
const service = body => (url, options, r) => url.includes('/drain') ? r.json(200, body) : r.html(404);

(async () => {
  // Loading, then the headline from the service. The first render asked for the figures once.
  let h = harness(service(base));
  assert.match(h.drain.card(), /Checking the records for recurring charges/);
  await settle();
  let card = h.drain.card();
  assert.match(card, /\$4\.24<\/strong><span>a day/);
  assert.match(card, /\$1,548 over a year if nothing changes/);
  assert.match(card, /\+ up to \$1\.82 a day we’re less sure about/);
  assert.match(card, /Add the date to see the total so far\./);
  assert.doesNotMatch(card, /since/);
  assert.doesNotMatch(card, /already stopped/, 'stopped line only appears when above zero');
  assert.equal(h.calls.filter(c => c.url.includes('/drain')).length, 1);
  assert.match(h.calls[0].url, /done=gather-records%2Cnotify-employer/);

  // With a date of death: an approximate total since that date.
  h = harness(service({...base, date_of_death: '2026-09-03', days_since_death: 22, since_death: base.daily * 22}));
  await settle();
  card = h.drain.card();
  assert.match(card, /About \$93 since September 3 · <span class="drain-approx">approximate<\/span>/);
  assert.doesNotMatch(card, /Add the date/);

  // Completing a task asks the server again; the card never subtracts on its own.
  const stopped = snapshot.variants['storage'];
  h = harness((url, options, r) => url.includes('/drain') ? r.json(200, url.includes('storage') ? stopped : base) : r.html(404));
  await settle();
  h.context.state.completed = [...h.context.state.completed, 'storage'];
  h.drain.card();
  await settle();
  card = h.drain.card();
  assert.ok(h.calls.some(c => c.url.includes('done=gather-records%2Cnotify-employer%2Cstorage')));
  assert.match(card, /Nothing we can confirm is charging his accounts right now\./);
  assert.match(card, /You’ve already stopped \$4\.24 a day\./);

  // Empty state.
  h = harness(service({...base, daily: 0, annual: 0, possible_daily: 0, confirmed: [], possible: [], buckets: {stoppable: [], keep_for_now: [], decide_later: []}}));
  await settle();
  assert.match(h.drain.card(), /Nothing is charging his accounts right now\./);

  // Static site: no service, so the backend-generated snapshot is used and labelled as sample figures.
  h = harness((url, options, r) => url.endsWith('data/drain_snapshot.json') ? r.json(200, snapshot) : r.html(404));
  await settle(); await settle();
  card = h.drain.card();
  assert.match(card, /\$4\.24/);
  assert.match(card, /Sample figures from the fictional records/);

  // A service error is shown, not replaced by sample figures.
  h = harness((url, options, r) => url.includes('/drain') ? r.json(500, {detail: 'Database is locked.'}) : r.json(200, snapshot));
  await settle();
  card = h.drain.card();
  assert.match(card, /couldn’t be loaded right now/);
  assert.match(card, /Database is locked\./);
  assert.match(card, /data-action="drain-retry"/);
  assert.ok(!h.calls.some(c => c.url.includes('drain_snapshot')));

  // Breakdown: three buckets, verbatim quotes, source links that return here, existing action controls.
  h = harness(service(base));
  await settle();
  assert.match(h.drain.card(), /data-action="drain-breakdown"/);
  h.context.actions['drain-breakdown']();
  let d = h.dialog.html;
  assert.match(d, /What’s still charging/);
  for (const title of ['You can stop these whenever you’re ready', 'Keep these running for now', 'These need a decision, not a cancellation']) assert.ok(d.includes(title), title);
  assert.match(d, /<q>Monthly charge: \$129<\/q>/);
  assert.match(d, /\$129\.00 monthly · <span class="drain-row-rate">\$4\.24 a day<\/span>/);
  assert.match(d, /\$39\.99 monthly, assumed from one monthly statement/);
  assert.match(d, /data-action="drain-source" data-id="storage"/);
  assert.doesNotMatch(d, /data-action="document"/);
  assert.match(d, /data-task="storage">Plan visit</);
  assert.match(d, /data-action="outreach-from-task" data-id="subscriptions">Ask to cancel</);
  assert.match(d, /Confirmed<\/span>/); assert.match(d, /Less sure<\/span>/);
  assert.equal((d.match(/Nothing in the records belongs here\./g) || []).length, 2, 'empty buckets say so');
  assert.match(d, /No date of death added yet/);
  assert.match(d, /divided by 30\.44 days/);

  // A keep-for-now charge is explained and can only be opened, never offered for cancellation.
  const keep = {...base.buckets.stoppable[1], id: 'keep', label: 'Oakridge Home Insurance', bucket: 'keep_for_now', tier: 'confirmed',
    note: 'Home insurance usually needs to stay active while the estate is settled, even if the house is empty.', finding_id: 'subscriptions'};
  const hostile = {...base.buckets.stoppable[0], id: 'hostile', label: '<img src=x onerror=alert(1)>', stopped: true};
  h = harness(service({...base, buckets: {stoppable: [hostile], keep_for_now: [keep], decide_later: []}, confirmed: [hostile, keep], possible: [],
    excluded: [{id: 'x', label: 'Harbor Gym', amount: 39.99, frequency: 'monthly', reason: 'cancelled_later', evidence: []}]}));
  await settle();
  h.context.actions['drain-breakdown']();
  d = h.dialog.html;
  const keepRow = d.slice(d.indexOf('Oakridge Home Insurance'), d.indexOf('</li>', d.indexOf('Oakridge Home Insurance')));
  assert.match(keepRow, /usually needs to stay active/);
  assert.match(keepRow, />Open action</);
  assert.doesNotMatch(keepRow, /cancel/i);
  assert.ok(!d.includes('<img src=x'), 'labels are escaped');
  assert.match(d, /&lt;img src=x onerror=alert\(1\)&gt;/);
  const stoppedRow = d.slice(d.indexOf('&lt;img'), d.indexOf('</li>', d.indexOf('&lt;img')));
  assert.match(stoppedRow, />Stopped</); assert.doesNotMatch(stoppedRow, /<button class="button"/);
  assert.match(d, /Not counted \(1\)/); assert.match(d, /a later document shows it was cancelled/);

  // Plan captions come from the server's per-action rates, never summed here.
  h = harness(service(base));
  await settle();
  assert.match(h.drain.caption('storage'), /\$4\.24 a day/);
  assert.match(h.drain.caption('subscriptions'), /Possibly \$1\.82 a day/);
  assert.equal(h.drain.caption('insurance'), '');
  h = harness(service(snapshot.variants['storage,subscriptions']));
  await settle();
  assert.equal(h.drain.caption('storage'), '', 'completed actions show no rate');

  // Tone: no red, no motion, serif figure.
  assert.doesNotMatch(css, /animation|@keyframes|transition/);
  assert.doesNotMatch(css, /\bred\b|crimson|#f00\b|#ff0000|danger/i);
  assert.match(css, /\.drain-figure strong\{[^}]*Newsreader/);
  assert.doesNotMatch(source, /setInterval|requestAnimationFrame/, 'the number updates on render, never on a timer');

  // The module can load before profile.js, but must not fetch or display
  // protected records until the profile announces an authenticated session.
  const gated = harness(service(base), {workspace: true, authenticated: false, profileReady: false});
  assert.equal(gated.calls.length, 0); assert.equal(gated.drain.card(), ''); assert.equal(gated.drain.caption('storage'), '');
  gated.context.actions['drain-breakdown'](); gated.context.actions['drain-date']({dataset:{}}); gated.context.actions['drain-date-clear']();
  assert.equal(gated.dialog.open, false); assert.equal(gated.calls.length, 0);
  gated.login(); await settle(); assert.match(gated.drain.card(), /\$4\.24/);
  gated.context.actions['drain-breakdown'](); assert.equal(gated.dialog.open, true);
  gated.lock(); assert.equal(gated.drain.card(), ''); assert.equal(gated.drain.caption('storage'), ''); assert.equal(gated.dialog.open, false); assert.equal(gated.dialog.html, '');
  const callsAtLock = gated.calls.length; gated.drain.reload(); assert.equal(gated.calls.length, callsAtLock);

  // A response for the old session cannot win even when login starts a new
  // request for the same completed-task key.
  let releaseOld, requests = 0;
  const stale = harness((url, options, r) => {
    requests++;
    if (requests === 1) return new Promise(resolve => { releaseOld = () => resolve(r.json(200, {...base, daily:99})); });
    return r.json(200, {...base, daily:1.25});
  }, {workspace:true});
  stale.lock(); stale.login(); await settle(); assert.match(stale.drain.card(), /\$1\.25/);
  releaseOld(); await settle(); assert.match(stale.drain.card(), /\$1\.25/); assert.doesNotMatch(stale.drain.card(), /\$99\.00/);

  // Authentication failures clear the displayed cache and never fall back to
  // fictional figures, including an HTML 401 rather than JSON.
  let denied = false;
  const expired = harness((url, options, r) => denied ? r.html(401) : r.json(200, base), {workspace:true});
  await settle(); assert.match(expired.drain.card(), /\$4\.24/);
  denied = true; expired.drain.reload(); await settle(); assert.equal(expired.drain.card(), '');
  assert.ok(!expired.calls.some(call => call.url.includes('drain_snapshot')));

  // A date save that completes after logout cannot re-open private dialogs,
  // record activity, toast success, or fetch records for the old session.
  let releaseSave;
  const saving = harness((url, options, r) => options.method === 'POST' ? new Promise(resolve => { releaseSave = () => resolve(r.json(200, {})); }) : r.json(200, base), {workspace:true});
  await settle(); const dateSave = saving.context.actions['drain-date-clear'](); saving.lock(); releaseSave(); await dateSave; await settle();
  assert.equal(saving.context.state.activity.length,0); assert.equal(saving.toasts.length,0); assert.equal(saving.dialog.open,false); assert.equal(saving.drain.card(),'');
  const deniedSave = harness((url, options, r) => options.method === 'POST' ? r.json(401,{detail:'Session ended'}) : r.json(200,base), {workspace:true});
  await settle(); await deniedSave.context.actions['drain-date-clear'](); assert.equal(deniedSave.drain.card(),''); assert.equal(deniedSave.context.state.activity.length,0);

  console.log('Drain UI passed: card states, recompute on completion, static snapshot, service error, breakdown buckets, source links, safe actions, escaping and level tone.');
})().catch(error => { console.error(error); process.exit(1); });

'use strict';
const assert = require('node:assert/strict');
const C = require('../dist/findings-core.js');
const row = (id, finding = {}, extra = {}) => ({contract:C.CONTRACT, id, source:'letter', status:'accepted', route:'extract', finding:{cat:'new_category', ...finding}, evidence:[], checks:{schema_errors:[], grounded:{}}, meta:{}, ...extra});

// Opaque identifiers and unrecognized model vocabulary remain data, never rewritten to fixtures.
for (const id of ['mail-0042', '__proto__', 'constructor', 'archive/2026?x=1', '<img src=x onerror=alert(1)>', 'पत्र']) assert.equal(C.validateResult(row(id)).valid, true);
const hostile = '<script>alert("document")</script>';
assert.equal(C.categoryLabel(hostile), hostile);
assert.equal(C.actionLabel(hostile), hostile);
assert.equal(C.categoryLabel(null), 'Uncategorized');
assert.equal(C.categoryLabel('retirement'), 'Retirement');
assert.equal(C.actionLabel('cancel'), 'Cancel the service');
for (const invalid of [null, [], 'text', {}, row(''), row('x', {}, {contract:'afterword.finding/v2'}), row('x', {}, {source:'web'}), row('x', {}, {status:'okay'}), row('x', {}, {route:'unknown'}), row('x', {}, {finding:[]}), row('x', {}, {evidence:{line:1}}), row('x', {}, {checks:[]}), row('x', {}, {text:123})]) assert.equal(C.validateResult(invalid).valid, false);

// Display titles use bounded source text, preserving opaque IDs only as metadata.
assert.equal(C.recordTitle(row('upload-'+ 'a'.repeat(64), {}, {text:'\r\n   \r\nSubject: Storage renewal\r\nBalance: 10'})), 'Storage renewal');
assert.equal(C.recordTitle(row('hash', {}, {text:'   ',source:'letter'})), 'Letter record');
assert.equal(C.recordTitle(row('hash',{inst:'Provider name'},{title:'Document title',text:'First line'})), 'Provider name');
assert.equal(C.recordTitle(row('hash',{}, {title:'Document title',text:'First line'})), 'Document title');
assert.equal(C.recordTitle(row('hash',{}, {text:hostile})), hostile);
assert.equal(Array.from(C.recordTitle(row('hash',{}, {text:'😀'.repeat(200)}))).length, 110);
const connectionFailure = row('failed', {}, {status:'failed',route:null,finding:null,checks:{error:'URLError: <urlopen error [Errno 61] Connection refused>'}});
const originalFailure=JSON.stringify(connectionFailure);
assert.deepEqual(C.reviewPresentation(connectionFailure), {reasons:['The local model is unavailable. Your source is saved; retry when it is available.'],details:connectionFailure.checks.error});
assert.equal(JSON.stringify(connectionFailure),originalFailure,'Display simplification does not rewrite stored checks.');
assert.deepEqual(C.reviewPresentation(row('failed',{}, {status:'failed',checks:{schema_errors:['unparseable']}})),{reasons:['unparseable'],details:null});

// Unverified fields remain unchanged but must be presented as provisional.
const unsupported=row('unsupported',{due:0,deadline_date:'2026-09-01',amt:0,money_at_stake:0},{status:'needs_review',checks:{schema_errors:[],grounded:{due:false,amt:false}}});
const originalUnsupported=JSON.stringify(unsupported);
assert.equal(C.fieldNeedsReview(unsupported,'due'),true);assert.equal(C.fieldNeedsReview(unsupported,'amt'),true);
assert.equal(C.fieldNeedsReview(row('grounded',{due:0,amt:0},{checks:{schema_errors:[],grounded:{due:true,amt:true}}}),'due'),false);
assert.equal(C.fieldNeedsReview(row('schema', {due:0}, {checks:{schema_errors:["'due' not an integer"],grounded:{due:true}}}),'due'),true);
assert.equal(C.fieldNeedsReview(row('schema', {amt:0}, {checks:{schema_errors:[{field:'amt',message:'Invalid value'}],grounded:{amt:true}}}),'amt'),true);
assert.equal(C.fieldNeedsReview(row('other', {due:0}, {checks:{schema_errors:["'kind'='due' not an allowed value"],grounded:{due:true}}}),'due'),false);
assert.equal(C.fieldNeedsReview(row('invalid',{due:'soon'}),'due'),true);
assert.equal(JSON.stringify(unsupported),originalUnsupported);
assert.equal(C.sortFindings([row('later',{due:30,money_at_stake:900}),unsupported])[0],unsupported,'Provisional display does not rewrite engine priority.');

// Strict calendar dates, with no browser-dependent parsing or deadline interpretation.
for (const date of ['2026-01-31','2028-02-29','2000-02-29','0001-01-01']) assert.equal(C.validDate(date), true);
for (const date of ['09/24/2026','2026-9-24','2026-02-29','1900-02-29','2026-04-31','2026-00-01','2026-01-00','2026-01-01T00:00:00Z','tomorrow',0,null,'0000-01-01']) assert.equal(C.validDate(date), false);
const sorting = [row('unknown'), row('zero',{money_at_stake:0}), row('late-high',{due:20,deadline_date:'2026-10-02',money_at_stake:1e6}), row('same-low',{due:10,deadline_date:'2026-10-01',money_at_stake:10}), row('same-high',{due:10,deadline_date:'2026-10-01',money_at_stake:50}), row('ambiguous',{deadline_date:'10/01/2026',money_at_stake:999}), row('equal-a',{money_at_stake:0}), row('equal-b',{money_at_stake:0})];
assert.deepEqual(C.sortFindings([row('calendar-only',{deadline_date:'2026-01-01',money_at_stake:999}), row('due-no-reference',{due:30,money_at_stake:1})]).map(r=>r.id), ['due-no-reference','calendar-only'], 'The authoritative schema prioritizes stated due even without reference_date.');
assert.deepEqual(C.sortFindings([row('same-date',{due:20,deadline_date:'2026-01-01'}),row('earlier-due',{due:0})]).map(r=>r.id), ['earlier-due','same-date']);
const originalOrder = sorting.map(r => r.id);
assert.deepEqual(C.sortFindings(sorting).map(r => r.id), ['same-high','same-low','late-high','ambiguous','zero','equal-a','equal-b','unknown']);
assert.deepEqual(sorting.map(r => r.id), originalOrder, 'Sorting must not mutate the server response.');
assert.equal(C.comparePriority(row('a',{money_at_stake:0}), row('b',{money_at_stake:null})), -1);
assert.equal(C.comparePriority(row('a',{money_at_stake:'500'}), row('b',{money_at_stake:null})), 0);

const failedDrop = row('failed-drop', {}, {status:'failed',route:'drop',finding:null});
const failedMissingRoute = row('failed-no-route', {}, {status:'failed',route:null,finding:null});
const partition = C.partitionFindings([row('action'), row('memory', {}, {route:'memory',finding:null}), row('ignored', {}, {route:'drop',finding:null}), failedDrop, failedMissingRoute, null]);
assert.deepEqual(partition.actions.map(r => r.id), ['action']);
assert.deepEqual(partition.memories.map(r => r.id), ['memory']);
assert.deepEqual(partition.ignored.map(r => r.id), ['ignored']);
assert.deepEqual(partition.failed.map(r => r.id), ['failed-drop','failed-no-route']);
assert.equal(partition.invalid.length, 1);
assert.equal(partition.total, 6);
assert.equal(C.partitionFindings({}).collectionError, 'Findings must be a list.');

// Exact Python splitlines semantics, including uncommon breaks and no trailing phantom line.
for (const [text, expected] of [['',[]], ['\n',['']], ['\n\n',['','']], ['one\r\n\r\nthree\r\n',['one','','three']], ['a\rb\vc\fd\x1ce\x1df\x1eg\x85h\u2028i\u2029j',['a','b','c','d','e','f','g','h','i','j']], ['  text  \nlast',['  text  ','last']]]) assert.deepEqual(C.splitLines(text), expected);
const source = 'Subject: A\r\n\r\n' + hostile + '\r\nAmount: 0\r\n';
const evidence = [{line:3,text:hostile}, {line:2,text:''}, {line:3,text:hostile}, {line:4,text:'Amount: 999'}, {line:9,text:'invented'}, {line:'1',text:'Subject: A'}, {line:0}, {line:1.5}, null];
const mapped = C.evidenceLines(source, evidence);
assert.equal(mapped.available, true);
assert.equal(mapped.lines.length, 4);
assert.deepEqual(mapped.lines.map(l => l.cited), [false,true,true,true]);
assert.equal(mapped.lines[2].text, hostile);
assert.equal(mapped.lines[2].evidence.length, 2);
assert.equal(mapped.mismatches.length, 1);
assert.equal(mapped.mismatches[0].source, 'Amount: 0');
assert.equal(mapped.invalidEvidence.length, 5);
assert.equal(C.evidenceLines(undefined, [{line:1,text:'a'}]).available, false);
assert.equal(C.evidenceLines(undefined, [{line:1,text:'a'}]).invalidEvidence[0].reason, 'Stored source text is unavailable.');
assert.equal(C.evidenceLines('', []).available, true);
assert.equal(C.evidenceLines('', [{line:1,text:''}]).lines[0].cited, true, 'Empty source agrees with the engine single empty line.');
assert.equal(C.evidenceLines('a', {}).invalidEvidence.length, 1);
assert.equal(source, 'Subject: A\r\n\r\n' + hostile + '\r\nAmount: 0\r\n', 'Evidence mapping must not normalize stored text.');

const needsReview = row('review', {amt:'$10',deadline_date:'30 days'}, {status:'needs_review',checks:{schema_errors:['Invalid action', {message:'Missing category'}, 'Invalid action'],grounded:{amt:true,ref:false,inst:null,custom:false}}});
assert.deepEqual(C.reviewReasons(needsReview), ['Invalid action','Missing category','The reference number could not be verified against the cited lines.','The custom could not be verified against the cited lines.','The returned deadline is not a valid calendar date.','The returned printed amount is not a valid number.']);
assert.equal(C.statusPresentation(needsReview).status, 'needs_review');
assert.equal(C.statusPresentation(row('a')).label, 'Accepted');
assert.equal(C.statusPresentation({}).label, 'Invalid result');
assert.ok(C.reviewReasons(row('a', {}, {status:'needs_review'})).length);
assert.ok(C.reviewReasons(failedDrop).length);
assert.deepEqual(C.reviewReasons({...failedDrop,checks:{error:'Local server unavailable'}}), ['Local server unavailable']);
assert.equal(C.validateResult(failedMissingRoute).valid,true,'Failed engine result legitimately has a null route.');
assert.deepEqual(C.amountComparison(row('a',{amt:0,money_at_stake:0,rec:'monthly',kind:'benefit'})), {printed:0,atStake:0,recurrence:'monthly',kind:'benefit'});
assert.deepEqual(C.amountComparison(row('a',{amt:null,money_at_stake:'10'})), {printed:null,atStake:null,recurrence:null,kind:null});
assert.equal(C.amountComparison(row('a',{amt:-4,money_at_stake:Infinity})).printed, -4);
assert.equal(C.amountComparison(row('a',{amt:-4,money_at_stake:Infinity})).atStake, null);

const telemetry = C.aggregateTelemetry([
 row('first', {}, {meta:{tier:'L1',model:'base',latency_ms:6000,output_tokens:60}}),
 row('second', {}, {meta:{tier:'L1',model:'tuned',latency_ms:0,output_tokens:0}}),
 row('third', {}, {meta:{tier:'__proto__',model:'base',latency_ms:-1,output_tokens:'500'}}),
 row('fourth', {}, {meta:{output_tokens:1.5}}),
 null
]);
assert.equal(telemetry.documents, 4);
assert.deepEqual(telemetry.tiers, [{tier:'L1',count:2},{tier:'__proto__',count:1}]);
assert.equal(telemetry.unknownTierCount, 1);
assert.deepEqual(telemetry.models, ['base','tuned']);
assert.deepEqual(telemetry.latency, {samples:2,totalMs:6000,meanMs:3000});
assert.deepEqual(telemetry.outputTokens, {samples:2,total:60,mean:30});
assert.equal(telemetry.entitiesLeftDevice, null);
assert.equal(telemetry.cloudEquivalentCost, null);
assert.equal(C.aggregateTelemetry([]).latency.meanMs, null);
assert.equal(C.aggregateTelemetry([]).outputTokens.total, null);
assert.equal(C.aggregateTelemetry([row('zero', {}, {meta:{latency_ms:0,output_tokens:0}})]).outputTokens.total, 0);
console.log('Findings contract core: route separation, exact evidence, ordering, statuses, amounts, and measured telemetry passed.');

// Engine 0.2 ranking: priority_score orders first; results without a score keep the old rule.
{
  const hi=row('hi',{priority_score:83,priority:'P1',tags:['clawback_risk','nonstandard'],priority_reasons:['+40 overdue']});
  const lo=row('lo',{priority_score:34,priority:'P3',due:1,money_at_stake:1});
  assert.deepEqual(C.sortFindings([lo,hi]).map(r=>r.id),['hi','lo']);
  const p=C.priorityPresentation(hi);
  assert.equal(p.tier,'P1'); assert.equal(p.score,83); assert.deepEqual(p.reasons,['+40 overdue']);
  assert.deepEqual(p.tags.map(t=>t.label),['May be clawed back','nonstandard']);
  assert.deepEqual(C.priorityPresentation(row('old',{due:5})),{tier:null,score:null,tags:[],reasons:[]});
  const oldA=row('a',{due:5,money_at_stake:10}), oldB=row('b',{due:60,money_at_stake:99999});
  assert.deepEqual(C.sortFindings([oldB,oldA]).map(r=>r.id),['a','b']);
}

// Chat intake helpers.
{
  assert.equal(C.detectSource('Subject: Account ending 5120\nFrom: bank@x.com\n\nBalance $10'), 'email');
  assert.equal(C.detectSource('Lumenflix: $15.99 renews 10/02. Reply STOP'), 'sms');
  assert.equal(C.detectSource('Dear family,\nline\nline\nline\nline\nSincerely'), 'letter');
  for (let i = 0; i < 50; i++) assert.match(C.chatDocumentId(), /^[A-Za-z0-9][A-Za-z0-9_.:-]*$/);
  const links = C.contactLinks({contacts:{urls:['www.x.com/a','javascript:alert(1)','data:text/html,x','https://p.y.com/q?a=1','evil"onmouseover=1'],
                                          emails:['a@b.com','not-an-email'], phones:['(800) 555-0142','555-0142']}});
  assert.deepEqual(links.map(l => l.href), ['https://www.x.com/a','https://p.y.com/q?a=1','mailto:a@b.com','tel:8005550142']);
  assert.deepEqual(C.contactLinks({}), []);
  const g = C.categoryRollup([
    row('a',{cat:'loan',priority_score:61,money_at_stake:386.4}), row('b',{cat:'retirement',priority_score:83,money_at_stake:12840}),
    row('c',{cat:'loan',priority_score:40,money_at_stake:100}), row('m',{cat:'personal'},{route:'memory'})]);
  assert.deepEqual(g.map(x => x.cat), ['retirement','loan']);
  assert.deepEqual(g[1].items.map(r => r.id), ['a','c']);
  assert.equal(Math.round(g[1].atStake * 100), 48640);
  // The same account sent twice counts once; the less urgent copy is listed as related.
  const dup = C.categoryRollup([row('p1',{cat:'retirement',priority_score:83,money_at_stake:12840,account_key:'riverbend:0213'}),
                                row('p2',{cat:'retirement',priority_score:70,money_at_stake:12840,account_key:'riverbend:0213'}),
                                row('bad',{cat:'retirement'},{status:'failed'})]);
  assert.deepEqual(dup[0].items.map(r => r.id), ['p1']);
  assert.equal(dup[0].atStake, 12840);
  assert.deepEqual(dup[0].leads[0].related, ['p2']);
}

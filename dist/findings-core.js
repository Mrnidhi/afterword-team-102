/* Pure contract helpers for the local findings workspace. No network or HTML output. */
(function(root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.FindingsCore = api;
})(typeof globalThis === 'object' ? globalThis : this, function() {
  'use strict';
  const CONTRACT = 'afterword.finding/v1';
  // Recovered model/schema.py uses relative due days, including when no reference date exists.
  // Use the engine-provided money_at_stake; do not repeat its financial policy calculations.
  const ORDERING_BASIS = 'schema.priority(): stated due days ascending, then engine-provided money_at_stake descending.';
  const ROUTES = ['extract', 'memory', 'drop'];
  const STATUSES = ['accepted', 'needs_review', 'failed'];
  const SOURCES = ['email', 'sms', 'letter'];
  const ACTIONS = Object.freeze({notify:'Notify the provider',claim:'Ask about a claim',cancel:'Cancel the service',stop_payment:'Stop the payment',verify_debt:'Verify the debt',transfer:'Ask about a transfer',close:'Close the account',review:'Review the record'});
  const CATEGORIES = Object.freeze({irrelevant:'Irrelevant',personal:'Personal',bank:'Bank accounts',credit_card:'Credit cards',insurance:'Insurance',retirement:'Retirement',investment:'Investments',loan:'Loans',utility:'Utilities',subscription:'Subscriptions',medical:'Medical',government:'Government',legal:'Legal',property:'Property'});
  const FIELDS = Object.freeze({amt:'printed amount',ref:'reference number',inst:'institution',due:'deadline'});
  const object = value => value !== null && typeof value === 'object' && !Array.isArray(value);
  const finite = value => typeof value === 'number' && Number.isFinite(value);
  const numberValue = value => finite(value) ? value : null;
  const label = (value, fallback) => typeof value === 'string' && value.trim() ? value : fallback;
  const categoryLabel = value => Object.hasOwn(CATEGORIES, value) ? CATEGORIES[value] : label(value, 'Uncategorized');
  const actionLabel = value => Object.hasOwn(ACTIONS, value) ? ACTIONS[value] : label(value, 'Review the record');

  function validDate(value) {
    if (typeof value !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(value)) return false;
    const [year, month, day] = value.split('-').map(Number);
    if (year < 1 || month < 1 || month > 12) return false;
    const leap = year % 4 === 0 && (year % 100 !== 0 || year % 400 === 0);
    return day >= 1 && day <= [31, leap ? 29 : 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][month - 1];
  }

  function recordTitle(value) {
    const bound = text => {const characters=Array.from(text.trim());return characters.length>110?characters.slice(0,109).join('')+'…':characters.join('');};
    for (const candidate of [value?.finding?.inst, value?.title]) if (typeof candidate === 'string' && candidate.trim()) return bound(candidate);
    const first = splitLines(value?.text).find(line => line.trim());
    if (first) return bound(first.replace(/^Subject:\s*/i, '')) || 'Email record';
    const sourceTitles={email:'Email record',sms:'SMS record',letter:'Letter record'};
    return Object.hasOwn(sourceTitles,value?.source)?sourceTitles[value.source]:'Source record';
  }

  function validateResult(value) {
    const issues = [];
    if (!object(value)) return {valid:false, issues:['Result must be an object.']};
    if (value.contract !== CONTRACT) issues.push('Unsupported or missing finding contract.');
    // IDs are opaque data. They are not restricted to fixture names or used as object keys.
    if (typeof value.id !== 'string' || !value.id.trim()) issues.push('Document identifier is missing.');
    if (!SOURCES.includes(value.source)) issues.push('Document source is not supported.');
    if (!STATUSES.includes(value.status)) issues.push('Finding status is not supported.');
    if (!ROUTES.includes(value.route) && !(value.status === 'failed' && value.route == null)) issues.push('Finding route is not supported.');
    if (value.route === 'extract' && value.status !== 'failed' && !object(value.finding)) issues.push('Extracted finding is missing.');
    if (value.finding != null && !object(value.finding)) issues.push('Finding must be an object or null.');
    if (value.evidence !== undefined && !Array.isArray(value.evidence)) issues.push('Evidence must be a list.');
    if (value.checks !== undefined && !object(value.checks)) issues.push('Checks must be an object.');
    if (value.meta !== undefined && !object(value.meta)) issues.push('Model metadata must be an object.');
    if (value.text !== undefined && typeof value.text !== 'string') issues.push('Stored source text must be a string.');
    return {valid:issues.length === 0, issues};
  }

  function comparePriority(a, b) {
    const ad = Number.isSafeInteger(a?.finding?.due) ? a.finding.due : null;
    const bd = Number.isSafeInteger(b?.finding?.due) ? b.finding.due : null;
    if (ad !== bd) {
      if (ad === null) return 1;
      if (bd === null) return -1;
      return ad < bd ? -1 : 1;
    }
    const av = numberValue(a?.finding?.money_at_stake);
    const bv = numberValue(b?.finding?.money_at_stake);
    if (av === bv) return 0;
    if (av === null) return 1;
    if (bv === null) return -1;
    return av > bv ? -1 : 1;
  }

  function sortFindings(values) {
    return (Array.isArray(values) ? values : []).map((value, index) => ({value, index}))
      .sort((a, b) => comparePriority(a.value, b.value) || a.index - b.index).map(item => item.value);
  }

  function partitionFindings(values) {
    const result = {actions:[], memories:[], ignored:[], failed:[], invalid:[], total:0};
    if (!Array.isArray(values)) return {...result, collectionError:'Findings must be a list.'};
    result.total = values.length;
    for (const value of values) {
      const validation = validateResult(value);
      // Failed processing must remain visible even when its route is missing or drop.
      if (object(value) && value.status === 'failed') {
        result.failed.push(value);
        if (!validation.valid) result.invalid.push({result:value, issues:validation.issues});
        continue;
      }
      if (!validation.valid) { result.invalid.push({result:value, issues:validation.issues}); continue; }
      if (value.route === 'extract') result.actions.push(value);
      else if (value.route === 'memory') result.memories.push(value);
      else result.ignored.push(value);
    }
    result.actions = sortFindings(result.actions);
    return result;
  }

  // Python str.splitlines(): CRLF is one break, terminal break adds no phantom line.
  // Keep interior empty lines, without trimming or normalizing the source.
  function splitLines(text) {
    if (typeof text !== 'string' || text === '') return [];
    const lines = text.split(/\r\n|[\n\r\v\f\x1c-\x1e\x85\u2028\u2029]/);
    if (/(?:\r\n|[\n\r\v\f\x1c-\x1e\x85\u2028\u2029])$/.test(text)) lines.pop();
    return lines;
  }

  function evidenceLines(text, evidence) {
    const available = typeof text === 'string';
    // engine.number_lines uses splitlines() or [""] for an empty document.
    const sourceLines = available && text === '' ? [''] : splitLines(text);
    const lines = sourceLines.map((value, index) => ({number:index + 1, text:value, cited:false, evidence:[]}));
    const invalidEvidence = [], mismatches = [];
    if (evidence != null && !Array.isArray(evidence)) invalidEvidence.push({index:null, line:null, reason:'Evidence is not a list.'});
    for (const [index, item] of (Array.isArray(evidence) ? evidence : []).entries()) {
      if (!object(item) || !Number.isInteger(item.line) || item.line < 1) {
        invalidEvidence.push({index, line:object(item) ? item.line : null, reason:'Evidence line must be a positive integer.'});
        continue;
      }
      if (!available || item.line > lines.length) {
        invalidEvidence.push({index, line:item.line, reason:available ? 'Evidence line is outside the stored source.' : 'Stored source text is unavailable.'});
        continue;
      }
      const target = lines[item.line - 1];
      target.cited = true;
      target.evidence.push(item);
      // Highlight the actual source line, never replace it with a model quotation.
      if (typeof item.text === 'string' && item.text !== target.text) mismatches.push({index, line:item.line, source:target.text, quoted:item.text});
      if (item.text !== undefined && typeof item.text !== 'string') invalidEvidence.push({index, line:item.line, reason:'Evidence quotation must be text.'});
    }
    return {available, lines, invalidEvidence, mismatches};
  }

  function reviewReasons(value) {
    const reasons = [];
    const checks = object(value?.checks) ? value.checks : {};
    if (typeof checks.error === 'string' && checks.error.trim()) reasons.push(checks.error);
    if (Array.isArray(checks.schema_errors)) {
      for (const error of checks.schema_errors) {
        if (typeof error === 'string' && error.trim()) reasons.push(error);
        else if (object(error) && typeof error.message === 'string' && error.message.trim()) reasons.push(error.message);
      }
    }
    if (object(checks.grounded)) {
      for (const [field, grounded] of Object.entries(checks.grounded)) {
        if (grounded === false) reasons.push('The ' + (Object.hasOwn(FIELDS, field) ? FIELDS[field] : field) + ' could not be verified against the cited lines.');
      }
    }
    if (value?.finding?.due != null && !Number.isSafeInteger(value.finding.due)) reasons.push('The returned days to act is not a valid integer.');
    if (value?.finding?.deadline_date != null && !validDate(value.finding.deadline_date)) reasons.push('The returned deadline is not a valid calendar date.');
    for (const [key, description] of [['amt','printed amount'], ['money_at_stake','money at stake']]) {
      if (value?.finding?.[key] != null && !finite(value.finding[key])) reasons.push('The returned ' + description + ' is not a valid number.');
    }
    if (!reasons.length && value?.status === 'needs_review') reasons.push('The model marked this result for review; no specific check was supplied.');
    if (!reasons.length && value?.status === 'failed') reasons.push('Processing failed. Review the source and retry when the local model is available.');
    return [...new Set(reasons)];
  }

  function reviewPresentation(value) {
    const reasons = reviewReasons(value), error = value?.checks?.error;
    const unavailable = value?.status === 'failed' && typeof error === 'string' && /connection[ _-]?refused|connectionerror|failed to establish a new connection|local model (?:service )?(?:is )?unavailable|could not connect|cannot connect|ECONNREFUSED/i.test(error);
    if (!unavailable) return {reasons, details:null};
    return {reasons:['The local model is unavailable. Your source is saved; retry when it is available.', ...reasons.filter(reason => reason !== error)], details:error};
  }

  function statusPresentation(value) {
    const status = STATUSES.includes(value?.status) ? value.status : null;
    return {status, label:({accepted:'Accepted',needs_review:'Needs review',failed:'Failed'})[status] || 'Invalid result', reasons:reviewReasons(value)};
  }

  function amountComparison(value) {
    const finding = object(value?.finding) ? value.finding : {};
    return {printed:numberValue(finding.amt), atStake:numberValue(finding.money_at_stake), recurrence:typeof finding.rec === 'string' ? finding.rec : null, kind:typeof finding.kind === 'string' ? finding.kind : null};
  }

  function aggregateTelemetry(values) {
    const rows = Array.isArray(values) ? values.filter(row => validateResult(row).valid) : [];
    const tiers = new Map(), models = new Set();
    let unknownTierCount = 0, latencyTotal = 0, latencySamples = 0, tokenTotal = 0, tokenSamples = 0;
    for (const row of rows) {
      const meta = object(row.meta) ? row.meta : {};
      if (typeof meta.tier === 'string' && meta.tier.trim()) tiers.set(meta.tier, (tiers.get(meta.tier) || 0) + 1);
      else unknownTierCount++;
      if (typeof meta.model === 'string' && meta.model.trim()) models.add(meta.model);
      if (finite(meta.latency_ms) && meta.latency_ms >= 0) {latencyTotal += meta.latency_ms; latencySamples++;}
      if (Number.isSafeInteger(meta.output_tokens) && meta.output_tokens >= 0) {tokenTotal += meta.output_tokens; tokenSamples++;}
    }
    return {
      documents:rows.length, tiers:[...tiers].map(([tier, count]) => ({tier, count})), unknownTierCount, models:[...models],
      latency:{samples:latencySamples, totalMs:latencySamples ? latencyTotal : null, meanMs:latencySamples ? latencyTotal / latencySamples : null},
      outputTokens:{samples:tokenSamples, total:tokenSamples ? tokenTotal : null, mean:tokenSamples ? tokenTotal / tokenSamples : null},
      // These require explicit deployment/model-layer measurements. Tier names do not prove them.
      entitiesLeftDevice:null, cloudEquivalentCost:null
    };
  }

  return Object.freeze({CONTRACT, ORDERING_BASIS, validateResult, validDate, numberValue, recordTitle, categoryLabel, actionLabel, comparePriority, sortFindings, partitionFindings, splitLines, evidenceLines, reviewReasons, reviewPresentation, statusPresentation, amountComparison, aggregateTelemetry});
});

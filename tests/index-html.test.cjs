'use strict';
// The workspace entrypoint must load each asset once: a repeated top-level script
// throws "already declared", and a repeated IIFE (i18n.js) runs twice.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const html = fs.readFileSync(path.join(__dirname, '../dist/index.html'), 'utf8');
const assets = [...html.matchAll(/<(?:script|link)[^>]+(?:src|href)="([a-z0-9-]+\.(?:js|css))(?:\?v=[a-f0-9]+)?"/g)].map(m => m[1]);
const repeated = assets.filter((asset, index) => assets.indexOf(asset) !== index);
assert.deepEqual(repeated, [], 'Assets referenced more than once: ' + repeated.join(', '));
for (const dependency of ['ui-translate.js', 'ui-strings.js'])
  assert.ok(assets.indexOf(dependency) < assets.indexOf('i18n.js'), dependency + ' must load before i18n.js');
console.log('Workspace entrypoint loads ' + assets.length + ' assets once each, with translation data before i18n.js.');

'use strict';
const assert=require('node:assert/strict');
const fs=require('node:fs');

const app=fs.readFileSync('dist/app.js','utf8');
const pages=fs.readFileSync('dist/pages.js','utf8');
const workspace=fs.readFileSync('dist/workspace.js','utf8');
const drain=fs.readFileSync('dist/drain.js','utf8');
const scans=fs.readFileSync('dist/outreach-scans.js','utf8');

assert(!app.includes("['letters'"), 'Letters is not registered in the main navigation');
assert(!pages.includes('data-action="finding-letter"') && !pages.includes('letters:lettersPage') && !pages.includes("go('letters"), 'Evidence cannot open the removed Letters view');
assert(!workspace.includes('letters:completeLettersPage') && !workspace.includes('data-action="outreach-from-task"') && !workspace.includes('Prepare a letter'), 'Workspace actions cannot open Letters');
assert(!drain.includes('outreach-from-task') && !drain.includes('Ask to cancel'), 'Daily-drain rows cannot open Letters');
assert(!scans.includes('Review provider contacts') && !scans.includes('data-action="scan-letter"'), 'Scan review cannot link into Letters');

console.log('Letters removal passed: navigation, evidence, drain, scan, and workspace entry points are gone.');

// Verify shipped demo data cannot silently diverge between local and static modes.
const fs = require('node:fs');
const assert = require('node:assert/strict');
for (const name of ['providers_directory.json', 'demo_archive.json']) {
  assert.equal(fs.readFileSync('data/' + name, 'utf8'), fs.readFileSync('dist/data/' + name, 'utf8'), name + ' differs between backend and public demo');
}
const directory = JSON.parse(fs.readFileSync('data/providers_directory.json', 'utf8'));
const archive = JSON.parse(fs.readFileSync('data/demo_archive.json', 'utf8'));
const ids = new Set(directory.providers.map(p => p.provider_id));
assert.equal(ids.size, directory.providers.length, 'Duplicate provider IDs');
for (const id of ['cedar-life','valley-storage','cedar-clinic','harbor-gym','streamly','northline']) assert(ids.has(id), 'Missing archive provider: ' + id);
for (const provider of directory.providers) {
  assert.equal(provider.fictional, true);
  assert.equal(provider.verified_by_user, false, 'Shipped data must not claim user verification');
  assert.equal(provider.channels.length, 0, 'Configure owned inbox at runtime; do not ship an assumed controlled mailbox');
  assert.match(provider.demo_alias, /^[a-z0-9-]+$/);
  assert(provider.domains.every(domain => domain.endsWith('.example')));
}
const docIds = new Set(archive.documents.map(doc => doc.id));
assert.equal(docIds.size, archive.documents.length);
for (const finding of archive.findings) {
  if (finding.provider_id) assert(ids.has(finding.provider_id));
  for (const provider of finding.provider_ids || []) assert(ids.has(provider));
  for (const source of finding.source_ids) assert(docIds.has(source));
  if (finding.masked_identifier) assert.match(finding.masked_identifier, /^(policy|account|reference) ending [A-Za-z0-9]{4}$/);
}
assert.equal(archive.person.date_of_death, null, 'Date of death must be supplied by the family');
for (const doc of archive.documents) {
  assert.equal(doc.fictional, true);
  for (const address of doc.text.match(/[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}/gi) || []) assert(address.endsWith('.example'), 'Unexpected deliverable contact in public demo archive');
}
console.log('Outreach fixture parity, provider coverage and unconfigured recipient checks passed.');

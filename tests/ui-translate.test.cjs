const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const context = vm.createContext({});
vm.runInContext(fs.readFileSync('dist/ui-translate.js','utf8')+'\nthis.ui = AfterwordUiTranslate;',context);
const {lookup} = context.ui;

const dict = {
  'Documents':'Documentos',
  '2 completed':'2 completados',
  'Sep 24':'Sep 24',
  '$1,240 before a recorded $400 payment':'$1,240 antes de un pago registrado de $400',
  // Reorders the two amounts: must never be used as a template.
  '$400 paid of $1,240':'de $1,240 se pagaron $400',
  // Digits rewritten as Devanagari numerals: exact match only.
  '3 findings':'३ निष्कर्ष',
};

// Exact matches.
assert.equal(lookup(dict,'Documents'),'Documentos');
assert.equal(lookup(dict,'$400 paid of $1,240'),'de $1,240 se pagaron $400');
assert.equal(lookup(dict,'3 findings'),'३ निष्कर्ष');

// Same string, different numbers, digits kept in order: the template applies.
assert.equal(lookup(dict,'5 completed'),'5 completados');
assert.equal(lookup(dict,'12 completed'),'12 completados');
assert.equal(lookup(dict,'Sep 30'),'Sep 30');
assert.equal(lookup(dict,'$2,000 before a recorded $150 payment'),'$2,000 antes de un pago registrado de $150');

// A translation that reorders amounts is never used for other numbers. Same
// template key as the reordered entry ("$# paid of $#,#"), so this only
// passes because the order check refuses it -- positional substitution would
// otherwise produce "de $500 se pagaron $2,000", swapping the two amounts.
assert.equal(lookup(dict,'$500 paid of $2,000'),null);
// Neither is one whose digits the model rewrote.
assert.equal(lookup(dict,'4 findings'),null);

// Misses fall back to null, so the caller leaves the English in place.
assert.equal(lookup(dict,'Something new'),null);
assert.equal(lookup(dict,'Documents '),null);
assert.equal(lookup(undefined,'Documents'),null);
assert.equal(lookup(dict,undefined),null);

// Prototype keys are not dictionary entries.
assert.equal(lookup(dict,'constructor'),null);
assert.equal(lookup(dict,'__proto__'),null);

console.log('UI translation lookup passed: exact matches, number templates, reordered and rewritten digits refused, misses and prototype keys.');

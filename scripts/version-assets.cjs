// Version static entrypoints so a new Pages deployment cannot mix old/new scripts.
const fs = require('node:fs');
const crypto = require('node:crypto');
const file = 'dist/index.html';
const before = fs.readFileSync(file,'utf8');
const after = before.replace(/(href|src)="([a-z0-9-]+\.(?:css|js))(?:\?v=[a-f0-9]+)?"/g,(_,attribute,asset)=>{
  const version=crypto.createHash('sha256').update(fs.readFileSync('dist/'+asset)).digest('hex').slice(0,12);
  return `${attribute}="${asset}?v=${version}"`;
});
if(process.argv.includes('--check')) {
  if(after!==before){console.error('Run node scripts/version-assets.cjs before committing frontend changes.');process.exit(1);}
  console.log('Asset versions match source files.');
} else fs.writeFileSync(file,after);

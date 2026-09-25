'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const Reports = require('../dist/reports.js');
const fonts = require('../dist/vendor/report-fonts.js');
const exportedAt = '2026-09-25T09:00:00Z';
const base = {mode:'live',exportedAt,items:[]};
const flattenText = value => {
  if (typeof value === 'string') return value;
  if (Array.isArray(value)) return value.map(flattenText).join('');
  if (value && typeof value === 'object') return Object.entries(value).filter(([key])=>['text','content','columns','stack'].includes(key)).map(([,v])=>flattenText(v)).join('\n');
  return '';
};
const build = (kind,input) => Reports.buildDefinition(kind,input,fonts.coverage);
const codeText = '<img src=x onerror="alert(1)"> <script>window.bad=true</script>';
const input = {
  ...base, scope:'Selected source records',items:[
    {id:'archive/2026?x=<data>',title:codeText,status:'Needs review',category:'Unknown model category',date:'Model-returned date - verify against source',source:'Letter.pdf, lines 1-4',amount:0,note:'José\nTiếng Việt\r\nमेरी माँ के लिए पत्र।',details:'Amount requires source review.'},
    {title:'Zero is different from unknown',status:'Saved',amount:null,note:''}
  ]
};
const before = JSON.stringify(input);
const definition = build('plan',input), text = flattenText(definition);
assert.equal(JSON.stringify(input),before,'Report generation must not change source fields.');
assert.ok(text.includes(codeText),'HTML-like user text must remain literal report text.');
assert.ok(text.includes('Model-returned date - verify against source'));
assert.ok(text.includes('Unknown model category'));
assert.ok(text.includes('Letter.pdf, lines 1-4'));
assert.ok(text.includes('José\nTiếng Việt\nमेरी माँ के लिए पत्र।'));
assert.match(text,/Amount0/);
assert.match(text,/AmountNot recorded/);
assert.ok(!text.includes('fictional records'));
assert.equal(definition.info.creationDate.toISOString(),'2026-09-25T09:00:00.000Z');
assert.ok(definition.content.findIndex(node=>flattenText(node).includes('Review original records')) < definition.content.findIndex(node=>node.headlineLevel===1),'Scope notes belong in the introduction, never on an otherwise empty final page.');
assert.match(flattenText(build('plan',{...base,mode:'preview'})),/Sample workspace - fictional records/);
assert.match(flattenText(build('plan',base)),/There are no actions in this view/);
assert.match(flattenText(build('activity',base)),/There are no recorded updates in this view/);
assert.equal(Reports.displayTimestamp('09/10/2026'),'09/10/2026','Ambiguous source dates must not be reinterpreted.');
assert.equal(Reports.displayTimestamp(null),'Not recorded');
assert.equal(Reports.displayTimestamp(exportedAt),'2026-09-25 09:00:00 UTC');
for(const input of [null,{}, {...base,items:null},{...base,items:[null]},{...base,items:[[]]},{...base,mode:'other'},{...base,exportedAt:'yesterday'}]) assert.throws(()=>build('plan',input));
assert.throws(()=>build('unknown',base));

// Font choices keep Hindi clusters together and preserve unsupported glyphs visibly.
const writer = Reports.textWriter(fonts.coverage);
const hindi = writer.text('मेरी माँ के लिए पत्र।',true);
assert.equal(hindi.map(run=>run.text).join(''),'मेरी माँ के लिए पत्र।');
assert.ok(hindi.some(run=>run.font==='Devanagari'));
assert.equal(writer.unsupported.size,0);
assert.equal(writer.text('Español Tiếng Việt').map(run=>run.text).join(''),'Español Tiếng Việt');
assert.equal(writer.text('中\u0000').map(run=>run.text).join(''),'[U+4E2D][U+0000]');
assert.equal(writer.text({text:'unsafe object',link:'https://example.com'}).map(run=>run.text).join(''),'');
assert.match(flattenText(build('plan',{...base,items:[{title:'中'}]})),/Character note/);

async function main() {
  const taskLiteral=fs.readFileSync(path.join(__dirname,'../dist/app.js'),'utf8').match(/^const tasks=(.*);$/m)?.[1];
  assert.ok(taskLiteral,'The real preview fixture must be available for pagination regression.');
  const previewTasks=vm.runInNewContext('('+taskLiteral+')');
  const previewPlan={...base,mode:'preview',scope:'Current plan view. Amounts are historical amounts mentioned in sample records, not money owed or recoverable.',items:previewTasks.map(item=>({id:item.id,title:item.title,status:({review:'Needs review',ready:'Ready',done:'Completed'})[item.status]||item.status,category:item.category,date:item.date,source:item.source,amount:item.value,note:''}))};
  const previewBytes=await Reports.generate('plan',previewPlan);
  if(process.env.AFTERWORD_REPORT_QA_DIR){fs.mkdirSync(process.env.AFTERWORD_REPORT_QA_DIR,{recursive:true});fs.writeFileSync(path.join(process.env.AFTERWORD_REPORT_QA_DIR,'preview-plan.pdf'),previewBytes);}
  assert.equal(previewTasks.length,7);
  assert.ok((Buffer.from(previewBytes).toString('latin1').match(/\/Type \/Page\b/g)||[]).length<=2,'The seven-action preview must not create a third page containing only its scope note.');
  const planItems = Array.from({length:24},(_,index)=>({...input.items[0],title:`Action ${index+1}: ${index===0?codeText:'Review the source records'}`,note:('A saved note about the source. José, Tiếng Việt, और परिवार।\n').repeat(index===3?50:3)}));
  const activityItems = Array.from({length:45},(_,index)=>({text:`Update ${index+1}: Saved a note for José and परिवार`,at:exportedAt,status:index%2?'Reviewed':'Saved',source:'User action in this browser',details:index===2?'Very long text: '+'record'.repeat(400):'Saved source information.'}));
  const outputs = [
    ['plan',await Reports.generate('plan',{...base,items:planItems})],
    ['activity',await Reports.generate('activity',{...base,mode:'preview',items:activityItems})],
    ['empty',await Reports.generate('plan',base)]
  ];
  for(const [name,bytes] of outputs) {
    assert.ok(bytes instanceof Uint8Array);
    const binary = Buffer.from(bytes).toString('latin1');
    assert.match(binary,/^%PDF-1\.[3-7]/);
    assert.match(binary,/%%EOF\s*$/);
    assert.match(binary,/\/FontFile2/,'Unicode fonts must be embedded.');
    assert.match(binary,/\/ToUnicode/,'PDF text must include Unicode mappings.');
    const pageCount = (binary.match(/\/Type \/Page\b/g)||[]).length;
    assert.ok(name==='empty'?pageCount===1:pageCount>2,`${name} must paginate content without clipping.`);
    assert.ok(!/\/JavaScript|\/OpenAction|\/URI\b/.test(binary),'Report input must not create executable or remote content.');
    if(process.env.AFTERWORD_REPORT_QA_DIR) {
      fs.mkdirSync(process.env.AFTERWORD_REPORT_QA_DIR,{recursive:true});
      fs.writeFileSync(path.join(process.env.AFTERWORD_REPORT_QA_DIR,`${name}.pdf`),bytes);
    }
  }

  // Browser download uses application/pdf and a .pdf name, never a print dialog.
  const downloads=[],urls=[],timers=[],loaded=[];
  const context={console,URL:{createObjectURL:blob=>{assert.equal(blob.type,'application/pdf');return 'blob:test';},revokeObjectURL:url=>urls.push(url)},Blob,Uint8Array,setTimeout:fn=>timers.push(fn),AfterwordReportFonts:fonts,pdfMake:{addVirtualFileSystem:()=>{},addFonts:()=>{},createPdf:()=>({getBuffer:cb=>cb(new Uint8Array([37,80,68,70]))})}};
  context.document={currentScript:{src:'https://site.example/afterword-team-102/reports.js?v=1'},head:{appendChild:script=>loaded.push(script.src)},body:{appendChild:anchor=>assert.equal(anchor.hidden,true)},createElement:tag=>{assert.equal(tag,'a');return {click(){downloads.push({name:this.download,url:this.href});},remove(){}};}};
  vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../dist/reports.js'),'utf8'),context);
  const saved = await context.AfterwordReports.downloadPlan(base);
  await context.AfterwordReports.downloadActivity(base);
  assert.equal(saved.filename,'afterword-action-plan.pdf');
  assert.deepEqual(downloads.map(item=>item.name),['afterword-action-plan.pdf','afterword-workspace-activity.pdf']);
  assert.equal(loaded.length,0,'Already available local PDF dependencies must be reused.');
  timers.forEach(fn=>fn());
  assert.deepEqual(urls,['blob:test','blob:test']);

  // A Pages subdirectory resolves local assets beside reports.js, and a failed
  // first load can be retried instead of leaving export permanently broken.
  const requests=[];
  let failNext=true;
  class LocalURL extends URL {}
  LocalURL.createObjectURL=()=> 'blob:lazy';
  LocalURL.revokeObjectURL=()=>{};
  const lazy={console,URL:LocalURL,Blob,Uint8Array,setTimeout:()=>{}};
  lazy.document={currentScript:{src:'https://site.example/team-102/reports.js?v=1'},body:{appendChild:()=>{}},head:{appendChild:script=>{
    requests.push(script.src);
    if(failNext){failNext=false;script.onerror();return;}
    if(script.src.endsWith('pdfmake.min.js')) lazy.pdfMake=context.pdfMake;
    else lazy.AfterwordReportFonts=fonts;
    script.onload();
  }},createElement:()=>({click(){},remove(){}})};
  vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../dist/reports.js'),'utf8'),lazy);
  await assert.rejects(lazy.AfterwordReports.downloadPlan(base),/could not load/);
  await lazy.AfterwordReports.downloadPlan(base);
  assert.deepEqual(requests,[
    'https://site.example/team-102/vendor/pdfmake.min.js',
    'https://site.example/team-102/vendor/pdfmake.min.js',
    'https://site.example/team-102/vendor/report-fonts.js'
  ]);

  const workspace = fs.readFileSync(path.join(__dirname,'../dist/workspace.js'),'utf8');
  assert.match(workspace,/'export-plan':async.*AfterwordReports\.downloadPlan/);
  assert.match(workspace,/'export-ledger':async.*AfterwordReports\.downloadActivity/);
  assert.ok(!workspace.includes('afterword-action-plan.csv'));
  assert.ok(!workspace.includes('afterword-workspace-activity.csv'));
  console.log('PDF export tests passed: source data, Unicode fonts, pagination, empty state, and downloads.');
}
main().catch(error=>{console.error(error);process.exitCode=1;});

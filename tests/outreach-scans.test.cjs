'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const source=fs.readFileSync(path.join(__dirname,'../dist/outreach-scans.js'),'utf8');
const helpers=require('../dist/outreach-scans.js');
assert.equal(helpers.validateScanFile({name:'letter.png',size:200,type:'image/png'}),'');
assert.equal(helpers.validateScanFile({name:'letter.jpeg',size:6000000,type:'image/jpeg'}),'');
assert.match(helpers.validateScanFile({name:'letter.pdf',size:200,type:'application/pdf'}),/PNG or JPEG/);
assert.match(helpers.validateScanFile({name:'letter.png',size:6000001,type:'image/png'}),/6 MB/);
assert.match(helpers.validateScanFile({name:'letter.png',size:0,type:'image/png'}),/non-empty/);
assert.equal(helpers.signatureMatches(Uint8Array.from([137,80,78,71,13,10,26,10]),'image/png'),true);
assert.equal(helpers.signatureMatches(Uint8Array.from([255,216,255]),'image/jpeg'),true);
assert.equal(helpers.signatureMatches(Uint8Array.from([60,115,99,114,105,112,116]),'image/png'),false);
assert.equal(helpers.previewPath('scan-123'),'/scans/scan-123/image');
for(const bad of ['https://evil.example/image','../../secret','scan?token=x',''])assert.throws(()=>helpers.previewPath(bad));
function harness(options={}){
 const elements=new Map(),calls=[],modals=[],messages=[],storage=new Map(),control={connected:true,ocr:true,vision:true,...options};
 class Element{constructor(id){this.id=id;this.value='';this.checked=false;this.disabled=false;this.files=[];this.listeners={};this.isConnected=true;this.textContent='';this.innerHTML='';}addEventListener(type,handler){this.listeners[type]=handler;}}
 const dialog=new Element('detail-dialog');
 function modal(title,body,footer=''){
  for(const el of elements.values())el.isConnected=false;elements.clear();modals.push({title,body,footer});
  const html=body+footer;
  for(const m of html.matchAll(/<[^>]+\bid="([^"]+)"[^>]*>/g)){const el=new Element(m[1]);el.value=m[0].match(/\bvalue="([^"]*)"/)?.[1]||'';el.disabled=/\bdisabled\b/.test(m[0]);elements.set(el.id,el);}
  for(const m of html.matchAll(/<textarea[^>]+id="([^"]+)"[^>]*>([\s\S]*?)<\/textarea>/g))elements.get(m[1]).value=m[2];
 }
 let scan={id:'scan1',filename:'letter.png',provider_id:'cedar-life',date:'2026-09-20',status:'awaiting_review',ocr_text:'Claims: clains@cedar-life.example',raw_ocr_text:'Claims: clains@cedar-life.example',ocr_sha256:'a'.repeat(64),raw_ocr_sha256:'a'.repeat(64),image_sha256:'b'.repeat(64),warnings:[],correction_history:[]};
 const api=async(url,opts)=>{
  calls.push({url,...opts});
  if(url==='/scans/status')return {ocr:{available:control.ocr,reason:control.ocr?'':'Reader unavailable'},image_validation:{available:true},vision:{configured:control.vision},max_bytes:6000000};
  if(url==='/providers')return {providers:[{provider_id:'cedar-life',display_name:'Cedar Life'}],findings:[{id:'insurance',provider_id:'cedar-life'}]};
  if(url==='/scans'&&opts.method==='POST')return {...scan};
  if(url==='/scans/scan1'&&opts.method==='GET')return {...scan};
  if(url==='/scans/scan1'&&opts.method==='PATCH'){
   assert.equal(opts.body.previous_ocr_sha256,scan.ocr_sha256);assert.equal(opts.body.actor,'Priya Rao');
   scan={...scan,ocr_text:opts.body.ocr_text,ocr_sha256:'c'.repeat(64),correction_history:[{actor:opts.body.actor}]};return {...scan};
  }
  if(url==='/scans/scan1/confirm'){
   assert.equal(opts.body.ocr_sha256,scan.ocr_sha256);assert.equal(opts.body.image_sha256,scan.image_sha256);assert.equal(opts.body.confirmed,true);assert.equal(opts.body.actor,'Priya Rao');
   return {status:'extracted',document:{id:'doc-scan1'},contacts:[{kind:'email',value:'claims@cedar-life.example',evidence:{doc_id:'doc-scan1',quote:'claims@cedar-life.example',start:8,end:33}}],processing:'local_ocr_and_vision'};
  }
  throw Error('Unexpected request '+url);
 };
 const bridge={api,getService:()=>control.connected?{service:'afterword-local'}:null,currentDraft:()=>({fields:{writer_name:'Priya Rao'}}),log:()=>{},refreshContacts:()=>{throw Error('Scan navigation must not refresh the previous finding');},openProviderLetter:(provider_id,finding_id)=>calls.push({navigation:{provider_id,finding_id}})};
 const context={window:{AfterwordOutreach:bridge,views:{documents:()=>'<h1>Documents</h1>'},actions:{}},document:{getElementById:id=>id==='detail-dialog'?dialog:elements.get(id)},location:{origin:'http://127.0.0.1:4174'},localStorage:{getItem:key=>storage.get(key)||null,setItem:(key,value)=>storage.set(key,value)},escapeHTML:value=>String(value??'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/"/g,'&quot;'),OutreachCore:require('../dist/outreach-core.js'),modal,button:(text,action)=>`<button data-action="${action}">${text}</button>`,icon:()=>'',render:()=>{},toast:text=>messages.push(text),closeDialog:()=>{},go:()=>{},Uint8Array,btoa:value=>Buffer.from(value,'binary').toString('base64')};
 vm.runInNewContext(source,context);
 const click=async id=>{const element=elements.get(id);assert.ok(element,'Missing UI control '+id);await element.listeners.click({currentTarget:element});};
 return {ui:context.window.AfterwordScans,actions:context.window.actions,view:context.window.views.documents,elements,calls,modals,messages,storage,control,click,dialog};
}
(async()=>{
 const staticMode=harness({connected:false});await staticMode.ui.openUpload();assert.match(staticMode.modals.at(-1).title,/need the local service/);assert.equal(staticMode.calls.length,0,'Static mode must not upload or fake OCR');
 const missingOCR=harness({ocr:false});await missingOCR.ui.openUpload();assert.equal(missingOCR.elements.get('scan-upload').disabled,true);assert.match(missingOCR.elements.get('scan-runtime').innerHTML,/unavailable/);
 const staged=harness({vision:false});await staged.ui.openUpload();assert.equal(staged.elements.get('scan-upload').disabled,false,'OCR staging works before vision is configured');assert.match(staged.elements.get('scan-runtime').innerHTML,/not configured yet/);
 staged.elements.get('scan-file').files=[{name:'letter.png',type:'image/png',size:8,arrayBuffer:async()=>Uint8Array.from([137,80,78,71,13,10,26,10]).buffer}];staged.elements.get('scan-provider').value='cedar-life';staged.elements.get('scan-date').value='2026-09-20';
 assert.equal(staged.calls.filter(c=>c.url==='/scans'&&c.method==='POST').length,0,'Choosing an image alone does not upload it');
 await staged.elements.get('scan-upload-form').listeners.submit({preventDefault(){}});
 assert.equal(staged.calls.filter(c=>c.url==='/scans'&&c.method==='POST').length,1);assert.equal(staged.elements.get('scan-extract').disabled,true);assert.ok(staged.storage.get('afterword-pending-scans-v1').includes('scan1'));
 assert.match(staged.modals.at(-1).body,/\/scans\/scan1\/image/,'Image preview remains on same origin');
 staged.control.vision=true;await staged.click('scan-check-model');assert.equal(staged.elements.get('scan-extract').disabled,false);
 await staged.click('scan-extract');assert.equal(staged.calls.filter(c=>c.url.endsWith('/confirm')).length,0,'A checkbox is required even when the model is ready');assert.match(staged.elements.get('scan-status').textContent,/confirm the review/);
 // A correction invalidates approval and cannot reuse the old text hash.
 staged.elements.get('scan-reviewed').checked=true;const text=staged.elements.get('scan-ocr-text');text.value='Claims: claims@cedar-life.example';text.listeners.input({target:text});
 assert.equal(staged.elements.get('scan-reviewed').checked,false);assert.equal(staged.elements.get('scan-extract').disabled,true);
 await staged.click('scan-extract');assert.equal(staged.calls.filter(c=>c.url.endsWith('/confirm')).length,0,'Unsaved OCR changes never reach extraction');assert.equal(staged.elements.get('scan-extract').disabled,true,'Dirty review remains disabled after rejected attempts');
 await staged.click('scan-save-correction');assert.equal(staged.calls.filter(c=>c.method==='PATCH').length,1);assert.match(staged.modals.at(-1).body,/Original text from the local reader/);assert.equal(staged.elements.get('scan-reviewed').checked,false);
 staged.elements.get('scan-reviewed').checked=true;await staged.click('scan-extract');
 const confirmed=staged.calls.find(c=>c.url.endsWith('/confirm'));assert.equal(confirmed.body.ocr_sha256,'c'.repeat(64));assert.equal(staged.modals.at(-1).title,'Contacts added from your scanned letter');assert.match(staged.modals.at(-1).body,/claims@cedar-life.example/);assert.match(staged.modals.at(-1).footer,/data-finding="insurance"/);assert.equal(JSON.parse(staged.storage.get('afterword-pending-scans-v1')).length,0);
 staged.actions['scan-letter']({dataset:{finding:'insurance',provider:'cedar-life'}});assert.deepEqual(staged.calls.at(-1).navigation,{provider_id:'cedar-life',finding_id:'insurance'},'The actual scan action must name both the provider and target finding');
 const resume=harness();await resume.ui.resumeScan('scan1');assert.equal(resume.modals.at(-1).title,'Compare the text with the scanned letter');assert.equal(resume.calls.filter(c=>c.url==='/scans'&&c.method==='POST').length,0,'Resume loads the staged original; it does not re-upload');
 console.log('Scan workflow passed: actual event handlers enforce local upload consent, file signatures, unavailable engines, OCR correction versioning, fresh review hashes, source evidence and resume behavior.');
})().catch(error=>{console.error(error);process.exitCode=1;});

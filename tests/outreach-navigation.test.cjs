'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),crypto=require('node:crypto').webcrypto;
const source=fs.readFileSync(path.join(__dirname,'../dist/outreach.js'),'utf8');
const C=require('../dist/outreach-core.js'),archive=JSON.parse(fs.readFileSync(path.join(__dirname,'../data/demo_archive.json'),'utf8')),providers=JSON.parse(fs.readFileSync(path.join(__dirname,'../data/providers_directory.json'),'utf8')).providers;
const fields={writer_name:'Priya Rao',writer_phone:'+1 408 555 0100',relationship:'daughter',date_of_death:'2026-09-18'};
const ref=(id,provider_id,last)=>({id,provider_id,kind:'account',masked_identifier:'account ending '+last,source_title:id+'.eml',evidence:[{doc_id:id,quote:'Account number '+last,start:20,end:39}]});
function harness(options={}){
 const calls=[],routes=[],messages=[],elements=new Map(),storage=new Map(),listeners={};
 if(options.saved)storage.set('afterword-outreach-v1',JSON.stringify(options.saved));
 const state={route:'overview',completed:options.completed||[],waiting:[],outreachReview:[],reminders:{},drafts:{},activeTask:'insurance'};
 const control={history:options.history||[],references:[],ingest:[],hold:null};
 const actions={'task-complete':()=>{state.completed=state.completed.includes(state.activeTask)?state.completed.filter(x=>x!==state.activeTask):[...state.completed,state.activeTask];state.waiting=state.waiting.filter(x=>x!==state.activeTask);},'task-wait':()=>{state.waiting=state.waiting.includes(state.activeTask)?state.waiting.filter(x=>x!==state.activeTask):[...state.waiting,state.activeTask];state.completed=state.completed.filter(x=>x!==state.activeTask);}};
 const response=value=>({ok:true,json:async()=>value});
 let clock=Date.now();
 const fetch=async(url,opts={})=>{
  const route=String(url).replace('http://127.0.0.1:4174',''),body=opts.body?JSON.parse(opts.body):undefined;calls.push({route,body,method:opts.method||'GET'});
  if(route==='data/providers_directory.json')return response({providers});
  if(route==='data/demo_archive.json')return response(JSON.parse(JSON.stringify(archive)));
  if(route==='/health')return response({service:'afterword-local',capabilities:{outreach:true}});
  if(route==='/providers')return response({providers,findings:archive.findings});
  if(route==='/outreach')return response({outreach:control.history});
  if(route==='/privacy/outreach')return response({consents:[]});
  if(route==='/integrations/gmail/status')return response({configured:false});
  if(route==='/outreach/session')return response({id:'session-'+body.finding_id});
  if(route==='/providers/resolve'){
   if(control.hold){const pending=control.hold;control.hold=null;await pending;}
   const f=archive.findings.find(f=>f.id===body.finding_id),ids=f.provider_ids||[f.provider_id];
   const candidates=providers.filter(p=>ids.includes(p.provider_id)).map(p=>({...p,source_kind:'directory',channels:[{kind:'email',value:'approved@university.edu'}],evidence:[]}));
   return response({finding_id:f.id,candidates,selected:candidates[0],references:control.references.filter(r=>ids.includes(r.provider_id))});
  }
  if(route==='/documents/ingest')return response(control.ingest.shift()||{document:{id:body.id,provider_id:body.provider_id,text:body.text},contacts:[]});
  if(route==='/outreach/draft'){
   const r=control.references.find(r=>r.id===body.reference_id),f=archive.findings.find(f=>f.id===body.finding_id),p=providers.find(p=>p.provider_id===body.provider_id);
   const d=C.buildDraft({...f,finding_id:f.id,masked_identifier:r?.masked_identifier||''},body.template_id,body.fields,body.recipient,{...p,source_kind:'directory'});
   return response({...d,id:'server-'+(++clock),reference_id:body.reference_id,reference:r||null});
  }
  if(opts.method==='PATCH'&&route.startsWith('/outreach/'))return response({...JSON.parse(JSON.stringify(context.window.AfterwordOutreach.currentDraft())),...body});
  throw Error('Unexpected API route '+route);
 };
 class FormData{constructor(form){this.values=form.values||{};}get(key){return this.values[key]||'';}*[Symbol.iterator](){yield* Object.entries(this.values);}}
 const context={window:{OutreachCore:C,views:{exposure:()=>'',settings:()=>''},actions,addEventListener:()=>{},openImport:()=>{}},state,tasks:archive.findings.map(f=>({id:f.id,title:f.title})),escapeHTML:value=>String(value??'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/"/g,'&quot;'),$:selector=>elements.get(selector)||null,$$:()=>[],icon:()=>'',heading:()=>'',button:()=>'',persist:()=>{},recordActivity:()=>{},render:()=>{},afterRender:()=>{},modal:()=>{},closeDialog:()=>{},toast:value=>messages.push(value),go:route=>{routes.push(route);context.location.hash='#'+route;},location:{origin:'http://127.0.0.1:4174',hash:'#overview'},localStorage:{getItem:key=>storage.get(key)||null,setItem:(key,value)=>storage.set(key,value)},document:{addEventListener:(name,fn)=>(listeners[name]??=[]).push(fn)},fetch,AbortController,setTimeout,clearTimeout,URL,URLSearchParams,TextEncoder,FormData,crypto,performance,console,formatDate:value=>value,formatTime:value=>value,fileSize:value=>value,exposureGroups:[]};
 const instrumented=source.replace('  initialize();\n  render();','  window.__test={initialize,ingestFiles,hydrate:d=>updateTask(d,true),apply:d=>updateTask(d),resolve,getSaved:()=>saved};');
 assert.notEqual(instrumented,source,'Test boot hook must attach to the real module');vm.runInNewContext(instrumented,context);
 const test=context.window.__test,bridge=context.window.AfterwordOutreach;
 const idle=async()=>{for(let i=0;i<8;i++)await new Promise(setImmediate);};
 const ingest=async(providerId,rows)=>{control.ingest=rows;elements.set('#outreach-ingest-files',{files:rows.map((r,i)=>({name:'letter-'+i+'.eml',size:100,text:async()=>r.document?.text||'From: support@valley-storage.example\n\nFictional letter'}))});elements.set('#outreach-ingest-state',{textContent:''});await test.ingestFiles({values:{provider_id:providerId,date:''},querySelector:()=>({disabled:false})});await idle();};
 return {context,control,state,calls,routes,messages,elements,storage,test,bridge,actions,listeners,idle,ingest,init:()=>test.initialize()};
}
(async()=>{
 const h=harness();await h.init();
 // Actual ingest handler routes from the canonical result, not the previously open Insurance action.
 await h.ingest('cedar-clinic',[{document:{id:'clinic-new',provider_id:'cedar-clinic',text:'New clinic letter'},contacts:[]}]);
 assert.match(h.routes.at(-1),/^letters\?finding=medical/);assert.equal(h.bridge.currentDraft().finding_id,'medical');
 assert.equal(h.calls.filter(c=>c.route==='/providers/resolve').at(-1).body.finding_id,'medical');
 await h.ingest('',[{document:{id:'storage-inferred',provider_id:'valley-storage',text:'From: support@valley-storage.example'},contacts:[]}]);
 assert.match(h.routes.at(-1),/^letters\?finding=storage/,'Provider inference returned by the service controls navigation');
 await h.ingest('',[{document:{id:'a',provider_id:'cedar-clinic'},contacts:[]},{document:{id:'b',provider_id:'valley-storage'},contacts:[]}]);
 assert.equal(h.routes.at(-1),'documents','A multi-provider import never chooses an arbitrary letter');
 await h.ingest('',[{document:{id:'unknown'},contacts:[]}]);assert.equal(h.routes.at(-1),'documents');
 // Navigation changes the active finding synchronously and refreshes even when contacts were cached.
 const before=h.calls.filter(c=>c.route==='/providers/resolve'&&c.body.finding_id==='storage').length;
 h.bridge.openProviderLetter('valley-storage','storage');assert.equal(h.bridge.currentDraft().finding_id,'storage');await h.idle();
 assert.equal(h.calls.filter(c=>c.route==='/providers/resolve'&&c.body.finding_id==='storage').length,before+1);
 let release;h.control.hold=new Promise(resolve=>release=resolve);const pending=h.test.resolve('storage',true);await h.idle();h.bridge.openProviderLetter('valley-storage','storage');release();await pending;await h.idle();
 assert.equal(h.calls.filter(c=>c.route==='/providers/resolve'&&c.body.finding_id==='storage').length,before+3,'A forced refresh during an old request reruns after that request');
 // A reference must come from the selected provider; ambiguity requires a real choice.
 h.control.references=[ref('ref-storage-a','valley-storage','7766')];await h.test.resolve('storage',true);
 let d=h.bridge.currentDraft();d.fields=fields;assert.equal(d.reference_choice,'ref-storage-a','A first imported source replaces an automatic empty-reference choice');
 h.control.references.push(ref('ref-storage-b','valley-storage','2233'));await h.test.resolve('storage',true);assert.equal(d.reference_choice,'');assert.equal(d.reference_selection_pending,true);
 let rendered=h.context.window.views.letters();assert.match(rendered,/account ending 7766/);assert.match(rendered,/account ending 2233/);assert.match(rendered,/Matching endings do not establish/);
 const select={id:'outreach-reference',value:'ref-storage-b',dataset:{}};for(const listener of h.listeners.change)listener({target:select});await h.actions['outreach-generate']();await h.idle();
 const generated=h.calls.filter(c=>c.route==='/outreach/draft').at(-1);assert.equal(generated.body.reference_id,'ref-storage-b');assert.equal(generated.body.provider_id,'valley-storage');assert.match(h.bridge.currentDraft().body,/ending 2233/);assert.doesNotMatch(h.bridge.currentDraft().body,/ending 7766/);
 h.control.references=[ref('ref-harbor','harbor-gym','1111'),ref('ref-stream','streamly','2222')];h.bridge.openProviderLetter('harbor-gym','subscriptions');await h.idle();
 d=h.bridge.currentDraft();d.fields=fields;await h.actions['outreach-generate']();await h.idle();h.actions['outreach-recipient']({dataset:{index:'1'}});d=h.bridge.currentDraft();assert.equal(d.provider_id,'streamly');assert.equal(d.reference_choice,'ref-stream');assert.equal(d.reference_selection_pending,true);assert.equal(C.preflight(d).can_handoff,false,'Provider change cannot hand off the old account letter');
 // History hydration respects explicit plan choices and uses lifecycle timestamps, not autosave dates.
 const replied={id:'old-reply',finding_id:'insurance',status:'replied',sent_at:'2026-01-01T00:00:00Z',replied_at:'2026-01-02T00:00:00Z',updated_at:'2026-01-02T00:00:00Z'};
 const manual=harness();manual.test.apply(replied);manual.actions['task-complete']();assert.deepEqual([...manual.state.completed],['insurance']);
 manual.test.hydrate({...replied,updated_at:'2099-01-01T00:00:00Z'});assert.deepEqual([...manual.state.completed],['insurance'],'An autosaved old reply cannot undo a manual completion');
 const reload=harness({completed:['insurance'],saved:JSON.parse(manual.storage.get('afterword-outreach-v1'))});reload.test.hydrate(replied);assert.deepEqual([...reload.state.completed],['insurance'],'Manual choice survives reload');
 const migration=harness({completed:['insurance']});migration.test.hydrate(replied);assert.deepEqual([...migration.state.completed],['insurance'],'Existing completion survives first watermark migration');
 reload.test.apply({...replied,id:'new-sent',status:'waiting',sent_at:new Date().toISOString()});assert.deepEqual([...reload.state.completed],[]);assert.deepEqual([...reload.state.waiting],['insurance'],'A new explicit sent action can update the plan');
 manual.actions['task-wait']();assert.deepEqual([...manual.state.waiting],['insurance']);manual.test.hydrate(replied);assert.deepEqual([...manual.state.waiting],['insurance']);
 console.log('Outreach navigation passed: actual ingest/provider routing, forced refresh races, account-reference selection, and manual lifecycle hydration.');
})().catch(error=>{console.error(error);process.exitCode=1;});

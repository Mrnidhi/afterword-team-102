/* Dialog contract checks with a small DOM fake; no network or Gmail account. */
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');

function harness(connected=true) {
  const elements=new Map(), calls=[], modals=[], stored=[], events=[], control={draftFailures:0};
  class Element {
    constructor(id){this.id=id;this.listeners={};this.value='';this.checked=false;this.disabled=false;this.isConnected=true;}
    addEventListener(type,handler){this.listeners[type]=handler;}
    insertAdjacentHTML(){}
  }
  function modal(title,body,footer='') {
    modals.push(title);elements.clear();
    for(const match of (body+footer).matchAll(/<[^>]+\bid="([^"]+)"[^>]*>/g)) {
      const element=new Element(match[1]);element.value=match[0].match(/\bvalue="([^"]*)"/)?.[1]||'';elements.set(element.id,element);
    }
  }
  const file={id:'file1',name:'reviewed.txt',size:7,sha256:'a'.repeat(64)};
  const snapshot={recipient:'team102+demo@gmail.com',subject:'Information request',body:'Reviewed body',attachments:[],attachment_files:[file]};
  const draft={id:'outreach1',finding_id:'insurance',template_id:'policy_information',fields:{writer_name:'Priya Rao'},origin:'server',...snapshot,attachment_files:[]};
  const consent={id:'fresh-consent',outreach_id:draft.id,actor:'Priya Rao',channel:'gmail_api',snapshot_hash:'new-hash',snapshot,disclosed_fields:['Attachment contents']};
  const api=async(url,options)=>{
    calls.push({url,options});
    if(url==='/integrations/gmail/status')return {configured:connected,connected,draft_scope_granted:connected,reply_tracking_granted:false,permission_notice:'Gmail compose includes send permission.'};
    if(url.endsWith('/review')&&!url.includes('/attachments/'))return {snapshot,snapshot_hash:'new-hash',can_handoff:true,disclosed_fields:['Attachment contents']};
    if(url.includes('/attachments/')&&url.endsWith('/review'))return {id:'file-review-1'};
    if(url.endsWith('/consent')){
      assert.equal(options.body.snapshot_hash,'new-hash');assert.equal(options.body.channel,'gmail_api');return consent;
    }
    if(url.endsWith('/gmail-draft')){
      assert.equal(options.body.consent_id,'fresh-consent');assert.equal(options.body.snapshot_hash,'new-hash');assert.deepEqual([...options.body.attachment_review_ids],['file-review-1']);
      if(control.draftFailures-- > 0)throw Error('Connection interrupted. Check Gmail before retrying.');
      return {draft_id:'gmail1',sender:'owner@gmail.com',subject:snapshot.subject,gmail_url:'https://mail.google.com/mail/#drafts',link_note:'Open Drafts'};
    }
    throw Error('Unexpected request '+url);
  };
  const bridge={api,currentDraft:()=>draft,storeDraft:value=>stored.push(value),log:(...args)=>events.push(args),refreshPrivacy:async()=>{}};
  const context={window:{AfterwordOutreach:bridge},document:{getElementById:id=>elements.get(id)},modal,button:()=>'',URL,URLSearchParams,Uint8Array,btoa:value=>Buffer.from(value,'binary').toString('base64')};
  vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../dist/outreach-integrations.js'),'utf8'),context);
  return {integrations:context.window.AfterwordOutreachIntegrations,elements,calls,modals,stored,events,draft,consent,snapshot,control};
}

(async()=>{
  const h=harness();let completed;
  await h.integrations.gmailDraft({draft:h.draft,onComplete:async value=>{completed=value;}});
  assert.equal(h.calls.filter(call=>call.url.endsWith('/consent')).length,0,'opening final review must not record consent');
  assert.equal(h.stored.at(-1).attachment_files[0].sha256,'a'.repeat(64));
  h.elements.get('integration-actor').value='Priya Rao';
  await h.elements.get('gmail-file-list').listeners.change({target:{dataset:{fileReview:'file1'},checked:true}});
  h.elements.get('gmail-final-confirm').checked=true;
  const create=h.elements.get('gmail-create');
  await create.listeners.click({currentTarget:create});
  assert.equal(completed.consent.id,'fresh-consent');
  assert.equal(completed.draft.attachment_files[0].sha256,'a'.repeat(64));
  assert.equal(completed.consent.snapshot.attachment_files[0].sha256,completed.draft.attachment_files[0].sha256);
  assert.equal(completed.result.draft_id,'gmail1');
  assert.equal(h.modals.at(-1),'Your Gmail draft is ready','completion callback must precede the success dialog');

  // Exercise the actual core completion helper and Mark as sent handler with the
  // attachment-adjusted consent, rather than only checking the callback shape.
  const core=require('../dist/outreach-core.js');
  const source=fs.readFileSync(path.join(__dirname,'../dist/outreach.js'),'utf8');
  const remember=source.match(/  function rememberServerConsent\([^\n]+/)[0];
  const mark=source.match(/  async function confirmSent\([^\n]+/)[0];
  const oldConsent={...completed.consent,id:'older-consent',snapshot:{...completed.consent.snapshot,attachment_files:[]}};
  const saved={consents:[oldConsent]}, apiCalls=[];
  const context={saved,C:core,localSave:()=>true,draft:()=>({...completed.draft,origin:'server'}),api:async(url,options)=>{apiCalls.push({url,options});return {...completed.draft,status:'waiting'};},storeDraft:()=>{},updateTask:()=>{},log:()=>{},recordActivity:()=>{},persist:()=>{},closeDialog:()=>{},render:()=>{},toast:message=>{if(message!=='Marked as sent. A 14-day reminder is in your action plan.')throw Error(message);}};
  vm.runInNewContext(remember+'\n'+mark+'\nthis.rememberServerConsent=rememberServerConsent;this.confirmSent=confirmSent;',context);
  context.rememberServerConsent(completed.consent,completed.draft);
  context.rememberServerConsent(completed.consent,completed.draft);
  assert.equal(saved.consents.length,2,'a repeated completion must not duplicate local consent');
  await context.confirmSent();
  assert.equal(apiCalls[0].options.body.consent_id,'fresh-consent','Mark as sent must use the consent for the exact attachment snapshot');

  const unavailable=harness(false);
  await unavailable.integrations.gmailDraft({draft:unavailable.draft,onComplete:()=>{throw Error('Must not complete');}});
  assert.equal(unavailable.calls.filter(call=>call.url.endsWith('/consent')||call.url.endsWith('/gmail-draft')).length,0,'unconfigured Gmail must not record sharing consent or create a draft');
  assert.equal(unavailable.modals.at(-1),'Gmail connection');
  const retry=harness();retry.control.draftFailures=1;
  await retry.integrations.gmailDraft({draft:retry.draft});
  retry.elements.get('integration-actor').value='Priya Rao';
  await retry.elements.get('gmail-file-list').listeners.change({target:{dataset:{fileReview:'file1'},checked:true}});
  retry.elements.get('gmail-final-confirm').checked=true;
  const retryButton=retry.elements.get('gmail-create');
  await retryButton.listeners.click({currentTarget:retryButton});
  await retryButton.listeners.click({currentTarget:retryButton});
  assert.equal(retry.calls.filter(call=>call.url.endsWith('/consent')).length,1,'retrying an uncertain request must reuse the same consent/idempotency identity');
  console.log('Optional Gmail UI contracts passed: consent timing, attachment snapshot, completion state, Mark as sent consent, unavailable configuration.');
})().catch(error=>{console.error(error);process.exitCode=1;});

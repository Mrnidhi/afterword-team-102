/* Provider outreach. Local templates work on Pages; authenticated same-origin service enables Nano processing. */
(() => {
  'use strict';
  if(window.AfterwordRuntime?.extraction)return;
  const C=window.OutreachCore, KEY='afterword-outreach-v1', esc=escapeHTML;
  let providers=[], archive={findings:[],documents:[]}, service=null, gmailStatus=null, connection='checking', loadError='', activeFinding='insurance', activeTemplate=C.defaults.insurance;
  let validationVisible=false;
  let resolved={}, sessions={}, pending=new Set(), refreshAfterPending=new Set(), contactTargets={}, review=null, saveTimer, syncQueue=Promise.resolve(), localAvailable=true, privacyServer=null;
  const empty=()=>({version:1,config:{runtime:'auto',demo_mailbox:'',confirmed_control:false},drafts:{},consents:[],events:[],verifiedDomains:[],taskSync:{}});
  let saved;
  try { const v=JSON.parse(localStorage.getItem(KEY)||'null'); saved=v&&v.version===1&&v.drafts&&typeof v.drafts==='object'&&!Array.isArray(v.drafts)?{...empty(),...v,config:{...empty().config,...v.config},consents:Array.isArray(v.consents)?v.consents:[],events:Array.isArray(v.events)?v.events:[],verifiedDomains:Array.isArray(v.verifiedDomains)?v.verifiedDomains:[]}:empty(); } catch {saved=empty();}
  if(!saved.taskSync||typeof saved.taskSync!=='object'||Array.isArray(saved.taskSync))saved.taskSync={};
  const key=()=>activeFinding+':'+activeTemplate;
  const finding=id=>archive.findings.find(f=>(f.id||f.finding_id)===id)||{id,finding_id:id,title:tasks.find(t=>t.id===id)?.title||'Request information'};
  const fieldFinding=id=>({...finding(id),finding_id:id,deceased_name:'Arun Rao'});
  const current=()=>Object.hasOwn(saved.drafts,key())?saved.drafts[key()]:null;
  const apiPath=path=>new URL(path,location.origin).href;
  const localSave=()=>{try{localStorage.setItem(KEY,JSON.stringify(saved));localAvailable=true;return true;}catch{localAvailable=false;return false;}};
  function log(kind,draft,extra={}) {saved.events.unshift({id:crypto.randomUUID(),kind,outreach_id:draft?.id||null,finding_id:draft?.finding_id||null,at:new Date().toISOString(),...extra});saved.events=saved.events.slice(0,500);localSave();}
  async function api(path,options={}) {
    if(!service)throw new Error('The local outreach service is not connected.');
    const controller=new AbortController(),timeout=setTimeout(()=>controller.abort(),options.long?120000:12000);
    try {
      const response=await fetch(apiPath(path),{method:options.method||'GET',headers:{Accept:'application/json','X-Afterword-Client':'web',...(options.body?{'Content-Type':'application/json'}:{})},...(options.body?{body:JSON.stringify(options.body)}:{}),signal:controller.signal,credentials:'same-origin',redirect:'error'});
      let value;try{value=await response.json();}catch{throw new Error('The local service returned an unreadable response.');}
      if(!response.ok)throw new Error(typeof value.detail==='string'?value.detail:value.detail?.message||value.error||'The local service could not complete this request.');
      return value;
    } finally {clearTimeout(timeout);}
  }
  function storeDraft(draft,origin) {
    const old=saved.drafts[draft.finding_id+':'+draft.template_id]||{};
    const clean={...old,...draft,fields:{...old.fields,...draft.fields},origin:origin||old.origin||'browser'};
    saved.drafts[clean.finding_id+':'+clean.template_id]=clean;localSave();return clean;
  }
  function makeDraft() {const d=C.buildDraft(fieldFinding(activeFinding),activeTemplate,window.AfterwordProfile?.fields()||{});d.origin='browser';storeDraft(d);return d;}
  function draft(){return current()||makeDraft();}
  function saveHint(message) {const hint=$('#outreach-save-state');if(hint)hint.textContent=message||(!localAvailable?'Session only. Export before leaving.':current()?.origin==='server'?'Saved on the local service and in this browser.':'Saved in this browser.');}
  const lifecycleTime=d=>Date.parse(d.status==='waiting'?d.sent_at:d.replied_at)||0;
  function updateTask(d,hydrate=false) {
    if(!tasks.some(t=>t.id===d.finding_id))return;
    if(!['waiting','review','replied'].includes(d.status))return;
    const id=d.finding_id,at=lifecycleTime(d),event=d.id+':'+d.status+':'+at,previous=saved.taskSync[id];
    if(hydrate){
      // Existing manual completions predate this watermark. Do not replay old outreach over them.
      if(!previous&&state.completed.includes(id)){saved.taskSync[id]={manual_at:Date.now()};localSave();return;}
      if(previous?.manual_at&&(!at||at<=previous.manual_at))return;
      if(previous&&(previous.event===event||previous.applied_at&&at<=previous.applied_at))return;
    }
    state.completed=state.completed.filter(x=>x!==d.finding_id);
    state.waiting=state.waiting.filter(x=>x!==d.finding_id);
    state.outreachReview=(state.outreachReview||[]).filter(x=>x!==d.finding_id);
    if(d.status==='waiting')state.waiting.push(d.finding_id);else state.outreachReview.push(d.finding_id);
    if(d.reminder_date)state.reminders[d.finding_id]=d.reminder_date;
    saved.taskSync[id]={applied_at:at,event};localSave();
    persist();
  }
  function startSession(id){
    if(!service){sessions[id]={opened_at:performance.now()};return Promise.resolve(null);}
    const promise=api('/outreach/session',{method:'POST',body:{finding_id:id}}).then(value=>{sessions[id]={...value,opened_at_client:performance.now()};return value.id;}).catch(()=>null);sessions[id]={promise,opened_at_client:performance.now()};return promise;
  }
  async function syncDraft(d) {
    if(d.origin!=='server')return d;
    if(!service)throw new Error('Reconnect the local service before reviewing this server draft. Your edits are saved in this browser.');
    const revision=d.updated_at, patch={provider_id:selectedProvider(d)||undefined,fields:d.fields,recipient:d.recipient,subject:d.subject,body:d.body,attachments:d.attachments};
    const result=await api('/outreach/'+encodeURIComponent(d.id),{method:'PATCH',body:patch});
    const now=saved.drafts[d.finding_id+':'+d.template_id];
    if(now&&now.updated_at===revision)storeDraft({...result,body_edited:d.body_edited},'server');
    return result;
  }
  function queueSync(d) {
    localSave();saveHint(localAvailable?'Saving…':'Session only. Export before leaving.');clearTimeout(saveTimer);
    saveTimer=setTimeout(()=>{syncQueue=syncQueue.catch(()=>{}).then(()=>syncDraft(d)).then(()=>saveHint()).catch(e=>saveHint('Saved in browser. Service save failed: '+e.message));},650);
  }
  async function flushDraft() {clearTimeout(saveTimer);await syncQueue.catch(()=>{});const d=draft();await syncDraft(d);saveHint();return draft();}
  function emailOf(p){return p?.channels?.find(c=>c.kind==='email')?.value||'';}
  function providerEvidence(p) {
    if(!p)return '<p class="fine">Enter an address you have checked with the provider.</p>';
    const company=p.source_kind==='user'?null:providers.find(item=>item.provider_id===p.provider_id)?.display_name;
    const evidence=(p.evidence||[]).map(e=>{
      const url=C.safeURL(e.url||e.source_url);
      if(url)return `<a class="text-link" href="${esc(url)}" target="_blank" rel="noopener noreferrer">Public source ${icon('external')}</a>`;
      return `<div class="outreach-evidence"><span>${esc(e.doc_id||e.document_id||(p.source_kind==='user'?'Your chosen inbox':'Offline directory'))}${Number.isInteger(e.start)?' · characters '+e.start+'–'+e.end:''}</span>${e.quote?`<blockquote>${esc(e.quote)}</blockquote>`:''}</div>`;
    }).join('');
    return `${company?`<p class="fine">Contact for <strong>${esc(company)}</strong></p>`:''}<p class="outreach-provenance">${icon(p.source_kind==='records'?'files':p.source_kind==='lookup'?'external':'book')}<strong>${esc(C.sourceLabels[p.source_kind]||'Entered by you')}</strong>${typeof p.confidence==='number'?`<span>Source match · ${p.confidence>=0.9?'strong':p.confidence>=0.6?'partial':'needs checking'}</span>`:''}</p>${p.source_kind==='lookup'?'<p class="fine">Check the public source and confirm this address before sharing family details.</p>':''}${evidence}`;
  }
  function localResolve(id) {
    const f=finding(id),wanted=f.provider_ids||[f.provider_id].filter(Boolean), candidates=[];
    for(const p of providers.filter(p=>wanted.includes(p.provider_id))) {
      for(const doc of archive.documents.filter(d=>d.provider_id===p.provider_id)) {
        const text=String(doc.text||''),header=text.split(/\n\s*\n/)[0],tail=text.split('\n').slice(-15).join('\n');
        const segments=[{text:tail,start:text.lastIndexOf(tail)}];
        if(doc.type==='email')for(const m of header.matchAll(/^(?:From|Reply-To|Return-Path):[^\r\n]+/gmi))segments.push({text:m[0],start:m.index});
        for(const seg of segments)for(const m of seg.text.matchAll(/[A-Z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Z0-9.-]+\.[A-Z]{2,}/gi)) {
          const address=m[0],offset=seg.start+m.index;
          if(C.noReply(address)||!(p.domains||[]).includes(C.emailDomain(address)))continue;
          if(candidates.some(c=>c.source_kind==='records'&&emailOf(c)===address))continue;
          candidates.push({...p,source_kind:'records',document_date:doc.date,confidence:1,channels:[{kind:'email',value:address,label:p.label||'Contact',preferred:true}],evidence:[{doc_id:doc.id,quote:address,start:offset,end:offset+address.length}],verified_by_user:false});
        }
      }
      const address=C.demoAddress(approvedMailbox(),p.demo_alias);
      if(address)candidates.push({...p,source_kind:'directory',channels:[{kind:'email',value:address,label:p.label||'Contact',preferred:true}],confidence:1,evidence:[{quote:'Routes to the demo inbox the family approved. This is not the provider’s real contact.'}],verified_by_user:true});
    }
    const ranked=C.rankCandidates(candidates);return {finding_id:id,candidates:ranked,selected:ranked[0]||null,needs_lookup:ranked.length===0};
  }
  function selectedProvider(d){return [d.recipient_provider?.provider_id,d.provider_id,finding(d.finding_id).provider_id].find(id=>providers.some(p=>p.provider_id===id))||null;}
  function referenceOptions(d){return (resolved[d.finding_id]?.references||[]).filter(r=>r.provider_id===selectedProvider(d));}
  function reconcileReference(d){
    if(!service||!resolved[d.finding_id])return;
    const options=referenceOptions(d),valid=id=>options.some(r=>r.id===id);
    const keepChoice=d.reference_choice_explicit||d.reference_id&&d.reference_choice===d.reference_id;
    if(!keepChoice||d.reference_choice!=='omit'&&!valid(d.reference_choice)){
      d.reference_choice=valid(d.reference_id)?d.reference_id:options.length===1?options[0].id:options.length?'':'omit';
    }
    d.reference_selection_pending=!d.reference_choice||d.reference_choice!==(d.reference_id||'omit');
    localSave();
  }
  function chooseProvider(d,p){
    const previous=selectedProvider(d);
    d.recipient=emailOf(p);d.recipient_provider=p;d.provider_id=p.provider_id;
    if(previous!==p.provider_id){delete d.reference_choice;delete d.reference_choice_explicit;d.reference_selection_pending=true;}
    reconcileReference(d);d.updated_at=new Date().toISOString();queueSync(d);
  }
  function referenceField(d){
    if(!service)return '';
    const options=referenceOptions(d),chosen=options.find(r=>r.id===d.reference_choice);
    return `<label class="field"><span>Account reference</span><select id="outreach-reference"><option value="" ${!d.reference_choice?'selected':''} disabled>${pending.has(d.finding_id)?'Reading source references…':'Choose a source reference'}</option>${options.map(r=>`<option value="${esc(r.id)}" ${r.id===d.reference_choice?'selected':''}>${esc(r.masked_identifier)} · ${esc(r.source_title||r.evidence?.[0]?.doc_id||'Source record')}${r.source_date?' · '+esc(r.source_date):''}</option>`).join('')}<option value="omit" ${d.reference_choice==='omit'?'selected':''}>Leave the account reference out</option></select></label><p class="fine">${options.length>1?'Several source records identify an account. Matching endings do not establish that they are the same account. Choose the record for this letter, or leave the reference out.':options.length?'Only the masked reference will appear in your letter.':'No source-backed account reference is available for this provider. The letter can ask how to identify the account securely.'}</p>${chosen?`<p class="fine">Source: ${esc(chosen.source_title||chosen.evidence?.[0]?.doc_id||'Record')}${Number.isInteger(chosen.evidence?.[0]?.start)?' · characters '+chosen.evidence[0].start+'–'+chosen.evidence[0].end:''}</p>`:''}${d.reference_selection_pending||d.reference_review_required?'<p class="outreach-warning">Prepare the letter below to apply this reference choice before sharing.</p>':''}`;
  }
  async function resolve(id=activeFinding,force=false) {
    if(pending.has(id)){if(force)refreshAfterPending.add(id);return;}
    if(resolved[id]&&!force)return;
    pending.add(id);if(state.route==='letters')render();
    try {
      const result=service?await api('/providers/resolve',{method:'POST',body:{finding_id:id}}):localResolve(id);
      resolved[id]=result;
      const d=current();if(id===activeFinding&&d){
        const wanted=contactTargets[id],candidate=wanted?(result.candidates||[]).find(p=>p.provider_id===wanted):result.selected;
        if(candidate&&(!d.recipient||wanted&&selectedProvider(d)!==wanted))chooseProvider(d,candidate);
        else if(wanted&&selectedProvider(d)!==wanted){d.provider_id=wanted;d.recipient='';d.recipient_provider=null;delete d.reference_choice;delete d.reference_choice_explicit;d.reference_selection_pending=true;queueSync(d);}
        reconcileReference(d);delete contactTargets[id];
      }
      loadError='';
    } catch(e){loadError=e.message;}
    finally {pending.delete(id);if(refreshAfterPending.delete(id))await resolve(id,true);else if(state.route==='letters')render();}
  }
  function selectFinding(id,template,options={}) {
    if(!tasks.some(t=>t.id===id))return;
    if(activeFinding!==id||!sessions[id])startSession(id);
    activeFinding=id;activeTemplate=Object.hasOwn(C.templateNames,template)?template:C.defaults[id]||'request_records';
    if(options.provider_id)contactTargets[id]=options.provider_id;
    draft();
    const target='letters?finding='+encodeURIComponent(id)+'&outreach='+encodeURIComponent(activeTemplate);
    go(target);return resolve(id,!!options.force);
  }
  function openProviderLetter(providerId,findingId){
    const target=archive.findings.find(f=>(!findingId||(f.id||f.finding_id)===findingId)&&(f.provider_ids||[f.provider_id]).includes(providerId));
    if(!target){go('documents');toast('Records added. Choose the relevant action in Letters after identifying its provider.');return false;}
    selectFinding(target.id||target.finding_id,undefined,{provider_id:providerId,force:true});return true;
  }
  const oldRoute=window.prepareRoute;
  window.prepareRoute=()=>{
    oldRoute?.();if(state.route!=='letters')return;
    const params=new URLSearchParams(location.hash.split('?')[1]||''),id=params.get('finding')||params.get('template');
    if(id&&tasks.some(t=>t.id===id)){activeFinding=id;activeTemplate=C.defaults[id]||'request_records';}
    const template=params.get('outreach');if(Object.hasOwn(C.templateNames,template))activeTemplate=template;
  };
  function generationText(d) {return ['llm','local_model_guarded'].includes(d.generation?.mode)?'Prepared on the local model. Check each detail against the records.':'Prepared from a local template. No language model was used.';}
  function historyRows(items=saved.consents) {return items.length?items.map(c=>`<article class="outreach-history-row"><div><strong>${esc(c.snapshot?.recipient||c.recipient||'Recipient recorded')}</strong><p>${esc(c.snapshot?.subject||c.subject||'Outreach consent')}</p><small>${esc(formatTime(c.created_at||c.at))} · ${esc(c.actor||'Family member')} · ${esc(({copy:'Copy to clipboard',gmail:'Gmail compose',mailto:'Email app',gmail_api:'Gmail API draft','gmail-draft':'Gmail API draft'})[c.channel]||c.channel||'Handoff')}</small></div><details><summary>Approved content</summary><p>${esc((c.disclosed_fields||[]).join(', ')||'See the exact content below.')}</p><pre>${esc(c.snapshot?.body||c.body||'No body in this record.')}</pre><p class="fine">${c.channel==='copy'?'This records a reviewed clipboard copy. It does not establish that anything was shared externally.':'This records permission to open an external draft.'} It does not prove an email was sent or delivered.</p></details></article>`).join(''):'<div class="inline-empty"><div><strong>No outreach handoffs yet.</strong><p>Reviewing or editing a letter does not disclose it. Reviewed handoffs and copies will appear here.</p></div></div>';}
  function statusBar(d) {
    const handed=saved.consents.find(c=>c.outreach_id===d.id&&Object.hasOwn(c.snapshot||{},'reference_id')&&C.canonicalSnapshot(c.snapshot)===C.canonicalSnapshot(d));
    if(d.status==='waiting')return `<div class="outreach-status"><div><strong>Waiting for a reply</strong><p>You marked this letter as sent ${esc(formatDate(d.sent_at?.slice(0,10)))}. Your reminder: ${esc(formatDate(d.reminder_date))}. This is not a legal deadline.</p></div><div class="button-row"><button class="button" data-action="outreach-replied">They replied</button>${d.origin==='server'?'<button class="text-link" data-action="outreach-check-reply">Check connected Gmail</button>':''}</div></div>`;
    if(['review','replied'].includes(d.status))return '<div class="outreach-status"><div><strong>Reply recorded · needs review</strong><p>Read the provider’s reply and update your action plan. Reply content is not read automatically.</p></div><a class="text-link" href="#plan">View action plan</a></div>';
    return handed?'<div class="outreach-status"><div><strong>Sharing authorized. Sending is still up to you.</strong><p>After you press Send in your email app, mark the letter as sent here.</p></div><button class="button" data-action="outreach-sent">Mark as sent</button></div>':'';
  }
  const fieldSelector=field=>({recipient:'#outreach-recipient',subject:'#outreach-subject',body:'#outreach-body',reference:'#outreach-reference',generate:'[data-action="outreach-generate"]',writer_name:'#outreach-writer',writer_phone:'#outreach-phone',relationship:'#outreach-relationship',date_of_death:'#outreach-date'}[field]||'#outreach-body');
  function validationHTML(check){return check.issues.length?`<p>Complete these details before reviewing:</p><ul>${(check.field_issues||check.issues.map(message=>({field:'body',message}))).map(issue=>`<li><button class="text-link" data-action="outreach-fix-field" data-field="${esc(issue.field)}">${esc(issue.message)}</button></li>`).join('')}</ul>`:'<p>All required details are complete. Review the letter before sharing.</p>';}
  function showValidation(check){validationVisible=true;const node=$('#outreach-validation');if(node)node.innerHTML=validationHTML(check);for(const element of $$('.outreach-workspace [aria-invalid]'))element.removeAttribute('aria-invalid');for(const issue of check.field_issues||[]){const el=$(fieldSelector(issue.field));if(el&&el.matches('input,textarea,select'))el.setAttribute('aria-invalid','true');}const first=$(fieldSelector(check.field_issues?.[0]?.field));first?.focus();first?.scrollIntoView({block:'center',behavior:'auto'});toast('Complete the highlighted details, then review your letter.');}
  function approvedMailbox(){const p=window.AfterwordProfile?.current();return p?.demo_mailbox_confirmed?p.demo_mailbox:saved.config.confirmed_control?saved.config.demo_mailbox:'';}
  function mailboxChoice(d){const mailbox=approvedMailbox();return mailbox?`<div class="outreach-demo-choice"><p>Send a test draft to your approved inbox: <strong>${esc(mailbox)}</strong></p><button class="button" data-action="outreach-use-mailbox">Use approved inbox</button></div>`:`<div class="outreach-demo-choice"><p>The contact in this fictional record cannot receive email.</p><button class="button" data-action="profile-edit">Add an approved inbox in your profile</button></div>`;}
  function applyProfile(replace=false){const d=draft(),fields=window.AfterwordProfile?.fields()||{};for(const [key,value] of Object.entries(fields))if(value&&(replace||!d.fields?.[key]))d.fields={...d.fields,[key]:value};if(!d.body_edited&&d.origin==='browser')d.body=C.buildDraft(fieldFinding(activeFinding),activeTemplate,d.fields,d.recipient,d.recipient_provider).body;d.updated_at=new Date().toISOString();queueSync(d);render();}
  function lettersView() {
    const d=draft(),r=resolved[activeFinding],check=C.preflight(d,{demoMailbox:approvedMailbox(),verifiedDomains:saved.verifiedDomains});
    const options=r?.candidates||[],provider=d.recipient_provider;
    return heading('LETTERS','Make the next conversation easier.','Find the right contact, prepare a short letter, and decide what to share.')+`
      <div class="outreach-layout"><aside class="outreach-aside"><label class="field"><span>Related action</span><select id="outreach-finding">${tasks.map(t=>`<option value="${t.id}" ${t.id===activeFinding?'selected':''}>${esc(t.title)}</option>`).join('')}</select></label><div class="outreach-template-heading">LETTER TEMPLATES</div><div class="outreach-template-list">${Object.entries(C.templateNames).map(([id,title])=>`<button data-action="outreach-template" data-id="${id}" class="${id===activeTemplate?'selected':''}" aria-pressed="${id===activeTemplate}">${esc(title)}${id===activeTemplate?icon('check'):''}</button>`).join('')}</div><div class="outreach-aside-note"><h2>Your words, your decision.</h2><p>Afterword prepares the letter. You review the details and press Send in your email app.</p>${['insurance','medical','storage'].includes(activeFinding)?`<a class="text-link" href="#evidence?finding=${activeFinding}">Review the evidence ${icon('arrow')}</a>`:`<button class="text-link" data-task="${activeFinding}">Review the action ${icon('arrow')}</button>`}</div><p class="fine">${connection==='connected'?'Local outreach service connected.':connection==='checking'?'Checking this site’s local service…':'Browser template mode. Drafts stay in this browser until handoff.'}<br><a href="#settings">Outreach settings</a></p></aside>
      <section class="outreach-workspace" aria-label="Prepare outreach"><div class="outreach-section"><div class="outreach-step-title"><span>1</span><h2>Choose who to contact</h2><button class="text-link" data-action="outreach-resolve" ${pending.has(activeFinding)?'disabled':''}>${pending.has(activeFinding)?'Finding contacts…':'Refresh contacts'}</button></div>${loadError?`<p class="form-error" role="alert">${esc(loadError)} <button class="text-link" data-action="outreach-resolve">Try again</button></p>`:''}
      <label class="field"><span>Recipient email</span><input id="outreach-recipient" type="email" autocomplete="off" value="${esc(d.recipient)}" placeholder="Enter a contact you have verified" maxlength="254"></label>${providerEvidence(provider)}
      ${C.reservedEmail(d.recipient)||!d.recipient?mailboxChoice(d):''}
      <details class="outreach-alternatives"><summary>Use a different address${options.length?' · '+options.length+' found':''}</summary>${options.length?options.map((p,i)=>`<button class="outreach-candidate" data-action="outreach-recipient" data-index="${i}"><strong>${esc(emailOf(p))}</strong><span>${esc(p.display_name)} · ${esc(C.sourceLabels[p.source_kind]||'Contact')}</span>${C.reservedEmail(emailOf(p))?'<small>Reserved example · cannot receive mail</small>':''}</button>`).join(''):'<p>No email contact found in the available records or configured directory.</p>'}<p class="fine">You can also type an address above. <a href="#settings">Configure a demo inbox approved for the demo.</a></p></details>
      ${r?.needs_lookup?`<div class="outreach-lookup"><p>No local contact was found. A public lookup can share only the provider’s name and country.</p><button class="button" data-action="outreach-lookup" ${!service?'disabled':''}>Review a public lookup</button>${!service?'<p class="fine">Public lookup requires the local outreach service. You can enter a verified contact yourself.</p>':''}</div>`:''}</div>
      <div class="outreach-section"><div class="outreach-step-title"><span>2</span><h2>Prepare your letter</h2></div><div class="outreach-profile-link"><p>Use your saved profile details, or enter them below.</p><div class="button-row"><button class="text-link" data-action="outreach-use-profile">Use profile details</button><button class="text-link" data-action="profile-edit">Edit profile</button></div></div><form id="outreach-fields">${referenceField(d)}<div class="fields-two"><label class="field"><span>Your full name</span><input name="writer_name" id="outreach-writer" autocomplete="name" value="${esc(d.fields?.writer_name||'')}" maxlength="120" placeholder="Required"></label><label class="field"><span>Your phone</span><input name="writer_phone" id="outreach-phone" type="tel" autocomplete="tel" value="${esc(d.fields?.writer_phone||'')}" maxlength="60" placeholder="Required"></label><label class="field"><span>Your relationship / authority</span><input name="relationship" id="outreach-relationship" value="${esc(d.fields?.relationship||'')}" maxlength="180" placeholder="For example, daughter; authority not yet confirmed"></label><label class="field"><span>Date of death</span><input name="date_of_death" id="outreach-date" type="date" value="${esc(d.fields?.date_of_death||'')}"></label></div><div class="outreach-generation"><p class="fine">${esc(generationText(d))} Your details are required before handoff.</p><button type="button" class="button" data-action="outreach-generate">${d.body_edited?'Replace letter from these details':'Prepare letter from these details'}</button></div></form>
      <div class="outreach-letter-fields"><label class="field"><span>Subject</span><input id="outreach-subject" value="${esc(d.subject)}" maxlength="200"></label><label class="field"><span>Letter</span><textarea id="outreach-body" rows="16" maxlength="10000">${esc(d.body)}</textarea></label><div class="outreach-letter-meta"><span id="outreach-length">${d.body.length} characters · ${d.body.trim().split(/\s+/).length} words</span><span id="outreach-save-state" role="status">${localAvailable?'Saved in this browser.':'Session only. Export before leaving.'}</span></div></div>
      <details class="outreach-attachments"><summary>Documents you may need to attach</summary><p class="fine">Nothing is attached or uploaded here. Add documents yourself in Gmail only when needed. Ask for a secure portal before sharing sensitive documents.</p>${['Death certificate (PDF)','Evidence of authority'].map(label=>`<label class="outreach-check"><input type="checkbox" data-outreach-attachment="${esc(label)}" ${d.attachments?.includes(label)?'checked':''}><span>Remind me to attach: ${esc(label)}</span></label>`).join('')}</details>
      </div><div class="outreach-section outreach-finish"><div class="outreach-step-title"><span>3</span><h2>Review before sharing</h2></div><p>The next screen shows the exact recipient, subject, letter and attachment reminders. Nothing is sent automatically.</p><div id="outreach-validation" class="outreach-validation" aria-live="polite">${validationVisible?validationHTML(check):'<p>Complete your contact details above, then review the full letter.</p>'}</div><div class="button-row"><button class="button primary" data-action="outreach-review">Review & choose email app ${icon('arrow')}</button><button class="button" data-action="outreach-copy">Copy letter</button></div><div class="outreach-secondary"><button class="text-link" data-action="outreach-download">Download letter</button><button class="text-link" data-action="outreach-print">Print</button><button class="text-link" data-action="outreach-reset">Reset this letter</button></div></div>${statusBar(d)}</section></div>`;
  }
  function rerenderLetterCounts(d){const label=$('#outreach-length');if(label)label.textContent=d.body.length+' characters · '+d.body.trim().split(/\s+/).length+' words';const node=$('#outreach-validation');if(node&&validationVisible){const c=C.preflight(d);node.innerHTML=validationHTML(c);for(const element of $$('.outreach-workspace [aria-invalid]'))element.removeAttribute('aria-invalid');for(const issue of c.field_issues){const el=$(fieldSelector(issue.field));if(el&&el.matches('input,textarea,select'))el.setAttribute('aria-invalid','true');}}}
  function updateDraftValue(target) {
    const d=draft();
    if(target.id==='outreach-reference')return;
    if(target.closest('#outreach-fields')) {
      d.fields=Object.fromEntries(new FormData($('#outreach-fields')));
      if(!d.body_edited&&d.origin==='browser') {const generated=C.buildDraft(fieldFinding(activeFinding),activeTemplate,d.fields,d.recipient,d.recipient_provider);d.body=generated.body;const area=$('#outreach-body');if(area)area.value=d.body;}
    } else if(target.id==='outreach-recipient') {d.recipient=target.value.trim();const options=(resolved[activeFinding]?.candidates||[]),previous=selectedProvider(d);d.recipient_provider=options.find(p=>emailOf(p)===d.recipient&&p.provider_id===previous)||options.find(p=>emailOf(p)===d.recipient)||{source_kind:'user',channels:[{kind:'email',value:d.recipient}],evidence:[],verified_by_user:false};if(d.recipient_provider.provider_id&&d.recipient_provider.provider_id!==previous){d.provider_id=d.recipient_provider.provider_id;delete d.reference_choice;delete d.reference_choice_explicit;reconcileReference(d);}}
    else if(target.id==='outreach-subject')d.subject=target.value;
    else if(target.id==='outreach-body'){d.body=target.value;d.body_edited=true;}
    else if(target.dataset.outreachAttachment){d.attachments=d.attachments.filter(v=>v!==target.dataset.outreachAttachment);if(target.checked)d.attachments.push(target.dataset.outreachAttachment);}
    else return;
    d.updated_at=new Date().toISOString();d.disclosed_fields=C.disclosures(d);queueSync(d);rerenderLetterCounts(d);
  }
  async function generate(force=false) {
    const d=draft();if(d.body_edited&&!force){modal('Replace the edited letter?', '<p>This rebuilds this letter from your saved details. Your manual wording will be replaced.</p>',button('Keep editing','close-modal')+button('Replace letter','outreach-generate-confirm',true));return;}
    const trigger=$('[data-action="outreach-generate"]');if(trigger){trigger.disabled=true;trigger.textContent='Preparing letter…';}
    try {
      if(service){await resolve(activeFinding);reconcileReference(d);if(!d.reference_choice)throw Error('Choose the source account reference or explicitly leave it out before preparing the letter.');}
      const sessionId=sessions[activeFinding]?.promise?await sessions[activeFinding].promise:sessions[activeFinding]?.id;
      const generated=service?await api('/outreach/draft',{method:'POST',body:{finding_id:activeFinding,provider_id:selectedProvider(d)||undefined,reference_id:d.reference_choice||undefined,session_id:sessionId||undefined,template_id:activeTemplate,fields:d.fields,recipient:d.recipient||undefined},long:true}):C.buildDraft(fieldFinding(activeFinding),activeTemplate,d.fields,d.recipient,d.recipient_provider);
      storeDraft({...generated,attachments:d.attachments,body_edited:false,reference_choice:generated.reference_id||'omit',reference_selection_pending:false},service?'server':'browser');log('draft_prepared',generated,{generation_mode:generated.generation?.mode||'template'});closeDialog();render();toast('Letter prepared. Review the details before sharing.');
    } catch(e){loadError=e.message;render();toast('Could not prepare the letter. Your previous draft is preserved.');}
  }
  function reviewHTML(d,check) {
    const attachments=check.snapshot.attachments;
    return `<div class="outreach-review"><p>These exact details will leave this workspace when you open your email app. You still press Send there.</p><dl class="outreach-review-envelope"><div><dt>From</dt><dd>Chosen in your email app · not verified by Afterword</dd></div><div><dt>To</dt><dd>${esc(d.recipient)}</dd></div><div><dt>Source</dt><dd>${esc(C.sourceLabels[d.recipient_provider?.source_kind]||'Entered by you')}</dd></div><div><dt>Subject</dt><dd>${esc(d.subject)}</dd></div></dl>${providerEvidence(d.recipient_provider)}<p class="outreach-sender-note">Gmail may use the account already signed in to this browser. Check the From address there before sending. For a team demonstration, use your team mailbox.</p><h3>Full letter</h3><pre class="outreach-review-body">${esc(d.body)}</pre><h3>Attachments</h3>${d.attachment_files?.length?'<ul>'+d.attachment_files.map(f=>'<li>'+esc(f.name)+' · '+fileSize(f.size)+' · SHA-256 '+esc(f.sha256)+'</li>').join('')+'</ul><p>These files are staged for the Gmail API draft only. Compose links do not attach files.</p>':''}${attachments.length?`<ul>${attachments.map(v=>`<li>${esc(v)} — attach it yourself in the email app</li>`).join('')}</ul>`:'<p>No attachments selected. No files will be attached by the compose link.</p>'}<div class="outreach-sharing"><h3>What you’re sharing</h3><p>${esc(check.disclosed_fields.join(', ')||'The full text shown above.')}. Any other text you entered is also included exactly as shown.</p><p class="fine">Full Social Security numbers, account numbers and dates of birth are blocked when detected. Check the full letter yourself; this check is not a guarantee.</p></div>${check.domain_warning?'<p class="outreach-warning">This recipient is outside your configured demo inbox and verified domains. Do not send test mail to a real provider. For this fictional case, use an approved demo inbox.</p>':''}${check.recipient_confirmation_required?`<label class="outreach-check outreach-confirm"><input id="outreach-recipient-confirm" type="checkbox"><span>I checked this recipient${d.recipient_provider?.source_kind==='lookup'?' against the linked public source':''} and confirm it is an inbox I control or am authorized to contact.</span></label>`:''}${check.issues.length?`<div class="form-error" role="alert"><strong>Before handoff</strong><ul>${check.issues.map(v=>`<li>${esc(v)}</li>`).join('')}</ul></div>`:''}${!check.compose_available?'<p class="outreach-warning">This letter is 1,500 characters or longer. Compose links may truncate it. Copy the full letter and paste it into your email app, or use a connected Gmail API draft.</p>':''}<p class="fine">Consent is recorded for this exact version. Editing the recipient, subject, body or attachments requires another review. Opening Gmail does not mark this letter as sent.</p><label class="outreach-check"><input id="outreach-sender-confirm" type="checkbox"><span>I will verify the sending account in my email app before pressing Send.</span></label><div id="outreach-review-error" role="alert"></div></div>`;
  }
  async function showReview() {
    try {
      const d=await flushDraft(),client=C.preflight(d,{demoMailbox:approvedMailbox(),verifiedDomains:saved.verifiedDomains});
      if(!client.can_handoff){showValidation(client);return;}
      let check={...client};
      if(d.origin==='server') {
        const backend=await api('/outreach/'+encodeURIComponent(d.id)+'/review',{method:'POST',body:{}});
        if(C.canonicalSnapshot(backend.snapshot)!==C.canonicalSnapshot(d))throw new Error('The saved draft changed. Reload the draft and review the updated content.');
        check={...client,...backend,issues:[...new Set([...client.issues,...(backend.issues||[]),...(backend.blocked_fields?.length?['Remove blocked fields: '+backend.blocked_fields.join(', ')]:[]),...(backend.placeholders?.length?['Fill the remaining placeholders.']:[])])],can_handoff:client.can_handoff&&backend.can_handoff,compose_available:client.compose_available,recipient_confirmation_required:client.recipient_confirmation_required||backend.recipient_confirmation_required,domain_warning:client.domain_warning};
      }
      if(!check.can_handoff){showValidation(check);return;}
      log('draft_reviewed',d,{elapsed_ms:sessions[activeFinding]?(performance.now()-(sessions[activeFinding].opened_at_client||sessions[activeFinding].opened_at)):null,measurement_environment:'browser'});
      const frozen=JSON.parse(JSON.stringify(d));review={draftId:d.id,serialized:C.canonicalSnapshot(d),draft:frozen,check};
      modal('Review what you’re about to share',reviewHTML(frozen,check),`<button class="button" data-action="close-modal">Back to edit</button><button class="button" data-action="outreach-review-copy">Copy letter</button><button class="button" data-action="outreach-mailto" ${!check.can_handoff||!check.compose_available?'disabled':''}>Use my email app</button><button class="button primary" data-action="outreach-gmail" ${!check.can_handoff||!check.compose_available?'disabled':''}>Open in Gmail ${icon('external')}</button>${service&&d.origin==='server'?`<button class="button" data-action="outreach-gmail-draft" ${!check.can_handoff?'disabled':''}>Create Gmail draft</button>`:''}`);
    } catch(e){toast(e.message);}
  }
  async function hashSnapshot(s){if(!crypto.subtle)throw new Error('A secure browser context is required to record consent.');const bytes=await crypto.subtle.digest('SHA-256',new TextEncoder().encode(C.canonicalSnapshot(s)));return [...new Uint8Array(bytes)].map(v=>v.toString(16).padStart(2,'0')).join('');}
  function reviewStillValid() {
    if(!review||draft().id!==review.draftId||C.canonicalSnapshot(draft())!==review.serialized)throw new Error('The letter changed after review. Close this dialog and review it again.');
    const latest=C.preflight(draft(),{demoMailbox:approvedMailbox(),verifiedDomains:saved.verifiedDomains});
    if(!latest.can_handoff||!review.check.can_handoff)throw new Error('Complete the missing details and remove blocked fields before handoff.');
    if(review.check.recipient_confirmation_required&&!$('#outreach-recipient-confirm')?.checked)throw new Error('Confirm the recipient above before continuing.');
  }
  async function consent(channel) {
    reviewStillValid();const d=review.draft;
    const row=d.origin==='server'?await api('/outreach/'+encodeURIComponent(d.id)+'/consent',{method:'POST',body:{snapshot_hash:review.check.snapshot_hash,actor:d.fields.writer_name,channel,recipient_confirmed:$('#outreach-recipient-confirm')?.checked||!review.check.recipient_confirmation_required}}):{id:crypto.randomUUID(),outreach_id:d.id,snapshot_hash:await hashSnapshot(d),actor:d.fields.writer_name,channel,snapshot:C.snapshot(d),disclosed_fields:C.disclosures(d),created_at:new Date().toISOString(),recipient_confirmed:$('#outreach-recipient-confirm')?.checked||false};
    saved.consents.unshift({...row,outreach_id:d.id,snapshot:row.snapshot||C.snapshot(d),disclosed_fields:row.disclosed_fields||C.disclosures(d)});if(!localSave()&&d.origin!=='server'){saved.consents.shift();throw new Error('Consent could not be saved. Free browser storage and try again before sharing.');}log('handoff_authorized',d,{channel});return row;
  }
  function rememberServerConsent(row,d){if(!saved.consents.some(c=>c.id===row.id))saved.consents.unshift({...row,outreach_id:d.id,snapshot:row.snapshot||C.snapshot(d),disclosed_fields:row.disclosed_fields||C.disclosures(d)});localSave();}
  function reviewError(error) {const node=$('#outreach-review-error');if(node){node.className='form-error';node.textContent=error.message;}else toast(error.message);}
  async function handoff(channel) {
    let target;
    try {
      if(window.AfterwordRuntime?.offline&&!window.AfterwordRuntime?.preview)throw new Error('Email handoffs are unavailable in this offline workspace. You can review and copy the letter locally.');
      reviewStillValid();if(!$('#outreach-sender-confirm')?.checked)throw new Error('Confirm that you will check the sending account before opening your email app.');if(!review.check.compose_available)throw new Error('This letter is too long for a compose link. Copy it instead.');
      // Open synchronously while the user gesture is active. Detach opener before navigating.
      if(channel==='gmail') {target=window.open('about:blank','_blank');if(!target)throw new Error('Your browser blocked the new tab. Allow pop-ups for Afterword, or copy the letter.');target.opener=null;}
      const row=await consent(channel),url=channel==='gmail'?C.gmailURL(review.draft):C.mailtoURL(review.draft);
      if(target)target.location.replace(url);else {const anchor=document.createElement('a');anchor.href=url;anchor.rel='noopener';anchor.click();}
      log('handoff_opened',review.draft,{channel,consent_id:row.id});closeDialog();render();toast('Email draft opened. After you send it, choose Mark as sent.');
    } catch(e){if(target)target.close();reviewError(e);}
  }
  async function copyText(content) {
    try {await navigator.clipboard.writeText(content);toast('Letter copied. Paste it into your email app when ready.');}
    catch {modal('Copy your letter',`<p>Select and copy the complete letter below.</p><textarea id="outreach-copy-text" rows="14" readonly>${esc(content)}</textarea>`,button('Done','close-modal'));$('#outreach-copy-text').select();}
  }
  function letterText(d){return 'To: '+d.recipient+'\nSubject: '+d.subject+'\n\n'+d.body;}
  async function markSent() {
    try {const d=await flushDraft(),latest=saved.consents.find(c=>c.outreach_id===d.id&&Object.hasOwn(c.snapshot||{},'reference_id')&&C.canonicalSnapshot(c.snapshot)===C.canonicalSnapshot(d));
      if(!latest)throw new Error('Review this exact letter and open your email app first.');
      modal('Did you send this letter?',`<p>Only choose this after pressing Send in your email app.</p><p><strong>To:</strong> ${esc(d.recipient)}</p><p>A reminder will be added to your plan for 14 days from today. It is your reminder, not a legal deadline.</p>`,button('Not yet','close-modal')+button('I sent it','outreach-confirm-sent',true));
    }catch(e){toast(e.message);}
  }
  async function confirmSent() {try {const d=draft(),latest=saved.consents.find(c=>c.outreach_id===d.id&&Object.hasOwn(c.snapshot||{},'reference_id')&&C.canonicalSnapshot(c.snapshot)===C.canonicalSnapshot(d));const next=d.origin==='server'?await api('/outreach/'+encodeURIComponent(d.id)+'/sent',{method:'POST',body:{confirmed_sent:true,actor:d.fields.writer_name,consent_id:latest.id}}):C.markSent(d,latest);storeDraft(next,d.origin);updateTask(next);log('marked_sent',next);recordActivity('Marked outreach to '+(next.recipient||'provider')+' as sent');persist();closeDialog();render();toast('Marked as sent. A 14-day reminder is in your action plan.');}catch(e){toast(e.message);}}
  async function replied(){try {const d=draft(),next=d.origin==='server'?await api('/outreach/'+encodeURIComponent(d.id)+'/replied',{method:'POST',body:{confirmed_replied:true,actor:d.fields.writer_name}}):C.markReplied(d);storeDraft(next,d.origin);updateTask(next);log('reply_recorded',next);recordActivity('Recorded a provider reply; action needs review');persist();render();toast('Reply recorded. This action now needs review.');}catch(e){toast(e.message);}}
  const previousPrivacy=window.views.exposure,previousSettings=window.views.settings;
  function privacyView() {
    const items=[...(privacyServer?.consents||[]),...saved.consents].filter((c,i,all)=>all.findIndex(v=>v.id===c.id)===i).sort((a,b)=>Date.parse(b.created_at||b.at)-Date.parse(a.created_at||a.at));
    const copies=items.filter(c=>c.channel==='copy').length,emails=items.length-copies;
    const shared=items.length?`${emails} authorized email handoff${emails===1?'':'s'}; ${copies} reviewed clipboard cop${copies===1?'y':'ies'}.`:'No email handoffs or reviewed copies recorded.';
    return heading('YOUR INFORMATION','Privacy','Review where your information is stored and what you chose to share.',button('Export privacy report','export-exposure',false,'download'))+`<div class="privacy-practical"><section class="settings-panel"><h2>Storage and sharing</h2><dl class="privacy-facts"><div><dt>Saved in this browser</dt><dd>Notes, reminders, progress, outreach drafts and consent history.<small>Browser storage is unencrypted. Use fictional details in this demo.</small></dd></div><div><dt>Local outreach service</dt><dd>${service?'Connected on this website’s origin.':'Not connected.'}<small>${service?'Selected text records, scan images, raw OCR, saved corrections, drafts and consent history are stored by your local service. Scan images and OCR text are not saved in browser storage. Model processing depends on its configured runtime.':'Letters use local templates. No language model is connected in browser mode.'}</small></dd></div><div><dt>Reviewed handoffs and copies</dt><dd>${shared}<small>Opening Gmail shares the reviewed text with Google. A mailto handoff shares it with your email app. Afterword does not send the message. A clipboard copy does not prove external disclosure.</small></dd></div><div><dt>Attachments</dt><dd>Compose links include no files.<small>Checklist items are reminders. You choose files in the email app; connected Gmail API drafts may include files you explicitly select and review.</small></dd></div></dl><a class="text-link" href="#settings">Manage outreach settings ${icon('arrow')}</a></section><section class="privacy-sources"><h2>Details in the sample records</h2><p class="fine">These categories describe the fictional archive. They are not a live scan.</p>${exposureGroups.map(g=>`<details class="privacy-category"><summary>${g.title}</summary><p>${g.details}</p>${g.sources.map(documentLink).join('')}</details>`).join('')}</section></div><section class="settings-panel outreach-history"><div class="section-title"><div><h2>Outreach</h2><p class="fine">The intended recipient, approved content and the person who authorized each handoff or copy.</p></div>${button('Export outreach','outreach-export',false,'download')}</div>${historyRows(items)}<p class="fine">${service?'Local service records and browser records may differ if a handoff was made in browser-only mode. Export preserves both.':'This history is editable browser storage, not an immutable audit log.'} Gmail compose links do not provide delivery receipts. ${saved.events.filter(e=>e.kind==='reply_recorded').length} replies manually recorded in this browser.</p></section>`;
  }
  function outreachSettings() {
    return `<section class="settings-panel outreach-settings"><h2>Provider outreach</h2><p>Choose an inbox you have permission to use for the demo. Gmail contacts use plus-address aliases; other domains use the exact approved inbox; they never point at real fictional-provider addresses.</p><form id="outreach-settings-form"><label class="field"><span>Outreach runtime</span><select name="runtime"><option value="auto" ${saved.config.runtime==='auto'?'selected':''}>Use this site’s local service when available</option><option value="browser" ${saved.config.runtime==='browser'?'selected':''}>Browser templates only</option></select></label><p class="fine">${connection==='connected'?'Local service connected on '+esc(location.origin):connection==='checking'?'Checking this site for the local service…':'No local service connected. Browser templates and Gmail compose work without one.'} No records are sent to another host for processing.</p>${window.AfterwordProfile?`<p><strong>Recipient for test letters:</strong> ${esc(approvedMailbox()||'Not configured')}</p><p class="fine">Your profile holds the approved recipient. The sending account is chosen separately in your email app.</p><button class="text-link" type="button" data-action="profile-edit">Edit profile and demo inbox</button>`:`<label class="field"><span>Approved demo inbox</span><input type="email" name="demo_mailbox" id="outreach-demo-mailbox" value="${esc(saved.config.demo_mailbox)}" placeholder="Your actual team inbox" maxlength="254" autocomplete="off"></label><label class="outreach-check"><input type="checkbox" name="confirmed_control" ${saved.config.confirmed_control?'checked':''}><span>I have permission to use this inbox for the demo.</span></label><p class="fine">Leave the inbox empty to remove demo aliases. An address is never assumed to belong to Team 102.</p>`}<button class="button" type="submit">Save outreach settings</button><span id="outreach-settings-state" role="status"></span></form><div class="outreach-connection-actions"><button class="text-link" data-action="outreach-reconnect">Check local service again</button>${service?'<button class="text-link" data-action="outreach-gmail-settings">Gmail draft connection</button>':''}</div><p class="fine">Reset demo clears browser outreach drafts and history. It does not delete records held by the local service.</p></section>`;
  }
  function settingsView(){return (service?previousSettings().replace('It makes no AI requests and has no analytics or account integration.','Local outreach can read selected records and use the configured model. Email connections require separate permission.'):previousSettings())+outreachSettings();}
  async function loadPrivacy(){if(!service)return;try{privacyServer=await api('/privacy/outreach');for(const row of privacyServer.consents||[])if(!saved.consents.some(c=>c.id===row.id))saved.consents.push(row);localSave();if(['exposure','letters'].includes(state.route))render();}catch(e){toast('Could not load service outreach history: '+e.message);}}
  async function initialize(force=false) {
    connection='checking';service=null;gmailStatus=null;loadError='';
    if(force&&state.route==='settings')render();
    try {
      const results=await Promise.allSettled([fetch('data/providers_directory.json',{redirect:'error'}).then(r=>{if(!r.ok)throw Error('Directory unavailable');return r.json();}),fetch('data/demo_archive.json',{redirect:'error'}).then(r=>{if(!r.ok)throw Error('Sample archive unavailable');return r.json();})]);
      if(results[0].status==='fulfilled')providers=results[0].value.providers||[];
      if(results[1].status==='fulfilled')archive=results[1].value;
      for(const existing of Object.values(saved.drafts)){if(existing.origin==='browser'&&!existing.body_edited&&!existing.fields?.writer_name&&!saved.consents.some(c=>c.outreach_id===existing.id)){const refreshed=C.buildDraft(fieldFinding(existing.finding_id),existing.template_id,existing.fields,existing.recipient,existing.recipient_provider);storeDraft({...existing,body:refreshed.body,subject:refreshed.subject});}}
      if(results.some(r=>r.status==='rejected'))loadError='The sample contact data could not be loaded. Reload the page or enter a verified address.';
      if(saved.config.runtime!=='browser') {
        const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),4000);
        try {const r=await fetch(apiPath('/health'),{headers:{Accept:'application/json'},signal:controller.signal,redirect:'error',credentials:'same-origin'});if(r.ok){const health=await r.json();if(health.service==='afterword-local'&&health.capabilities?.outreach===true){service=health;connection='connected';if(C.validEmail(health.demo_mailbox)){saved.config.demo_mailbox=health.demo_mailbox;saved.config.confirmed_control=true;}}}}catch{}finally{clearTimeout(timer);}
      }
      if(service){
        const results=await Promise.allSettled([api('/providers'),api('/outreach'),api('/integrations/gmail/status')]);
        if(results[2].status==='fulfilled')gmailStatus=results[2].value;
        if(results[0].status==='fulfilled'){providers=results[0].value.providers||providers;archive.findings=results[0].value.findings||archive.findings;}
        if(results[1].status==='fulfilled')for(const d of [...(results[1].value.outreach||[])].sort((a,b)=>lifecycleTime(a)-lifecycleTime(b))){const stored=saved.drafts[d.finding_id+':'+d.template_id];if(!stored||Date.parse(d.updated_at)>=Date.parse(stored.updated_at))storeDraft(d,'server');updateTask(d,true);}
        else loadError='Could not reload local service drafts. Browser edits have been preserved.';
      }
    } finally {if(connection==='checking')connection='browser';resolved={};localSave();if(['letters','settings','exposure'].includes(state.route))render();if(state.route==='letters'){startSession(activeFinding);resolve(activeFinding);}if(['letters','exposure'].includes(state.route))loadPrivacy();}
  }
  async function saveSettings(form) {
    const values=new FormData(form),mailbox=window.AfterwordProfile?approvedMailbox():String(values.get('demo_mailbox')||'').trim(),confirmed=window.AfterwordProfile?!!mailbox:values.get('confirmed_control')==='on';
    if(mailbox&&(!C.validEmail(mailbox)||C.reservedEmail(mailbox))){toast('Enter a real inbox that you control.');return;}
    if(mailbox&&!confirmed){toast('Confirm permission to use the demo inbox before saving.');return;}
    const config={runtime:values.get('runtime')==='browser'?'browser':'auto',demo_mailbox:mailbox,confirmed_control:!!mailbox&&confirmed};
    try {if(service&&config.runtime==='auto')await api('/settings/demo-mailbox',{method:'POST',body:{email:mailbox,confirmed_control:!!mailbox&&confirmed}});saved.config=config;localSave();await initialize(true);toast('Outreach settings saved. Refresh contacts to use your demo aliases.');}
    catch(e){toast(e.message);}
  }
  function exportOutreach(){exportFile('afterword-outreach-history.json',JSON.stringify({exported_at:new Date().toISOString(),notice:'Consent records authorize drafts only; they do not prove delivery. Browser records are editable.',browser:{outreach:Object.values(saved.drafts),consents:saved.consents,events:saved.events},local_service:privacyServer},null,2),'application/json');}
  async function lookupDialog(){
    const f=finding(activeFinding),p=providers.find(p=>p.provider_id===f.provider_id);
    if(!service||!p){toast('Choose a known provider or enter a contact you have verified.');return;}
    if(window.AfterwordOutreachIntegrations?.lookup){await window.AfterwordOutreachIntegrations.lookup({finding_id:activeFinding,provider:p,onComplete:()=>resolve(activeFinding,true)});return;}
    modal('Review a public contact lookup',`<p>This request contains only the provider’s public name and country.</p><dl class="outreach-review-envelope"><div><dt>Company</dt><dd>${esc(p.display_name)}</dd></div><div><dt>Country</dt><dd>${esc(p.country||'US')}</dd></div></dl><p class="fine">No family names, policy numbers, amounts, document excerpts or personal fields are included. Returned addresses need your verification.</p><p>The lookup connection is not configured in this interface. You can enter a verified contact yourself.</p>`,button('Keep working locally','close-modal'));
  }
  Object.assign(window.views,{letters:lettersView,exposure:privacyView,settings:settingsView});
  Object.assign(window.actions,{
    'finding-letter':()=>selectFinding(state.selectedFinding),
    'outreach-template':a=>selectFinding(activeFinding,a.dataset.id),
    'outreach-resolve':()=>resolve(activeFinding,true),
    'outreach-recipient':a=>{const p=resolved[activeFinding]?.candidates[Number(a.dataset.index)];if(!p)return;const d=draft();chooseProvider(d,p);render();},
    'outreach-generate':()=>generate(),
    'outreach-generate-confirm':()=>generate(true),
    'outreach-review':()=>showReview(),
    'outreach-fix-field':a=>{const element=$(fieldSelector(a.dataset.field));element?.focus();element?.scrollIntoView({block:'center',behavior:'auto'});},
    'outreach-use-profile':()=>{if(!window.AfterwordProfile?.current()){go('profile');return;}applyProfile(true);toast('Profile details applied. Review the letter before sharing.');},
    'outreach-use-mailbox':()=>{const address=approvedMailbox();if(!address){go('profile');return;}const d=draft();d.recipient=address;d.recipient_provider={provider_id:selectedProvider(d),source_kind:'user',channels:[{kind:'email',value:address}],evidence:[{quote:'Approved demo inbox from your profile. Not a provider contact.'}],verified_by_user:true};d.updated_at=new Date().toISOString();queueSync(d);render();},
    'outreach-gmail':()=>handoff('gmail'),
    'outreach-mailto':()=>handoff('mailto'),
    'outreach-copy':()=>showReview(),
    'outreach-review-copy':async()=>{try{await consent('copy');await copyText(letterText(review.draft));}catch(e){reviewError(e);}},
    'outreach-download':()=>exportFile('afterword-'+activeFinding+'-letter.txt',letterText(draft())),
    'outreach-print':()=>{modal('Letter preview',`<div class="outreach-print"><p>To: ${esc(draft().recipient)}</p><h3>${esc(draft().subject)}</h3><pre>${esc(draft().body)}</pre></div>`,button('Close','close-modal')+button('Print','print-page',true));},
    'outreach-reset':()=>modal('Reset this letter?', '<p>This restores the template and clears its personal details. Other drafts and past consent records stay available.</p>',button('Keep editing','close-modal')+button('Reset letter','outreach-reset-confirm',true)),
    'outreach-reset-confirm':()=>{delete saved.drafts[key()];localSave();closeDialog();render();},
    'outreach-sent':()=>markSent(),
    'outreach-confirm-sent':()=>confirmSent(),
    'outreach-replied':()=>replied(),
    'outreach-check-reply':async()=>{try{if(!window.AfterwordOutreachIntegrations?.checkReply)throw Error('Gmail reply tracking is not configured. You can record a reply manually.');await window.AfterwordOutreachIntegrations.checkReply({draft:draft(),onComplete:async result=>{if(result.replied){const value=await api('/outreach'),fresh=(value.outreach||[]).find(d=>d.id===draft().id);if(fresh){storeDraft(fresh,'server');updateTask(fresh);render();}}}});}catch(e){toast(e.message);}},
    'outreach-export':()=>exportOutreach(),
    'outreach-reconnect':()=>initialize(true),
    'outreach-lookup':()=>lookupDialog(),
    'outreach-gmail-settings':()=>window.AfterwordOutreachIntegrations?.gmailSettings?.()||toast('Gmail API drafts require local OAuth configuration. Gmail compose works without it.'),
    'outreach-gmail-draft':async()=>{try{reviewStillValid();if(!window.AfterwordOutreachIntegrations?.gmailDraft)throw Error('Gmail API connection is not configured. Use Open in Gmail instead.');await window.AfterwordOutreachIntegrations.gmailDraft({draft:review.draft,onComplete:({draft:completed,consent:row})=>{storeDraft(completed,'server');rememberServerConsent(row,completed);closeDialog();render();}});}catch(e){reviewError(e);}},
    'export-exposure':()=>exportFile('afterword-privacy-report.json',JSON.stringify({exported_at:new Date().toISOString(),browserStorage:'unencrypted',localService:!!service,notice:'Outreach authorization is not a delivery receipt.',categories:exposureGroups,browserOutreach:{drafts:Object.values(saved.drafts),consents:saved.consents,events:saved.events},serviceOutreach:privacyServer},null,2),'application/json'),
    'export-workspace':()=>exportFile('afterword-workspace.json',JSON.stringify({version:4,exportedAt:new Date().toISOString(),workspace:AfterwordStore.clean(state),outreach:saved,notice:'Contains personal draft text and editable browser history. Store the export safely.'},null,2),'application/json')
  });
  for(const action of ['task-complete','task-wait']){
    const original=window.actions[action];
    window.actions[action]=(...args)=>{
      const id=state.activeTask;
      original?.(...args);
      if(tasks.some(t=>t.id===id)){
        // Record the user's decision, including Resume and Undo, independently of old draft edits.
        saved.taskSync[id]={...saved.taskSync[id],manual_at:Date.now()};localSave();
      }
    };
  }
  let outreachResetBackup;
  const resetAction=window.actions['confirm-reset'],undoResetAction=window.actions['undo-reset'];
  window.actions['confirm-reset']=()=>{outreachResetBackup=JSON.parse(JSON.stringify(saved));saved=empty();localSave();resolved={};resetAction();};
  window.actions['undo-reset']=()=>{if(outreachResetBackup){saved=outreachResetBackup;outreachResetBackup=null;localSave();resolved={};}undoResetAction();};
  const priorTaskOpener=window.openTask;
  window.openTask=id=>{startSession(id);priorTaskOpener(id);const footer=$('.modal-foot');if(footer)footer.insertAdjacentHTML('afterbegin',`<button class="button" data-action="outreach-from-task" data-id="${esc(id)}">Prepare a letter</button>`);};
  window.actions['outreach-from-task']=a=>{closeDialog();selectFinding(a.dataset.id);};
  const stagedImport=window.openImport;
  window.openImport=()=>{
    if(!service){stagedImport();return;}
    modal('Add records to the local archive',`<p>The selected file contents will be read and sent to the outreach service on <strong>${esc(location.origin)}</strong>. They stay in this local deployment for contact extraction. Use fictional files for the demo.</p><form id="outreach-ingest-form"><label class="field"><span>Provider named in these records</span><select name="provider_id"><option value="">No known provider</option>${providers.map(p=>`<option value="${esc(p.provider_id)}">${esc(p.display_name)}</option>`).join('')}</select></label><label class="field"><span>Document date, if known</span><input type="date" name="date"></label><label class="field"><span>Text, email, CSV or Markdown files</span><input id="outreach-ingest-files" type="file" multiple accept=".txt,.eml,.csv,.md" required></label><p class="fine">Up to 10 files, 2 MB each. Scanned files need a configured local OCR / vision service; the browser does not pretend to read them.</p><p id="outreach-ingest-state" role="status"></p><button class="button primary" type="submit">Read and add to local archive</button></form>`,button('Cancel','close-modal'));
  };
  async function ingestFiles(form){
    const files=[...$('#outreach-ingest-files').files],values=new FormData(form),report=$('#outreach-ingest-state'),button=form.querySelector('button[type=submit]');
    if(!files.length||files.length>10){report.textContent='Choose between 1 and 10 files.';return;}
    if(files.some(f=>! /\.(txt|eml|csv|md)$/i.test(f.name)||!f.size||f.size>2*1024*1024)){report.textContent='Use non-empty TXT, EML, CSV or Markdown files up to 2 MB each.';return;}
    button.disabled=true;let completed=0;const importedProviders=new Set();let hasUnknownProvider=false;
    try {
      for(const file of files){
        report.textContent='Reading '+file.name+'…';
        const result=await api('/documents/ingest',{method:'POST',body:{id:'uploaded-'+crypto.randomUUID(),filename:file.name,title:file.name,text:await file.text(),provider_id:values.get('provider_id')||null,type:/\.eml$/i.test(file.name)?'email':'text',date:values.get('date')||''}});
        if(result.document)archive.documents.push(result.document);
        const known=[result.document?.provider_id,...(result.contacts||[]).map(c=>c.provider_id)].filter(id=>providers.some(p=>p.provider_id===id));
        if(!known.length)hasUnknownProvider=true;
        for(const id of known)importedProviders.add(id);
        completed++;
      }
      resolved={};recordActivity('Added '+completed+' record'+(completed===1?'':'s')+' to the local outreach archive');persist();closeDialog();
      if(importedProviders.size===1&&!hasUnknownProvider){toast('Records added. Review the matching provider contact and account reference.');openProviderLetter([...importedProviders][0]);}
      else{go('documents');toast('Records added. They cover multiple or unidentified providers. Choose the relevant action in Letters and refresh its contacts.');}
    }
    catch(e){report.textContent=completed+' record(s) added. '+e.message+' Completed uploads are kept; retry only remaining files.';}finally{button.disabled=false;}
  }
  document.addEventListener('submit',e=>{if(e.target.id==='outreach-ingest-form'){e.preventDefault();ingestFiles(e.target);}});
  document.addEventListener('input',e=>{if(e.target.id==='outreach-demo-mailbox'){const checkbox=$('#outreach-settings-form [name="confirmed_control"]');if(checkbox)checkbox.checked=false;}if(e.target.closest('.outreach-workspace'))updateDraftValue(e.target);});
  document.addEventListener('change',e=>{if(e.target.id==='outreach-finding')selectFinding(e.target.value);else if(e.target.id==='outreach-reference'){const d=draft(),value=e.target.value;if(value==='omit'||referenceOptions(d).some(r=>r.id===value)){d.reference_choice=value;d.reference_choice_explicit=true;reconcileReference(d);localSave();render();}}else if(e.target.dataset.outreachAttachment)updateDraftValue(e.target);});
  document.addEventListener('submit',e=>{if(e.target.id==='outreach-settings-form'){e.preventDefault();saveSettings(e.target);}else if(e.target.id==='outreach-fields')e.preventDefault();});
  window.addEventListener('afterword-profile-changed',()=>{if(state.route==='letters')render();});
  window.addEventListener('pagehide',()=>{clearTimeout(saveTimer);localSave();});
  window.addEventListener('hashchange',()=>{if(state.route==='letters'){startSession(activeFinding);resolve(activeFinding);}if(['letters','exposure'].includes(state.route))loadPrivacy();});
  const outreachAfterRender=afterRender;
  afterRender=()=>{
    outreachAfterRender();
    if(state.route==='letters'){
      saveHint();
    }
  };
  // Integration hooks expose safe operations, not service secrets or arbitrary endpoints.
  window.AfterwordOutreach={api,getService:()=>service,currentDraft:()=>draft(),refreshContacts:()=>resolve(activeFinding,true),openProviderLetter,storeDraft,showReview,reviewError,log,refreshPrivacy:loadPrivacy,rememberServerConsent,summary:()=>({draftCount:Object.keys(saved.drafts).length,localService:!!service,gmail:gmailStatus}),setGmailStatus:value=>{gmailStatus=value;}};
  for(const [id,legacy] of Object.entries(state.drafts||{})){const template=C.defaults[id];if(template&&!saved.drafts[id+':'+template]){const migrated=C.buildDraft(fieldFinding(id),template,{writer_name:legacy.name||''},C.validEmail(legacy.recipient)?legacy.recipient:'');storeDraft({...migrated,subject:legacy.subject,body:legacy.body,body_edited:true,origin:'browser'});}}
  for(const d of Object.values(saved.drafts).sort((a,b)=>lifecycleTime(a)-lifecycleTime(b)))if(d&&d.finding_id)updateTask(d,true);
  initialize();
  render();
})();

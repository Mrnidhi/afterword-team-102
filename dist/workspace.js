/* Complete browser-side workflows. All model outputs remain explicit fixtures. */
const sampleDates = {insurance:'2026-09-24',storage:'2026-09-26',medical:'2026-09-30'};
const recordAmounts = {insurance:250000,storage:129,subscriptions:55.48,medical:1240};
let planSearch = '', planCategory = 'all', planSort = 'suggested', ledgerTier = 'all';
const taskWorking = {}, reviewWorking = {};
let importQueue = [], importErrors = [], taskReturn = null, previousRouteHash = null, resetBackup = null;
const formatDate = value => value ? new Intl.DateTimeFormat('en-US',{month:'short',day:'numeric',year:'numeric',timeZone:'UTC'}).format(new Date(value)) : 'Not set';
const formatTime = value => value && Number.isFinite(Date.parse(value)) ? new Date(value).toLocaleString([], {dateStyle:'medium',timeStyle:'short'}) : 'Not recorded';
const fileSize = size => size < 1024*1024 ? `${Math.ceil(size/1024)} KB` : `${(size/1024/1024).toFixed(1)} MB`;
function recordActivity(text) { state.activity.unshift({text,at:new Date().toISOString()}); state.activity=state.activity.slice(0,60); }
function closeDialog() { $('#detail-dialog').close(); }
function saveNotice(message) { if(persist()) toast(message); }
function exportFile(name, content, type='text/plain') {
  const url = URL.createObjectURL(new Blob([content],{type:`${type};charset=utf-8`}));
  const anchor = document.createElement('a'); anchor.href=url; anchor.download=name; anchor.click();
  setTimeout(()=>URL.revokeObjectURL(url),1000);
  modal('Your export is ready',`<p>Your browser has been asked to download <strong>${escapeHTML(name)}</strong>. You can also copy the content below.</p><label class="field"><span>Export content</span><textarea readonly rows="12">${escapeHTML(content)}</textarea></label>`,button('Done','close-modal',true));
}
function toCSV(rows) { return rows.map(row=>row.map(cell=>{let v=String(cell??'');if(/^[\s]*[=+@-]/.test(v))v="'"+v;return '"'+v.replace(/"/g,'""')+'"';}).join(',')).join('\r\n'); }

// Query parameters preserve the source/finding/template when sharing a page link.
window.prepareRoute = () => {
  const rawHash=location.hash.slice(1)||'overview';
  const hash=rawHash==='privacy'?'exposure':rawHash==='design'?'settings':rawHash;
  const [route,query='']=hash.split('?');
  state.route=[...nav.map(n=>n[0]),'ask','profile'].includes(route)?route:'overview';
  if(previousRouteHash===hash)return;
  previousRouteHash=hash;
  const params=new URLSearchParams(query);
  if(state.route==='evidence') {
    const id=params.get('finding');
    if(Object.hasOwn(findings,id)) state.selectedFinding=id;
    state.evidenceSource=findings[state.selectedFinding].sources.includes(params.get('source'))?params.get('source'):null;
  }
  if(state.route==='letters') {
    const id=params.get('template');
    if(Object.hasOwn(letterTemplates,id)) letterType=id;
    letterDraft=sessionDrafts[letterType]||state.drafts[letterType]||null;
    letterPreview=false;
  }
  state.linkedDocument=state.route==='documents'&&allRecords().some(d=>d.id===params.get('document'))?params.get('document'):null;
};

function filteredTasks() {
  const q=planSearch.toLowerCase().trim();
  return tasks.filter(t=>(state.filter==='all'||status(t)===state.filter)&&(planCategory==='all'||t.category===planCategory)&&`${t.title} ${t.category} ${t.description} ${state.taskNotes[t.id]||''}`.toLowerCase().includes(q)).sort((a,b)=>{
    if(planSort==='date') return (state.reminders[a.id]||sampleDates[a.id]||'9999').localeCompare(state.reminders[b.id]||sampleDates[b.id]||'9999');
    if(planSort==='amount') return (recordAmounts[b.id]||0)-(recordAmounts[a.id]||0);
    return 0;
  });
}
function planResults() {
  const list=filteredTasks();
  return `<div class="results-count" role="status">${list.length} of ${tasks.length} actions${planSort==='amount'?' · Historical amounts only; not money owed or recoverable':''}</div>`+(list.length?list.map((t,i)=>`<article class="plan-row ${status(t)==='done'?'is-done':''}"><div class="plan-track"><span>${status(t)==='done'?icon('check'):String(i+1).padStart(2,'0')}</span></div><div class="plan-content"><div class="row-overline">${t.category}<span class="pill ${status(t)==='review'?'amber':status(t)==='waiting'?'blue':'neutral'}">${statusNames[status(t)]}</span></div><h2><button data-task="${t.id}">${t.title}</button></h2><p>${t.description}</p><div class="plan-metadata"><span>${icon('calendar')}${state.reminders[t.id]?'Your reminder · '+formatDate(state.reminders[t.id]):t.date}</span><span>${icon('files')}${t.source}</span>${window.AfterwordDrain?.caption(t.id)||''}${state.taskNotes[t.id]?'<span>'+icon('edit')+'Your note saved</span>':''}</div></div><button class="row-chevron" data-task="${t.id}" aria-label="Open ${t.title}">${icon('arrow')}</button></article>`).join(''):`<div class="empty-state">${icon('search')}<h2>No actions in this view.</h2><p>Change a filter or clear your search to see more.</p>${button('Clear filters','clear-plan')}</div>`);
}
function completePlanPage() {
  return heading('THE FIRST 30 DAYS','One thing at a time.','A practical plan connected to your records. Adapt it to your family’s pace.',button('Export plan','export-plan',false,'download'))+`
  <div class="plan-progress"><span><strong>${state.completed.length}</strong> of ${tasks.length} actions complete</span><progress value="${state.completed.length}" max="${tasks.length}" aria-label="Completed actions"></progress><span>${tasks.filter(t=>status(t)==='review').length} need a closer look</span></div>
  <div class="plan-layout"><section><div class="filter-bar" role="group" aria-label="Filter actions">${Object.entries(statusNames).map(([key,label])=>`<button class="filter ${state.filter===key?'selected':''}" data-action="filter-plan" data-filter="${key}" aria-pressed="${state.filter===key}">${label}<span>${tasks.filter(t=>key==='all'||status(t)===key).length}</span></button>`).join('')}</div>
  <div class="flow-toolbar"><label class="search-field">${icon('search')}<input id="plan-search" aria-label="Search actions" placeholder="Search your plan…" value="${escapeHTML(planSearch)}"></label><label class="compact-field"><span>Category</span><select id="plan-category"><option value="all">All categories</option>${[...new Set(tasks.map(t=>t.category))].map(c=>`<option ${planCategory===c?'selected':''}>${c}</option>`).join('')}</select></label><label class="compact-field"><span>Sort</span><select id="plan-sort"><option value="suggested">Suggested order</option><option value="date" ${planSort==='date'?'selected':''}>Next date</option><option value="amount" ${planSort==='amount'?'selected':''}>Amount mentioned</option></select></label></div><div class="plan-list" id="plan-results">${planResults()}</div></section>
  <aside class="plan-aside"><div class="gentle-note"><span class="eyebrow">YOUR PLAN, YOUR PACE</span><h2>Progress can be<br>one small step.</h2><p>Add a note, set a reminder, or leave an action waiting for a reply.</p><div class="leaf-mark">${icon('plan')}</div></div><div class="aside-note">${icon('info')}<p>The “first 30 days” is an organizing view. Dates are sample provider requests or reminders you set, not legal deadlines.</p></div><a class="text-link" href="#evidence">Start with the evidence ${icon('arrow')}</a></aside></div>`;
}
const originalOpenTask = openTask;
openTask = function(id) {
  const t=tasks.find(t=>t.id===id); if(!t)return;
  taskReturn=id; originalOpenTask(id);
  $('.modal-body').insertAdjacentHTML('beforeend',`<form id="task-details-form" class="task-details-form"><div class="fields-two"><label class="field"><span>Your reminder date</span><input type="date" name="reminder" value="${taskWorking[id]?.reminder??state.reminders[id]??''}"></label><div class="field"><span>Reminder behavior</span><p class="fine">Shown in your plan. Email and push notifications are not connected.</p></div></div><label class="field"><span>Your working note</span><textarea name="note" rows="3" maxlength="2000" placeholder="A question to ask, or a detail to remember…">${escapeHTML(taskWorking[id]?.note??state.taskNotes[id]??'')}</textarea></label><p class="fine" id="task-note-state">${taskWorking[id]?'Unsaved changes':'Notes and reminders save when you choose Save.'}</p><button class="button" type="submit">Save note & reminder</button></form>`);
};
window.openTask=openTask;
openDocument = function(id) {
  const d=allRecords().find(d=>d.id===id);if(!d)return;
  const back=$('#detail-dialog').open&&taskReturn&&$('#task-details-form');
  modal(d.title,recordPaper(d),back?button('Back to action','document-back',false,'arrow'):button('Back to workspace','close-modal'));
  if(!back)taskReturn=null;
};

const originalDocumentsPage=documentsPage;
function stagingSection() {
  return `<section class="staging-section"><div class="section-title"><div><div class="eyebrow">YOUR LOCAL QUEUE</div><h2>Files awaiting a connection</h2></div><span class="pill neutral">${state.staged.length} staged</span></div><p class="fine">Only file names and sizes are saved here. File contents are not read, uploaded or analyzed. Re-select the original files when a processing service is connected.</p>${state.staged.length?state.staged.map(f=>`<div class="staged-row"><span class="file-badge">${icon('files')}</span><div><strong>${escapeHTML(f.name)}</strong><small>${escapeHTML(f.type)} · ${fileSize(f.size)}</small></div><span class="pill neutral">Awaiting connection</span><button class="icon-button" data-action="remove-staged" data-id="${f.id}" aria-label="Remove ${escapeHTML(f.name)} from queue">${icon('close')}</button></div>`).join(''):`<div class="inline-empty">${icon('upload')}<div><strong>Your queue is clear.</strong><p>Add sample files to try the intake experience.</p></div>${button('Choose files','import')}</div>`}</section>`;
}
function completeDocumentsPage(){return originalDocumentsPage()+stagingSection();}
function importBody() {
  return `<p>Select sample files to organize an intake queue. The frontend records file names and sizes only.</p><div id="file-dropzone" class="file-dropzone"><span class="upload-symbol">${icon('upload')}</span><h3>Bring your records together.</h3><p>Drop files here or browse your computer.</p><label class="button primary file-picker">Choose sample files<input id="intake-files" type="file" multiple accept=".pdf,.txt,.csv,.eml,.md" aria-label="Choose sample files"></label><small>PDF, TXT, CSV, EML, MD · 20 MB per file · 20 files / 100 MB total</small></div>
  <div id="intake-errors" role="alert">${importErrors.map(e=>`<p class="form-error">${escapeHTML(e)}</p>`).join('')}</div><div id="intake-queue">${importQueue.map((f,i)=>`<div class="staged-row"><span class="file-badge">${icon('files')}</span><div><strong>${escapeHTML(f.name)}</strong><small>${fileSize(f.size)} · Ready to stage</small></div><button class="icon-button" data-action="remove-queued" data-index="${i}" aria-label="Remove ${escapeHTML(f.name)}">${icon('close')}</button></div>`).join('')}</div>
  <div class="import-sample"><div><strong>Just exploring?</strong><p>Add a fictional family letter with a readable excerpt.</p></div><button class="button" data-action="sample-import" ${state.imported?'disabled':''}>${state.imported?'Sample added':'Add sample letter'}</button></div><p class="fine">Use fictional files in this public demo. This browser’s local storage is not encrypted.</p>`;
}
function showImport(){modal('Add documents',importBody(),`<span class="fine">${importQueue.length} selected</span>${button('Cancel','close-modal')}<button class="button primary" data-action="stage-files" ${!importQueue.length?'disabled':''}>Stage ${importQueue.length||''} file${importQueue.length===1?'':'s'} ${icon('arrow')}</button>`);}
openImport=function(){importQueue=[];importErrors=[];showImport();};window.openImport=openImport;
function queueFiles(files) {
  importErrors=[];
  for(const file of files) {
    const error=AfterwordStore.validateFile(file);
    const total=[...state.staged,...importQueue];
    if(error){importErrors.push(`${file.name}: ${error}`);continue;}
    if(total.some(f=>f.name===file.name&&f.size===file.size)){importErrors.push(`${file.name}: already in the queue.`);continue;}
    if(total.length>=20){importErrors.push('The queue holds up to 20 files. Remove a file to add another.');break;}
    if(total.reduce((sum,f)=>sum+f.size,0)+file.size>100*1024*1024){importErrors.push(`${file.name}: the queue would exceed 100 MB.`);continue;}
    importQueue.push({name:file.name,size:file.size,type:file.name.split('.').pop().toUpperCase()});
  }
  showImport();
}

const originalEvidencePage=evidencePage;
function completeEvidencePage() {
  const id=state.selectedFinding;
  return originalEvidencePage()+`<section class="review-workbench"><div><div class="eyebrow">YOUR REVIEW RECORD</div><h2>Leave a clear trail.</h2><p>Record a question or the next source you need. Your notes and read status do not change the underlying evidence.</p><div class="review-stamp">${icon('clock')} ${state.reviewTimes[id]?'Last marked as read · '+escapeHTML(formatTime(state.reviewTimes[id])):'Not yet marked as read'}</div><div class="button-row">${button('Export evidence','export-evidence',false,'download')}${button('Print review','print-page',false,'files')}</div></div><form id="review-note-form"><label class="field"><span>Your review note</span><textarea name="note" rows="5" maxlength="2000" placeholder="What do you want to confirm with the provider?">${escapeHTML(reviewWorking[id]??state.reviewNotes[id]??'')}</textarea></label><button class="button primary" type="submit">Save review note</button><p class="fine" id="review-note-state">${Object.hasOwn(reviewWorking,id)?'Unsaved changes. Choose Save to keep this note.':'Editable browser-local notes, not an immutable audit record.'}</p></form></section>`;
}
function selectLetter(id) {
  if(!Object.hasOwn(letterTemplates,id))return;
  if(state.route==='letters') sessionDrafts[letterType]=captureLetter();
  letterType=id;state.lastDraft=id;persist();letterDraft=sessionDrafts[id]||state.drafts[id]||null;letterPreview=false;sendTranslated=false;
  go('letters?template='+id);
}
const originalLettersPage=lettersPage;
function completeLettersPage() {
  return `<div class="letter-context"><span>For: ${findings[letterType].label}</span><a class="text-link" href="#evidence?finding=${letterType}">Review source records</a><button class="text-link" data-task="${letterType}">Return to action ${icon('arrow')}</button></div>`+originalLettersPage().replace('Untitled draft',letterTemplates[letterType].title).replace('<div class="letter-guidance">',`<div class="saved-draft-list"><span class="eyebrow">SAVED IN THIS BROWSER</span><strong>${Object.keys(state.drafts).length} of 3 drafts</strong><p>Each template keeps its own draft.</p></div><div class="letter-guidance">`)+`<div class="letter-extra-actions"><p>Drafts save automatically in this browser. Preview, print or download before sharing the letter yourself.</p><div class="button-row">${button('Reset this template','reset-letter',false,'refresh')}${button('Print letter','print-letter',false,'files')}</div></div>`;
}

let activityQuery='';
function activityResults(){const rows=state.activity.filter(a=>a.text.toLowerCase().includes(activityQuery.toLowerCase()));return rows.length?rows.map(a=>`<div class="local-event">${icon('clock')}<span>${escapeHTML(a.text)}</span><time>${escapeHTML(formatTime(a.at))}</time></div>`).join(''):`<div class="inline-empty">${icon('clock')}<div><strong>${activityQuery?'No matching updates.':'Your updates will appear here.'}</strong><p>${activityQuery?'Try a different search.':'Notes, saved letters and action changes are recorded as you work.'}</p></div></div>`;}
function ledgerPage(){return heading('WORKSPACE','Activity','A record of changes made in this browser.',button('Export activity','export-ledger',false,'download'))+`<section class="activity-workspace"><label class="search-field">${icon('search')}<input id="activity-search" aria-label="Search activity" placeholder="Search your updates…" value="${escapeHTML(activityQuery)}"></label><div id="activity-results" aria-live="polite">${activityResults()}</div><p class="fine">This history belongs to the sample workspace in this browser. It is not shared with other people or devices.</p></section>`;}

const exposureGroups=[{icon:'shield',title:'Identity & relationships',details:'Arun, Priya and Maya’s names; family relationships and beneficiary references.',sources:['policy','will']},{icon:'files',title:'Financial details',details:'Historical coverage, account charges and recurring transactions.',sources:['policy','statement','storage']},{icon:'heart',title:'Health-related billing',details:'Clinic correspondence, invoice amounts and payment details.',sources:['medical','receipt']},{icon:'book',title:'Personal memories',details:'Family passages, notes about belongings and personal locations.',sources:['voice']}];
function exposurePage(){return heading('YOUR INFORMATION','Privacy','See what stays in this browser and what has been shared.',button('Export privacy report','export-exposure',false,'download'))+`<div class="privacy-practical"><section class="settings-panel"><h2>Storage and sharing</h2><dl class="privacy-facts"><div><dt>Saved in this browser</dt><dd>Notes, reminders, letter drafts, progress and file names.<small>Browser storage is unencrypted. Use fictional details in this demo.</small></dd></div><div><dt>Original file contents</dt><dd>Not read or stored.<small>Files in the queue need to be selected again when processing is available.</small></dd></div><div><dt>Sent for analysis</dt><dd>No records sent.<small>Document analysis and external model services are not connected.</small></dd></div><div><dt>Email and bank accounts</dt><dd>Not connected.<small>Letters are prepared here. You decide whether and how to send them.</small></dd></div></dl><div class="privacy-management"><a class="button" href="#settings">Manage saved data ${icon('arrow')}</a><p class="fine">The website downloads typography from Google Fonts. It has no analytics.</p></div></section><section class="privacy-sources"><h2>Sensitive details in the sample records</h2><p class="fine">These categories describe the fictional archive. They are not the result of a live document scan.</p>${exposureGroups.map(g=>`<details class="privacy-category"><summary>${g.title}</summary><p>${g.details}</p>${g.sources.map(documentLink).join('')}</details>`).join('')}</section></div><details class="request-example"><summary>Review an example external request</summary><div><p>This shows how a future optional request could be reviewed before sharing. It is an example; nothing can be sent from this page.</p><blockquote>What information might an insurer request before discussing a deceased policyholder’s account?</blockquote><p class="fine">Family names, providers, amounts and source excerpts are absent from this example. Removing names alone does not guarantee privacy.</p>${button('Inspect example','inspect-payload',false,'eye')}</div></details>`;}
function settingsPage() {
  const outreach=window.AfterwordOutreach?.summary?.();
  const gmail=outreach?.gmail;
  const connections=[['Text record intake',outreach?.localService?'Connected to local service':'Not connected'],['Gmail drafts',gmail?(gmail.connected&&gmail.draft_scope_granted?'Connected':gmail.configured?'Ready to connect':'Not configured'):'Not checked'],['Sending messages','You send from your email app']];
  return heading('WORKSPACE SETTINGS','Make this space yours.','Reading preferences, local data and a clear view of what is connected.')+`<div class="settings-layout"><section class="settings-panel"><div class="section-title"><h2>Your sample workspace</h2><span class="avatar">AR</span></div><dl class="settings-facts"><div><dt>Archive</dt><dd>Arun Rao · fictional</dd></div><div><dt>Organizer</dt><dd>Priya Rao · fictional</dd></div><div><dt>Working letters</dt><dd>${outreach?.draftCount??Object.keys(state.drafts).length} saved drafts</dd></div><div><dt>Staged file names</dt><dd>${state.staged.length} names only · file contents not included</dd></div><div><dt>Browser notes & draft cache</dt><dd>Local browser storage · unencrypted</dd></div><div><dt>Local record archive</dt><dd>${outreach?.localService?'Text records and scans are stored by the local service when uploaded.':'Not connected. Staging a file name does not read its contents.'}</dd></div></dl><div class="setting-action"><div><h3>Appearance</h3><p>${state.largeText?'Larger':'Standard'} text · ${state.ambientMotion?'gentle background motion':'still background'}. Your device’s reduced-motion preference takes priority.</p></div>${button('Change','preferences')}</div><div class="setting-action"><div><h3>Keep a copy</h3><p>Export notes, reminders, draft text and demo preferences as JSON.</p></div>${button('Export workspace','export-workspace',false,'download')}</div><div class="setting-action"><div><h3>Start fresh</h3><p>Restore the fictional workspace. Export first if you want to keep your edits.</p></div><button class="button danger" data-action="reset-workspace">Reset demo</button></div>${resetBackup?`<div class="notice-strip">${icon('refresh')}<p>Your previous workspace can be restored until you reload this page.</p>${button('Undo reset','undo-reset')}</div>`:''}</section><aside><section class="settings-panel"><span class="eyebrow">CONNECTIONS</span><h2>Connection status</h2>${connections.map(([name,status])=>`<div class="connection-row"><span>${name}</span><strong>${status}</strong></div>`).join('')}<p class="fine">The website uses system fonts without external font requests. It makes no AI requests and has no analytics or account integration.</p></section><section class="settings-panel"><h2>About this edition</h2><p>A fictional family case for trying the workflow. Documents, names, providers and amounts are examples.</p><button class="text-link" data-action="workspace-info">How to use this workspace ${icon('arrow')}</button></section></aside></div>`;
}

Object.assign(window.views,{plan:completePlanPage,documents:completeDocumentsPage,evidence:completeEvidencePage,letters:completeLettersPage,exposure:exposurePage,ledger:ledgerPage,settings:settingsPage});
Object.assign(window.actions,{
  'clear-plan':()=>{state.filter='all';planSearch='';planCategory='all';planSort='suggested';render();},
  favorite:a=>{const id=a.dataset.id;state.favorite=state.favorite.includes(id)?state.favorite.filter(v=>v!==id):[...state.favorite,id];saveNotice(state.favorite.includes(id)?'Memory saved to your favorites.':'Memory removed from your favorites.');render();},
  'export-plan':async a=>{if(a)a.disabled=true;toast('Preparing your plan PDF…');try{await AfterwordReports.downloadPlan({mode:'preview',scope:'Current plan view. Amounts are historical amounts mentioned in sample records, not money owed or recoverable.',items:filteredTasks().map(t=>({id:t.id,title:t.title,status:statusNames[status(t)],category:t.category,date:state.reminders[t.id]?'Your reminder: '+state.reminders[t.id]:t.date,source:t.source,amount:t.value,note:state.taskNotes[t.id]||''}))});toast('Your plan PDF download has started.');}catch(error){toast(error.message||'The plan PDF could not be created. Please try again.');}finally{if(a)a.disabled=false;}},
  'document-back':()=>openTask(taskReturn),
  'task-evidence':()=>{const id=state.activeTask;closeDialog();go('evidence?finding='+id);},
  'sample-import':()=>{if(state.imported)return;state.imported=true;state.query='';state.docFilter='all';recordActivity('Added the fictional family letter');saveNotice('Fictional letter added to your sample library.');closeDialog();go('documents');},
  'remove-queued':a=>{importQueue.splice(Number(a.dataset.index),1);showImport();},
  'stage-files':()=>{if(!importQueue.length)return;const count=importQueue.length;state.staged.push(...importQueue.map(f=>({...f,id:'local-'+crypto.randomUUID(),added:new Date().toISOString()})));importQueue=[];recordActivity(`Staged ${count} file name${count===1?'':'s'}; no file content read`);saveNotice('File names staged. A connected service is needed to process their contents.');state.focusStaged=true;closeDialog();go('documents');},
  'remove-staged':a=>{state.staged=state.staged.filter(f=>f.id!==a.dataset.id);saveNotice('File removed from the local queue. The original file is unchanged.');render();},
  finding:a=>go('evidence?finding='+a.dataset.id),
  'evidence-source':a=>go('evidence?finding='+state.selectedFinding+'&source='+a.dataset.id),
  'review-finding':()=>{const id=state.selectedFinding;const read=!state.reviewed.includes(id);state.reviewed=read?[...state.reviewed,id]:state.reviewed.filter(v=>v!==id);if(read)state.reviewTimes[id]=new Date().toISOString();else delete state.reviewTimes[id];recordActivity(`${read?'Read':'Removed read mark from'} ${findings[id].label.toLowerCase()} finding`);saveNotice(read?'Marked as read. Unknowns still need confirmation.':'Read mark removed.');render();},
  'export-evidence':()=>{const id=state.selectedFinding,f=findings[id];exportFile('afterword-evidence-'+id+'.json',JSON.stringify({notice:'Fictional evidence. Human read acknowledgement is not verification.',finding:f,sources:records.filter(r=>f.sources.includes(r.id)),read:state.reviewed.includes(id),readAt:state.reviewTimes[id]||null,note:state.reviewNotes[id]||''},null,2),'application/json');},
  'finding-letter':()=>selectLetter(state.selectedFinding),
  'letter-template':a=>selectLetter(a.dataset.id),
  'save-letter':()=>{if(!validLetter())return;state.drafts[letterType]={...captureLetter()};sessionDrafts[letterType]={...letterDraft};recordActivity('Saved '+letterTemplates[letterType].title.toLowerCase()+' draft');saveNotice('This draft is saved in your browser. Nothing has been sent.');render();},
  'reset-letter':()=>modal('Reset this letter?',`<p>Restore the original <strong>${letterTemplates[letterType].title.toLowerCase()}</strong> template. Your other letters will stay as they are.</p>`,button('Keep editing','close-modal')+button('Reset this template','confirm-reset-letter',true)),
  'confirm-reset-letter':()=>{delete state.drafts[letterType];delete sessionDrafts[letterType];letterDraft=null;letterPreview=false;closeDialog();saveNotice('Template restored.');render();},
  'print-letter':()=>{if(!validLetter())return;captureLetter();letterPreview=true;render();window.print();},
  'print-page':()=>window.print(),
  'export-ledger':async a=>{if(a)a.disabled=true;toast('Preparing your activity PDF…');try{await AfterwordReports.downloadActivity({mode:'preview',scope:activityQuery?'Updates matching the current activity search.':'All recorded updates in this browser.',items:state.activity.filter(item=>item.text.toLowerCase().includes(activityQuery.toLowerCase())).map(item=>({text:item.text,at:item.at}))});toast('Your activity PDF download has started.');}catch(error){toast(error.message||'The activity PDF could not be created. Please try again.');}finally{if(a)a.disabled=false;}},
  exposure:()=>go('exposure'),
  'inspect-payload':()=>modal('Proposed external request',`<div class="notice-strip">${icon('info')}<p>Preview only. No endpoint is configured and no request can be sent.</p></div><label class="field"><span>Exact example payload</span><textarea readonly rows="7">${escapeHTML(JSON.stringify({question:'What information might an insurer request before discussing a deceased policyholder’s account?',attachments:[],source_excerpts:[],personal_identifiers:[]},null,2))}</textarea></label><p>In the intended product, you would review the destination, purpose and actual payload before giving permission. Removing names alone is not a guarantee of privacy.</p>`,button('Close preview','close-modal',true)),
  'export-exposure':()=>exportFile('afterword-exposure-design.json',JSON.stringify({notice:'Illustrative categories; not an automated scan or a privacy guarantee.',cloudConnected:false,archiveAIRequests:0,sampleCategories:exposureGroups.map(({title,details,sources})=>({title,details,sources})),proposedQuestion:'What information might an insurer request before discussing a deceased policyholder’s account?'},null,2),'application/json'),
  'connection-help':()=>modal('Connecting the intended product',`<p>The frontend is ready to demonstrate the workflow. A running HP ZGX deployment still needs these services:</p><ol class="connection-steps"><li><strong>Secure workspace service</strong><span>Authentication, family roles and encrypted file storage.</span></li><li><strong>Local processing service</strong><span>Document parsers, local models and measured routing decisions.</span></li><li><strong>Grounded evidence service</strong><span>Source references, versioned findings and user review records.</span></li></ol><div class="subtle-box">This browser does not scan for devices, collect credentials or open a remote connection.</div>`,button('Back to station','close-modal')),
  'export-workspace':()=>exportFile('afterword-demo-workspace.json',JSON.stringify({version:3,exportedAt:new Date().toISOString(),notice:'Browser-local demo state, not an encrypted archive.',...AfterwordStore.clean(state)},null,2),'application/json'),
  'reset-workspace':()=>modal('Start the demo again?',`<p>This resets browser-local notes, reminders, drafts, favorites, read marks and file names. Original files are never changed.</p><p>You can undo this reset until you reload the page.</p>`,button('Keep workspace','close-modal')+button('Reset demo','confirm-reset',true)),
  'confirm-reset':()=>{resetBackup=AfterwordStore.clean(state);Object.assign(state,AfterwordStore.defaults());letterType=state.lastDraft;for(const cache of [taskWorking,reviewWorking])for(const key of Object.keys(cache))delete cache[key];for(const key of Object.keys(sessionDrafts))delete sessionDrafts[key];letterDraft=null;letterPreview=false;conversation=[];importQueue=[];planSearch='';planCategory='all';planSort='suggested';ledgerTier='all';state.filter='all';state.docFilter='all';state.query='';state.memoryFilter='all';saveNotice('Demo restored. Undo is available in Workspace settings.');closeDialog();render();},
  'undo-reset':()=>{if(!resetBackup)return;Object.assign(state,resetBackup);letterType=state.lastDraft;resetBackup=null;for(const cache of [sessionDrafts,taskWorking,reviewWorking])for(const key of Object.keys(cache))delete cache[key];letterDraft=state.drafts[letterType]||null;saveNotice('Previous workspace restored.');render();},
  'answer-next':a=>go(a.dataset.route==='evidence'?'evidence?finding='+a.dataset.topic:a.dataset.route)
});
for(const [action,kind] of [['task-complete','complete'],['task-wait','wait']]) {
  window.actions[action]=()=>{const id=state.activeTask,t=tasks.find(t=>t.id===id);if(!t)return;
    if(kind==='complete'){state.completed=state.completed.includes(id)?state.completed.filter(x=>x!==id):[...state.completed,id];state.waiting=state.waiting.filter(x=>x!==id);}
    else{state.waiting=state.waiting.includes(id)?state.waiting.filter(x=>x!==id):[...state.waiting,id];state.completed=state.completed.filter(x=>x!==id);}
    recordActivity(`${statusNames[status(t)]}: ${t.title}`);saveNotice('Action updated. You can change its status again anytime.');closeDialog();render();};
}
document.addEventListener('input',e=>{
  if(e.target.id==='activity-search'){activityQuery=e.target.value;$('#activity-results').innerHTML=activityResults();}
  if(e.target.id==='plan-search'){planSearch=e.target.value;$('#plan-results').innerHTML=planResults();}
  if(e.target.closest('#task-details-form')){taskWorking[state.activeTask]=Object.fromEntries(new FormData($('#task-details-form')));$('#task-note-state').textContent='Unsaved changes';}
  if(e.target.closest('#review-note-form')){reviewWorking[state.selectedFinding]=e.target.value;$('#review-note-state').textContent='Unsaved changes. Choose Save to keep this note.';}
  if(e.target.closest('#letter-form')&&!letterPreview) sessionDrafts[letterType]={...captureLetter()};
});
document.addEventListener('change',e=>{
  if(e.target.id==='plan-category'){planCategory=e.target.value;$('#plan-results').innerHTML=planResults();}
  if(e.target.id==='plan-sort'){planSort=e.target.value;$('#plan-results').innerHTML=planResults();}
  if(e.target.id==='intake-files')queueFiles([...e.target.files]);
  if(e.target.id==='send-translated-checkbox')sendTranslated=e.target.checked;
});
document.addEventListener('dragover',e=>{if(e.target.closest('#file-dropzone')){e.preventDefault();$('#file-dropzone').classList.add('drag-over');}});
document.addEventListener('dragleave',e=>{if(e.target.closest('#file-dropzone'))$('#file-dropzone').classList.remove('drag-over');});
document.addEventListener('drop',e=>{if(e.target.closest('#file-dropzone')){e.preventDefault();queueFiles([...e.dataTransfer.files]);}});
document.addEventListener('submit',e=>{
  if(e.target.id==='task-details-form'){e.preventDefault();const data=new FormData(e.target),date=data.get('reminder');if(date&&!AfterwordStore.validDate(date)){toast('Choose a valid reminder date.');return;}state.taskNotes[state.activeTask]=String(data.get('note')).trim();if(date)state.reminders[state.activeTask]=date;else delete state.reminders[state.activeTask];delete taskWorking[state.activeTask];recordActivity('Updated a note or reminder for '+tasks.find(t=>t.id===state.activeTask).category.toLowerCase());saveNotice('Your note and reminder are saved.');$('#task-note-state').textContent=state.storageAvailable===false?'Session only. Export your work in Settings.':'Note and reminder saved in this browser.';render();}
  if(e.target.id==='review-note-form'){e.preventDefault();state.reviewNotes[state.selectedFinding]=String(new FormData(e.target).get('note')).trim();delete reviewWorking[state.selectedFinding];$('#review-note-state').textContent='Saved in this browser. Editable notes, not an immutable audit record.';recordActivity('Saved a review note for '+findings[state.selectedFinding].label.toLowerCase());saveNotice('Review note saved. The source records are unchanged.');render();}
});
const previousAfterRender=afterRender;
afterRender=()=>{previousAfterRender();if(state.storageAvailable===false)$('#main').insertAdjacentHTML('afterbegin','<div class="notice-strip storage-warning" role="alert"><p><strong>Changes are session only.</strong> Browser storage is unavailable. Export your workspace before closing this page.</p><a class="text-link" href="#settings">Workspace settings</a></div>');if(state.linkedDocument){const id=state.linkedDocument;state.linkedDocument=null;openDocument(id);}if(state.route==='overview'){const activity=$('.activity-list');if(activity&&state.activity.length)activity.innerHTML=state.activity.slice(0,3).map(a=>`<div class="activity"><span class="activity-icon">${icon('clock')}</span><div><p>${escapeHTML(a.text)}</p><small>${escapeHTML(formatTime(a.at))}</small></div></div>`).join('');}};
render();

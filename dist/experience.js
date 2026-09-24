/* Interaction continuity: useful work stays in place and mistakes stay reversible. */
let autosaveTimer, autosavePending=false, autosaveDescription='', invalidReminder=false;
function updateSaveStatus() {
  const label=state.storageAvailable===false?'Session only · storage unavailable':autosavePending?'Saving…':'Saved in this browser';
  const draft=$('#draft-state');if(draft&&Object.hasOwn(state.drafts,letterType))draft.textContent=label;
  const count=$('.saved-draft-list strong');if(count)count.textContent=Object.keys(state.drafts).length+' of 3 drafts';
  const storageLabel=$('.node-label small');if(storageLabel)storageLabel.textContent=state.storageAvailable===false?'Session only · not saved':autosavePending?'Saving changes…':'Changes saved in this browser';
  for(const id of ['task-note-state','review-note-state']){const node=$('#'+id);if(node)node.textContent=label;}
  if(!autosavePending&&state.storageAvailable!==false){if($('#task-note-state')&&!state.taskNotes[state.activeTask]&&!state.reminders[state.activeTask])$('#task-note-state').textContent='Changes save automatically in this browser.';if($('#review-note-state')&&!state.reviewNotes[state.selectedFinding])$('#review-note-state').textContent='Changes save automatically in this browser.';}
  if(invalidReminder&&$('#task-note-state'))$('#task-note-state').textContent='Finish the reminder date. These edits have not been saved.';
  const taskForm=$('#task-details-form');
  if(taskForm&&!autosavePending&&!invalidReminder){const values=new FormData(taskForm);if(values.get('note')!==(state.taskNotes[state.activeTask]||'')||values.get('reminder')!==(state.reminders[state.activeTask]||''))$('#task-note-state').textContent='Unsaved changes. Complete a valid reminder date or choose Save.';}
}
window.flushAutosave=()=>{if(!autosavePending)return;clearTimeout(autosaveTimer);autosavePending=false;if(autosaveDescription){if(state.activity[0]?.text===autosaveDescription)state.activity[0].at=new Date().toISOString();else recordActivity(autosaveDescription);}persist();updateSaveStatus();};
function scheduleAutosave(){autosavePending=true;updateSaveStatus();clearTimeout(autosaveTimer);autosaveTimer=setTimeout(window.flushAutosave,600);}
document.addEventListener('input',e=>{
  if(e.target.closest('#letter-form')&&!letterPreview){state.drafts[letterType]={...captureLetter()};state.lastDraft=letterType;autosaveDescription='Updated '+letterTemplates[letterType].title.toLowerCase()+' draft';scheduleAutosave();}
  if(e.target.closest('#task-details-form')){
    const form=new FormData($('#task-details-form')),date=String(form.get('reminder'));
    const dateControl=$('#task-details-form [name="reminder"]');
    invalidReminder=dateControl.validity.badInput||!dateControl.validity.valid||!!(date&&!AfterwordStore.validDate(date));
    dateControl.setAttribute('aria-invalid',String(invalidReminder));
    if(invalidReminder){clearTimeout(autosaveTimer);autosavePending=false;updateSaveStatus();return;}
    state.taskNotes[state.activeTask]=String(form.get('note'));
    if(!date)delete state.reminders[state.activeTask];else if(AfterwordStore.validDate(date))state.reminders[state.activeTask]=date;
    autosaveDescription='Updated a note or reminder for '+tasks.find(t=>t.id===state.activeTask).category.toLowerCase();scheduleAutosave();
  }
  if(e.target.closest('#review-note-form')){state.reviewNotes[state.selectedFinding]=e.target.value;autosaveDescription='Updated a review note for '+findings[state.selectedFinding].label.toLowerCase();scheduleAutosave();}
});
window.addEventListener('pagehide',window.flushAutosave);
window.addEventListener('beforeunload',window.flushAutosave);
document.addEventListener('click',e=>{if(e.target.closest('a,[data-action],[data-task]'))window.flushAutosave();},true);

window.captureWorkspaceFocus=()=>{
  const element=document.activeElement;
  if(!element||!$('#app').contains(element)||element.id==='main')return null;
  if(element.id)return '#'+CSS.escape(element.id);
  for(const key of ['data-action','data-task','href']){
    if(!element.hasAttribute(key))continue;
    let selector=`[${key}="${CSS.escape(element.getAttribute(key))}"]`;
    for(const extra of ['data-id','data-filter','data-index','data-route','data-tier'])if(element.hasAttribute(extra))selector+=`[${extra}="${CSS.escape(element.getAttribute(extra))}"]`;
    return selector;
  }
  return null;
};
window.restoreWorkspaceFocus=selector=>{if($('#detail-dialog').open)return;if(selector)($(selector,$('#app'))||$('#main')).focus({preventScroll:true});};
const flowAfterRender=afterRender;
afterRender=()=>{flowAfterRender();updateSaveStatus();if(state.focusStaged){state.focusStaged=false;requestAnimationFrame(()=>$('.staging-section')?.scrollIntoView({block:'start'}));}};
const taskOpener=window.openTask;
window.openTask=id=>{invalidReminder=false;taskOpener(id);updateSaveStatus();};

// A text notice with a real Undo control; no decorative success badges.
let undoCallback=null;
function dismissNotice(){clearTimeout(window.toastTimer);$('#toast').classList.remove('visible');$('#toast').inert=true;undoCallback=null;}
toast=function(message,undo){
  const notice=$('#toast');clearTimeout(window.toastTimer);undoCallback=typeof undo==='function'?undo:null;
  notice.innerHTML=`<span>${escapeHTML(message)}</span>${undoCallback?'<button type="button" data-action="undo-last">Undo</button>':''}`;
  notice.inert=false;notice.classList.add('visible');window.toastTimer=setTimeout(dismissNotice,undoCallback?20000:4500);
};
window.actions['undo-last']=()=>{const undo=undoCallback,restoreFocus=$('#toast').contains(document.activeElement);undoCallback=null;if(undo)undo();if(restoreFocus)$('#main')?.focus({preventScroll:true});};
document.addEventListener('keydown',e=>{if((e.metaKey||e.ctrlKey)&&e.key.toLowerCase()==='z'&&!e.shiftKey&&undoCallback&&!e.target.closest('input,textarea,[contenteditable="true"]')&&!$('#detail-dialog').open){e.preventDefault();window.actions['undo-last']();}});
const notice=$('#toast');
notice.inert=true;
for(const event of ['focusin','mouseenter'])notice.addEventListener(event,()=>clearTimeout(window.toastTimer));
for(const event of ['focusout','mouseleave'])notice.addEventListener(event,()=>{window.toastTimer=setTimeout(dismissNotice,undoCallback?20000:4500);});
function restoreMembership(key,id,wasPresent){state[key]=state[key].filter(v=>v!==id);if(wasPresent)state[key].push(id);}
for(const action of ['task-complete','task-wait']){
  const original=window.actions[action];
  window.actions[action]=(...args)=>{
    const id=state.activeTask,completed=state.completed.includes(id),waiting=state.waiting.includes(id);original(...args);
    toast(state.storageAvailable===false?'Action changed for this session.':'Action status updated.',()=>{restoreMembership('completed',id,completed);restoreMembership('waiting',id,waiting);recordActivity('Undid an action status change');saveNotice('Previous action status restored.');render();});
  };
}
const originalFavorite=window.actions.favorite;
window.actions.favorite=(button,...rest)=>{
  const id=button.dataset.id,present=state.favorite.includes(id);originalFavorite(button,...rest);
  toast(present?'Memory removed from favorites.':'Memory added to favorites.',()=>{restoreMembership('favorite',id,present);saveNotice('Previous favorite selection restored.');render();});
};
const originalRemove=window.actions['remove-staged'];
window.actions['remove-staged']=button=>{
  const removed=state.staged.find(f=>f.id===button.dataset.id);originalRemove(button);if(!removed)return;
  toast('File removed from the queue. The original is unchanged.',()=>{
    if(state.staged.length>=20||state.staged.reduce((sum,f)=>sum+f.size,0)+removed.size>100*1024*1024){toast('The queue is full. Remove a file before restoring this one.');return;}
    if(!state.staged.some(f=>f.id===removed.id))state.staged.push(removed);saveNotice('File name restored to the queue.');render();
  });
};
window.actions['workspace-info']=()=>modal('Using Afterword',`<p>Afterword helps a family organize the practical work after a loss. This workspace contains a fictional case you can explore.</p><ol class="workspace-guide"><li><strong>Start with the records.</strong><p>Open a document and read the original excerpt.</p></li><li><strong>Review what needs confirmation.</strong><p>Compare sources, note what is unknown, and decide what to ask.</p></li><li><strong>Take the next step.</strong><p>Prepare a letter, contact the provider yourself, and update the action when you’re ready.</p></li></ol><p class="fine">Notes and drafts save automatically in this browser. The demo does not analyze new files, send messages or connect to accounts.</p>`,button('Explore the records','guide-documents')+button('Review the next action','guide-start',true,'arrow'));
window.actions['guide-documents']=()=>{closeDialog();go('documents');};
window.actions['guide-start']=()=>openTask(tasks.find(t=>status(t)!=='done')?.id||'insurance');
$('#detail-dialog').addEventListener('close',()=>{window.flushAutosave();if(!$('#app').contains(document.activeElement))$('#main')?.focus({preventScroll:true});});
render();

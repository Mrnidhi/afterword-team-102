/* Local workspace identity. Static hosting offers an explicitly browser-local preview. */
(() => {
  'use strict';
  const KEY='afterword-profile-v1', esc=escapeHTML;
  const connected=!!window.AfterwordRuntime?.workspace;
  let profile=null, session={enabled:connected,require_login:window.AfterwordRuntime?.requireLogin===true,authenticated:false,setup_required:false}, checking=connected, error='', connectionError='', busy=false, welcome=false, setupPage=false, working=null, authEpoch=0;
  const profileKeys=['display_name','writer_name','estate_name','person_name','writer_phone','relationship','date_of_death','reading_language','demo_mailbox'];
  const plain=value=>!!value&&typeof value==='object'&&!Array.isArray(value);
  const validProfile=value=>plain(value)&&profileKeys.every(key=>typeof value[key]==='string')&&typeof value.demo_mailbox_confirmed==='boolean';
  try {if(!connected){const saved=JSON.parse(localStorage.getItem(KEY)||'null');profile=validProfile(saved?.profile)?saved.profile:null;welcome=!saved?.visited;}}catch{welcome=true;}
  const t=text=>window.AfterwordI18n?.t(text)||text;
  const fields=['writer_name','writer_phone','relationship','date_of_death'];
  const loginRequired=()=>connected&&(window.AfterwordRuntime?.requireLogin===true||session.require_login===true);
  const canAccessData=()=>!loginRequired()||(!checking&&!connectionError&&session.authenticated===true);
  const today=()=>{const d=new Date();return `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`;};
  function checkSession(value){
    if(!plain(value)||value.enabled!==true||['require_login','authenticated','setup_required'].some(key=>typeof value[key]!=='boolean')||(value.authenticated?!validProfile(value.profile):value.profile!==null)||value.authenticated&&value.setup_required)throw Error('The workspace service returned an unexpected session. Reconnect to continue.');
    return value;
  }
  function lock(){
    authEpoch++;profile=null;working=null;session={...session,authenticated:false};checking=false;error='';connectionError='';busy=false;
    closeDialog();const dialog=$('#dialog-content');if(dialog)dialog.textContent='';window.dispatchEvent(new CustomEvent('afterword-locked'));render();
  }
  async function request(path,body,method='POST') {
    const epoch=authEpoch;
    const response=await fetch('/workspace/'+path,{method,credentials:'same-origin',headers:{'Content-Type':'application/json','X-Afterword-Client':'web'},...(body?{body:JSON.stringify(body)}:{})});
    let data;try{data=await response.json();}catch{throw Error('The workspace service could not be reached. Try again.');}
    if(epoch!==authEpoch){const stale=Error('This request belongs to an earlier session.');stale.stale=true;throw stale;}
    if(!response.ok){if(response.status===401&&!['login','setup'].includes(path))lock();throw Error(typeof data?.detail==='string'?data.detail:'Check the details and try again.');}
    const result=checkSession(data);
    if(['setup','login','profile'].includes(path)&&!result.authenticated){lock();throw Error('Your session has ended. Sign in and try again.');}
    return result;
  }
  function changed(){
    if(profile?.reading_language){state.lang=profile.reading_language;persist();}
    window.dispatchEvent(new CustomEvent('afterword-profile-changed',{detail:{profile}}));
  }
  async function refresh(){
    const epoch=authEpoch;checking=true;connectionError='';render();
    try{const next=await request('session',null,'GET');if(epoch!==authEpoch)return;if(session.authenticated&&!next.authenticated)lock();session=next;profile=session.profile;checking=false;changed();render();if(canAccessData())await window.AfterwordFindings?.refresh();}
    catch(e){if(!e.stale){lock();connectionError=e.message;}}
    finally{if(epoch===authEpoch||connectionError){checking=false;render();}}
  }
  function storePreview(value){
    try{localStorage.setItem(KEY,JSON.stringify({visited:true,profile:value}));}
    catch{throw Error('Browser storage is unavailable. Allow local storage before saving this preview profile.');}
  }
  function gateShell(content){return `<main class="workspace-gate" id="main" tabindex="-1"><section class="workspace-welcome"><a class="brand" href="#overview" aria-label="Afterword home"><span class="brand-mark">a<span>·</span></span><span>afterword</span></a><div><p class="eyebrow">${t('A SPACE FOR WHAT COMES NEXT')}</p><h1>${t('A little clarity. One step at a time.')}</h1><p>${t('Bring the records together, understand what needs attention, and take the next step when you are ready.')}</p><ol><li>${t('Keep the important records together.')}</li><li>${t('Review the details before you act.')}</li><li>${t('Prepare letters and keep track of progress.')}</li></ol></div><small>${connected?t('A local workspace on your Afterword device.'):t('An interactive preview with fictional records.')}</small></section><section class="workspace-entry">${content}</section></main>`;}
  function input(name,label,value='',options=''){return `<label class="field"><span>${t(label)}</span><input name="${name}" id="profile-${name}" value="${esc(value)}" ${options}></label>`;}
  function profileFields(setup=false){
    const p=working||profile||{}, preview=!connected;
    return `<div class="fields-two">${input('writer_name','Your full name',p.writer_name||p.display_name||'','autocomplete="name" maxlength="120" required')}${input('estate_name','Workspace name',p.estate_name||'','maxlength="120" placeholder="Family workspace" required')}</div>${connected?input('person_name','Person whose records you are organizing',p.person_name||'','maxlength="120"'):''}<p class="fine">${t('These details help prepare your letters. You can complete or change them later.')}</p><div class="fields-two">${input('writer_phone','Your phone',p.writer_phone||'','type="tel" autocomplete="tel" maxlength="60"')}${input('relationship','Your relationship / authority',p.relationship||'','maxlength="180" placeholder="For example, daughter; authority not yet confirmed"')}${input('date_of_death','Date of death',p.date_of_death||'',`type="date" max="${today()}"`)}<label class="field"><span>${t('Reading language')}</span><select name="reading_language"><option value="en" ${(p.reading_language||state.lang)==='en'?'selected':''}>English</option><option value="es" ${(p.reading_language||state.lang)==='es'?'selected':''}>Español</option>${['vi','hi'].includes(p.reading_language)?`<option value="${esc(p.reading_language)}" selected>${esc(p.reading_language)}</option>`:''}</select></label></div><div class="profile-mailbox"><h3>${t('Inbox for trying the letter workflow')}</h3><p class="fine">${t('Sample providers use fictional addresses. Enter an inbox you have permission to use if you want to open a test email draft.')}</p>${input('demo_mailbox','Approved demo inbox',p.demo_mailbox||'','type="email" maxlength="254" autocomplete="email"')}<label class="outreach-check"><input name="demo_mailbox_confirmed" type="checkbox" ${p.demo_mailbox_confirmed?'checked':''}><span>${t('I have permission to use this inbox for the demo.')}</span></label></div>${setup&&connected&&session.enabled?`${input('password','Create a workspace password','','type="password" minlength="10" maxlength="256" autocomplete="new-password" required')}<p class="fine">${t('Use at least 10 characters. This password unlocks this device workspace; it is not a cloud account.')}</p>`:''}<p class="profile-storage">${preview?t('Preview profile and drafts are saved in this browser, without encryption. Use fictional details.'):t('Your profile is saved in the local database on the Afterword device. It is not uploaded to a cloud account.')}</p>`;
  }
  function form(setup=false){return `<form id="workspace-profile-form" data-setup="${setup}" class="profile-form"><h2>${t(setup?'Set up your workspace':'Your profile')}</h2><p>${t('A few details now mean less repeated typing later.')}</p>${profileFields(setup)}<p id="profile-error" class="form-error" role="alert" ${error?'':'hidden'}>${esc(t(error))}</p><div class="button-row"><button class="button primary" type="submit" ${busy?'disabled':''}>${t(busy?'Saving…':setup?'Open my workspace':'Save profile')}</button>${setup&&!connected?`<button class="button" type="button" data-action="profile-skip">${t('Explore sample first')}</button>`:''}${!setup?`<a class="button" href="#overview">${t('Back to overview')}</a>`:''}</div></form>`;}
  function gate(){
    const needsGate=connected&&(loginRequired()||state.route==='profile');
    if(checking&&needsGate)return gateShell(`<h2>${t('Opening your workspace…')}</h2><p role="status">${t('Checking the local connection.')}</p>`);
    if(needsGate&&connectionError)return gateShell(`<h2>${t('Reconnect to your workspace')}</h2><p class="form-error" role="alert">${esc(t(connectionError))}</p><button class="button primary" data-action="profile-reconnect">${t('Try again')}</button>`);
    if(needsGate&&!session.authenticated){
      if(session.setup_required)return gateShell(form(true));
      return gateShell(`<form id="workspace-login-form" class="profile-form"><span class="profile-lock">${icon('lock')}</span><h2>${t('Welcome back')}</h2><p>${t('Unlock the workspace on this device to continue.')}</p>${input('password','Workspace password','','type="password" autocomplete="current-password" required')}<p id="profile-error" class="form-error" role="alert" ${error?'':'hidden'}>${esc(t(error))}</p><button class="button primary" type="submit" ${busy?'disabled':''}>${t(busy?'Signing in…':'Sign in')}</button><p class="fine">${t('Your records remain on the Afterword device.')}</p></form>`);
    }
    if(welcome)return gateShell(setupPage?form(true):`<p class="eyebrow">${t('WELCOME TO AFTERWORD')}</p><h2>${t('Start with a little context.')}</h2><p>${t('Set up your profile to reuse your details in letters, or explore the fictional family workspace first.')}</p><div class="button-row"><button class="button primary" data-action="profile-setup">${t('Set up preview')}</button><button class="button" data-action="profile-skip">${t('Explore sample first')}</button></div><p class="profile-storage">${t('This public preview has no account sign-in or cloud database. Local sign-in is available when running Afterword on your device.')}</p>`);
    return null;
  }
  function showError(message){error=message;const el=$('#profile-error');if(el){el.hidden=false;el.textContent=t(message);}else toast(message);}
  function collect(form){const data=new FormData(form),value={};for(const key of ['writer_name','estate_name','person_name','writer_phone','relationship','date_of_death','reading_language','demo_mailbox'])value[key]=String(data.get(key)||'').trim();value.display_name=value.writer_name;value.demo_mailbox_confirmed=data.get('demo_mailbox_confirmed')==='on';if(!connected)value.person_name='Arun Rao';if(data.get('password'))value.password=String(data.get('password'));return value;}
  function validate(p){const C=window.OutreachCore;if(!p.writer_name||!p.estate_name)return 'Add your name and workspace name.';if(p.writer_phone&&!C.validPhone(p.writer_phone))return 'Enter a valid contact phone number.';if(p.date_of_death&&(!C.validDate(p.date_of_death)||p.date_of_death>today()))return 'Enter a valid date of death that is not in the future.';if(p.demo_mailbox&&(!C.validEmail(p.demo_mailbox)||C.reservedEmail(p.demo_mailbox)||C.noReply(p.demo_mailbox)))return 'Use a real inbox that accepts replies.';if(p.demo_mailbox&&!p.demo_mailbox_confirmed)return 'Confirm permission to use this inbox.';if(p.demo_mailbox_confirmed&&!p.demo_mailbox)return 'Enter the inbox before confirming permission to use it.';return '';}
  function captureForm(){const form=$('#workspace-profile-form');if(form){working=collect(form);delete working.password;}}
  document.addEventListener('input',event=>{if(event.target.id==='profile-demo_mailbox'){const check=$('[name="demo_mailbox_confirmed"]');if(check)check.checked=false;}if(event.target.closest?.('#workspace-profile-form'))captureForm();});
  document.addEventListener('change',event=>{if(event.target.closest?.('#workspace-profile-form'))captureForm();});
  document.addEventListener('submit',async event=>{
    const form=event.target;if(!['workspace-profile-form','workspace-login-form'].includes(form.id))return;event.preventDefault();if(busy)return;
    error='';const submit=form.querySelector('[type="submit"]');busy=true;if(submit)submit.disabled=true;
    try{
      if(form.id==='workspace-login-form'){const result=await request('login',{password:new FormData(form).get('password')});if(!result.authenticated)throw Error('The workspace could not be unlocked. Try signing in again.');session=result;profile=result.profile;connectionError='';working=null;busy=false;changed();render();await window.AfterwordFindings?.refresh();return;}
      const value=collect(form),issue=validate(value);if(issue)throw Error(issue);
      if(connected){const result=await request(form.dataset.setup==='true'?'setup':'profile',value,form.dataset.setup==='true'?'POST':'PATCH');if(!result.authenticated){lock();throw Error('Your session has ended. Sign in and save the profile again.');}profile=result.profile;session=result;}
      else{delete value.password;storePreview(value);profile=value;}
      working=null;welcome=false;setupPage=false;busy=false;changed();go('overview');render();if(connected)await window.AfterwordFindings?.refresh();toast(t('Profile saved. Your details are ready to use in letters.'));
    }catch(e){if(!e.stale)showError(e.message);}finally{busy=false;if(submit)submit.disabled=false;}
  });
  Object.assign(window.actions,{
    'profile-setup':()=>{setupPage=true;render();$('#profile-writer_name')?.focus();},
    'profile-skip':()=>{welcome=false;try{storePreview(profile);}catch{}render();},
    'profile-edit':()=>{closeDialog();go('profile');},
    'profile-reconnect':refresh,
    'profile-logout':async()=>{try{await request('logout',{});lock();}catch(e){if(!e.stale)toast(e.message);}}
  });
  window.views.profile=()=>`<div class="profile-page">${form(false)}${connected&&session.enabled?`<section class="profile-session"><h2>${t('Workspace access')}</h2><p>${t('Sign out when you finish on a shared computer.')}</p><button class="button" data-action="profile-logout">${t('Sign out')}</button></section>`:''}</div>`;
  const previous=afterRender;
  afterRender=()=>{previous();if(!$('#main'))return;
    const name=profile?.display_name||profile?.writer_name;
    if(name){const title=$('.profile strong');if(title)title.textContent=name;const avatar=$('.profile .avatar');if(avatar)avatar.textContent=name.split(/\s+/).slice(0,2).map(x=>x[0]).join('').toUpperCase();}
    const settings=$('.nav-link[href="#settings"]');if(settings&&!$('.nav-link[href="#profile"]'))settings.insertAdjacentHTML('beforebegin',`<a class="nav-link ${state.route==='profile'?'active':''}" href="#profile" ${state.route==='profile'?'aria-current="page"':''}>${icon('edit')}<span>${t('Your profile')}</span></a>`);
    const action=$('.profile button');if(action){action.dataset.action='profile-edit';action.setAttribute('aria-label',t('Edit your profile'));}
    if(profile?.estate_name&&connected){const title=$('.estate-label strong');if(title)title.textContent=profile.estate_name;}
    if(state.route==='settings'&&!$('#profile-settings-link'))$('#main').insertAdjacentHTML('afterbegin',`<section class="profile-settings-link" id="profile-settings-link"><div><h2>${t('Your profile')}</h2><p>${t('Your name, contact details, workspace and reading language.')}</p></div><a class="button" href="#profile">${t('Edit profile')}</a></section>`);
    window.AfterwordI18n?.apply();
  };
  async function setLanguage(language){if(!profile)return;try{if(connected){const result=await request('profile',{reading_language:language},'PATCH');profile=result.profile;}else{profile={...profile,reading_language:language};storePreview(profile);}}catch(e){toast('Language changed for this browser. Profile save failed: '+e.message);}}
  window.AfterwordProfile={setLanguage,gate,lock,canAccessData,captureForm,current:()=>profile,fields:()=>Object.fromEntries(fields.map(k=>[k,profile?.[k]||''])),refresh,connected};
  if(connected)refresh();else render();
})();

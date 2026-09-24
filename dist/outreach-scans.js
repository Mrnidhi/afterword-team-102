/* Scanned letters stay on the same-origin local service; extraction requires an exact OCR review. */
(() => {
  'use strict';
  const LIMIT=6000000;
  function validateScanFile(file,limit=LIMIT){
    if(!file||!file.size)return 'Choose a non-empty PNG or JPEG scan.';
    if(!/\.(png|jpe?g)$/i.test(file.name)||!['image/png','image/jpeg'].includes(file.type))return 'Use a PNG or JPEG image. Export a scanned PDF page as an image first.';
    if(file.size>Math.min(limit,LIMIT))return 'Choose a scan no larger than '+(Math.min(limit,LIMIT)/1000000)+' MB.';
    return '';
  }
  function previewPath(id){if(typeof id!=='string'||!/^[\w.-]{1,120}$/.test(id))throw Error('The local service returned an invalid scan reference.');return '/scans/'+encodeURIComponent(id)+'/image';}
  function signatureMatches(bytes,type){return type==='image/png'?bytes.length>=8&&[137,80,78,71,13,10,26,10].every((v,i)=>bytes[i]===v):type==='image/jpeg'&&bytes.length>=3&&bytes[0]===255&&bytes[1]===216&&bytes[2]===255;}
  if(typeof module==='object'&&module.exports){module.exports={validateScanFile,previewPath,signatureMatches};return;}
  const O=()=>window.AfterwordOutreach,esc=escapeHTML,$id=id=>document.getElementById(id),KEY='afterword-pending-scans-v1';
  let current=null,engine=null,providers=[],findings=[],pending=[],uiToken=0,reviewerName='';
  try {pending=JSON.parse(localStorage.getItem(KEY)||'[]');if(!Array.isArray(pending))pending=[];pending=pending.filter(v=>v&&typeof v.id==='string'&&/^[\w.-]{1,120}$/.test(v.id)&&typeof v.filename==='string').slice(0,10);}catch{pending=[];}
  const savePending=()=>{try{localStorage.setItem(KEY,JSON.stringify(pending));}catch{toast('The scan is stored on the local service, but its resume shortcut could not be saved in this browser.');}};
  const call=(path,body,method='POST')=>O().api(path,{method,...(body!==undefined?{body}:{}),long:true});
  const actionButton=(id,label,primary=false,disabled=false)=>`<button type="button" class="button ${primary?'primary':''}" id="${id}" ${disabled?'disabled':''}>${label}</button>`;
  const message=text=>{const node=$id('scan-status');if(node)node.textContent=text;};
  function bind(id,handler){$id(id)?.addEventListener('click',async event=>{const el=event.currentTarget;el.disabled=true;try{await handler();}catch(error){message(error.message||'The local scan could not be processed.');}finally{if(el.isConnected)el.disabled=id==='scan-extract'?(!engine?.vision?.configured||$id('scan-ocr-text')?.value!==current?.ocr_text):id==='scan-save-correction'?($id('scan-ocr-text')?.value===current?.ocr_text):false;}});}
  function runtimeNotice(){
    if(!engine)return '<p class="fine">Checking the local text reader and contact model…</p>';
    if(!engine.image_validation?.available)return '<p class="outreach-warning">The local image reader is unavailable. No scan can be uploaded or processed yet.</p>';
    if(!engine.ocr?.available)return `<p class="outreach-warning">The local text reader is unavailable. ${esc(engine.ocr?.reason||'Configure the OCR engine on the local service, then check again.')}</p>`;
    if(!engine.vision?.configured)return '<p class="outreach-warning">The local text reader is ready. The contact-reading model is not configured yet. You can prepare and review the scan, then return after the model is configured to extract contacts.</p>';
    return '<p class="fine">The local text reader is available and the contact-reading model is configured. No image or extracted text is sent to an external service.</p>';
  }
  async function checkRuntime(){engine=await call('/scans/status',undefined,'GET');return engine;}
  function missingService(){modal('Scanned letters need the local service','<p>This public browser demo cannot read scanned letters. Open Afterword through your local outreach service to read a scan, compare the extracted text with the image, and approve contact extraction.</p><p>No file has been read or uploaded.</p>',button('Close','close-modal')+'<a class="button" href="#settings" data-action="close-modal">Outreach settings</a>');}
  async function openUpload(){
    if(!O()?.getService()){missingService();return;}
    const token=++uiToken;current=null;engine=null;
    modal('Add a scanned letter',`<p>A PNG or JPEG image will be sent to the local service on <strong>${esc(location.origin)}</strong> only after you choose Read scan locally. Review the text against the image before allowing contact extraction. Use fictional records for the demo.</p><div id="scan-runtime">${runtimeNotice()}</div><form id="scan-upload-form"><label class="field"><span>Provider named on the letter</span><select id="scan-provider" required disabled><option value="">Loading providers…</option></select></label><div class="fields-two"><label class="field"><span>Letter date, if known</span><input id="scan-date" type="date"></label><label class="field"><span>Title, optional</span><input id="scan-title" maxlength="180" placeholder="For example, policy contact letter"></label></div><label class="field"><span>PNG or JPEG scan · up to 6 MB</span><input id="scan-file" type="file" accept=".png,.jpg,.jpeg,image/png,image/jpeg" required></label><p class="fine">The scan and extracted text are stored on your local service. Selecting a file alone does not upload it. Scanned PDF pages must be exported as images first.</p><p id="scan-status" role="status" aria-live="polite"></p><button type="submit" class="button primary" id="scan-upload" disabled>Read scan locally</button></form>`,button('Not yet','close-modal')+actionButton('scan-runtime-retry','Check local setup again'));
    const load=async()=>{
      const [runtime,data]=await Promise.all([checkRuntime(),call('/providers',undefined,'GET')]);
      if(token!==uiToken||!$id('scan-provider'))return;
      providers=data.providers||[];findings=data.findings||[];
      $id('scan-runtime').innerHTML=runtimeNotice();$id('scan-provider').innerHTML='<option value="">Choose the provider on this letter</option>'+providers.map(p=>`<option value="${esc(p.provider_id)}">${esc(p.display_name)}</option>`).join('');$id('scan-provider').disabled=false;
      $id('scan-upload').disabled=!(runtime.ocr?.available&&runtime.image_validation?.available);
      message('');
    };
    bind('scan-runtime-retry',load);
    $id('scan-upload-form').addEventListener('submit',async event=>{
      event.preventDefault();const el=$id('scan-upload');
      if(!engine?.ocr?.available||!engine?.image_validation?.available){message('Connect the local text reader before uploading.');return;}
      const file=$id('scan-file').files[0],error=validateScanFile(file,engine.max_bytes||LIMIT),provider_id=$id('scan-provider').value,date=$id('scan-date').value,title=$id('scan-title').value.trim();
      if(error){message(error);return;}
      if(!providers.some(p=>p.provider_id===provider_id)){message('Choose the provider named on the letter.');return;}
      if(date&&!OutreachCore.validDate(date)){message('Enter a valid letter date.');return;}
      el.disabled=true;el.textContent='Reading scan locally…';message('The local text reader is processing the image. This may take a moment.');
      try{
        const bytes=new Uint8Array(await file.arrayBuffer());
        if(!signatureMatches(bytes,file.type))throw Error('This file’s contents do not match its PNG or JPEG type. Export a new image and try again.');
        let binary='';for(let i=0;i<bytes.length;i+=8192)binary+=String.fromCharCode(...bytes.subarray(i,i+8192));
        const scan=await call('/scans',{filename:file.name,image_base64:btoa(binary),provider_id,date,title});
        previewPath(scan.id);
        pending=[{id:scan.id,filename:scan.filename||file.name},...pending.filter(v=>v.id!==scan.id)].slice(0,10);savePending();
        if(token!==uiToken)return;
        current=scan;showReview();
      }catch(error){message(error.message||'The scan could not be read. Choose a clearer image and try again.');}
      finally{if(el.isConnected){el.disabled=false;el.textContent='Read scan locally';}}
    });
    try{await load();}catch(error){if(token===uiToken)message(error.message||'The local scan service is unavailable. Check the connection and try again.');}
  }
  function showReview(){
    const scan=current,token=uiToken;if(!scan)return;
    const company=providers.find(p=>p.provider_id===scan.provider_id)?.display_name||scan.provider_id;
    const extractReady=!!engine?.vision?.configured;
    modal('Compare the text with the scanned letter',`<p>Check the contact address character by character. Correct any reading mistakes, save the corrected text, then confirm your review. The original OCR result is kept for comparison. Extraction accepts only contact details found verbatim in the version you approve.</p><p class="fine">Contact for <strong>${esc(company)}</strong> · ${esc(scan.filename)}</p><div class="scan-review-grid"><figure><img src="${esc(previewPath(scan.id))}" alt="Original scanned letter: ${esc(scan.filename)}"><figcaption>Original image stored on the local service</figcaption><a class="text-link" href="${esc(previewPath(scan.id))}" target="_blank" rel="noopener noreferrer">Open full-size scan ${icon('external')}</a></figure><label class="field"><span>Text to verify against the scan</span><textarea id="scan-ocr-text" rows="18" maxlength="2000000">${esc(scan.ocr_text)}</textarea><span id="scan-text-state" class="fine">${scan.correction_history?.length?'Saved correction. Original OCR text is retained below.':'Original OCR text. Correct mistakes before approving.'}</span><button type="button" class="button" id="scan-save-correction" disabled>Save corrected text</button></label></div>${scan.raw_ocr_text&&scan.raw_ocr_text!==scan.ocr_text?`<details class="scan-file-details"><summary>Original text from the local reader</summary><pre class="scan-original-text">${esc(scan.raw_ocr_text)}</pre></details>`:''}${scan.warnings?.length?`<div class="outreach-warning">${scan.warnings.map(esc).join('<br>')}</div>`:''}<div id="scan-runtime">${runtimeNotice()}</div><details class="scan-file-details"><summary>File and text versions</summary><dl><dt>Image SHA-256</dt><dd>${esc(scan.image_sha256)}</dd><dt>Text SHA-256</dt><dd>${esc(scan.ocr_sha256)}</dd></dl><p class="fine">Approval applies to these exact versions. A replacement scan needs a new review.</p></details><label class="field"><span>Your name</span><input id="scan-review-actor" maxlength="100" value="${esc(reviewerName||O().currentDraft()?.fields?.writer_name||'')}" autocomplete="name"></label><label class="outreach-check"><input type="checkbox" id="scan-reviewed"><span>I compared the extracted text with the image and verified that the contact details match.</span></label><p class="fine">The next step uses the configured local model to find contacts, then checks each proposed address against the text. Nothing is emailed.</p><p id="scan-status" role="status" aria-live="polite"></p>`,button('Not yet','close-modal')+actionButton('scan-reupload','Choose a different scan')+actionButton('scan-check-model','Check local setup again')+actionButton('scan-extract','Extract verified contacts',true,!extractReady));
    let dirty=false;
    const syncReviewState=()=>{
      dirty=$id('scan-ocr-text').value!==scan.ocr_text;
      $id('scan-save-correction').disabled=!dirty;
      $id('scan-extract').disabled=dirty||!engine?.vision?.configured;
      $id('scan-text-state').textContent=dirty?'Unsaved correction. Save this version, then review it before extracting contacts.':'This text version is saved. Compare it with the image before approving.';
    };
    $id('scan-ocr-text').addEventListener('input',()=>{$id('scan-reviewed').checked=false;syncReviewState();});
    $id('scan-review-actor').addEventListener('input',event=>{reviewerName=event.target.value;});
    bind('scan-save-correction',async()=>{
      if(!dirty)return;
      const actor=$id('scan-review-actor').value.trim(),ocr_text=$id('scan-ocr-text').value;
      if(!actor)throw Error('Enter your name before saving a correction.');
      if(!ocr_text.trim())throw Error('The verified text cannot be empty.');
      reviewerName=actor;message('Saving the corrected text as a new review version…');
      const fresh=await call('/scans/'+encodeURIComponent(scan.id),{ocr_text,previous_ocr_sha256:scan.ocr_sha256,actor},'PATCH');
      if(fresh.ocr_sha256===scan.ocr_sha256&&fresh.ocr_text!==scan.ocr_text)throw Error('The corrected text did not receive a new version. Reload the scan before continuing.');
      if(token!==uiToken)return;
      current=fresh;showReview();message('Correction saved. Compare this version with the image and confirm your review again.');
    });
    bind('scan-reupload',openUpload);
    bind('scan-check-model',async()=>{await checkRuntime();if(!$id('scan-runtime'))return;$id('scan-runtime').innerHTML=runtimeNotice();$id('scan-extract').disabled=dirty||!engine.vision?.configured;message(engine.vision?.configured?'The local model is configured. Review the scan and confirm when ready.':'The contact-reading model is still not configured. Your reviewed scan is kept on the local service.');});
    bind('scan-extract',async()=>{
      if(dirty||$id('scan-ocr-text').value!==scan.ocr_text)throw Error('Save the corrected text and review the new version before extraction.');
      if(!engine?.vision?.configured)throw Error('Connect the local contact-reading model before extracting contacts.');
      if(!$id('scan-reviewed').checked)throw Error('Compare the text with the image and confirm the review first.');
      const actor=$id('scan-review-actor').value.trim();if(!actor)throw Error('Enter the name of the person reviewing this scan.');
      message('Reading the contact block locally and checking each result against the text…');
      const result=await call('/scans/'+encodeURIComponent(scan.id)+'/confirm',{ocr_sha256:scan.ocr_sha256,image_sha256:scan.image_sha256,confirmed:true,actor});
      if(result.status!=='extracted')throw Error('The service did not confirm contact extraction. Your scan remains available for review.');
      pending=pending.filter(v=>v.id!==scan.id);savePending();
      if(token!==uiToken)return;
      const contacts=result.contacts||[],target=findings.find(f=>(f.provider_ids||[f.provider_id]).includes(scan.provider_id));
      const contactHTML=contacts.map(c=>{const evidence=c.evidence||{};return `<article class="scan-contact"><strong>${esc(c.value||c.channel?.value||'Contact detail')}</strong><p>${esc(c.label||c.kind||'Contact')}</p>${evidence.quote?`<blockquote>${esc(evidence.quote)}</blockquote><p class="fine">${esc(evidence.doc_id||result.document?.id||'Reviewed scan')} · characters ${esc(evidence.start)}–${esc(evidence.end)}</p>`:''}</article>`;}).join('');
      modal(contacts.length?'Contacts added from your scanned letter':'Scan reviewed; no contact found',`<p>${contacts.length?'The local model proposed these contacts. Every stored contact matched the reviewed text.':'No contact detail passed the source check. No address was invented or added. You can use a clearer scan or enter an address you have verified.'}</p>${contactHTML}<p class="fine">Processed by local OCR and the configured local contact-reading model. This is source matching, not independent proof that an address is current or accepts messages.</p>`,button('Back to documents','scan-documents')+(target?`<button class="button primary" data-action="scan-letter" data-finding="${esc(target.id||target.finding_id)}">Review provider contacts ${icon('arrow')}</button>`:'')+actionButton('scan-add-another','Add another scan'));
      bind('scan-add-another',openUpload);O().log('scan_contacts_added',null,{scan_id:scan.id,contact_count:contacts.length});
    });
  }
  async function resumeScan(id){
    if(!O()?.getService()){missingService();return;}
    previewPath(id);const token=++uiToken;
    modal('Loading your scanned letter','<p id="scan-status" role="status">Loading the original image and extracted text from the local service…</p>',button('Not yet','close-modal'));
    try{const [scan,,data]=await Promise.all([call('/scans/'+encodeURIComponent(id),undefined,'GET'),checkRuntime(),call('/providers',undefined,'GET')]);if(token!==uiToken)return;current=scan;providers=data.providers||[];findings=data.findings||[];showReview();}catch(error){message(error.message||'The saved scan could not be loaded.');}
  }
  const documentsView=window.views.documents;
  window.views.documents=()=>documentsView()+`<section class="staging-section scan-entry"><div class="section-title"><div><h2>Scanned letters</h2><p class="fine">Read a paper letter locally, compare the text, and approve its contact details.</p></div><button class="button" data-action="outreach-add-scan">Add scanned letter ${icon('plus')}</button></div>${pending.length?`<div class="scan-pending"><h3>Scans awaiting review</h3>${pending.map(v=>`<button class="scan-resume" data-action="outreach-resume-scan" data-id="${esc(v.id)}"><span>${esc(v.filename)}</span><span>Resume review ${icon('arrow')}</span></button>`).join('')}</div>`:''}</section>`;
  Object.assign(window.actions,{'outreach-add-scan':()=>openUpload(),'outreach-resume-scan':el=>resumeScan(el.dataset.id),'scan-documents':()=>{closeDialog();go('documents');},'scan-letter':el=>{closeDialog();go('letters?finding='+encodeURIComponent(el.dataset.finding));O().refreshContacts();}});
  $id('detail-dialog')?.addEventListener('close',()=>{uiToken++;});
  window.AfterwordScans={openUpload,resumeScan};
  render();
})();

/* Pure outreach rules shared by the buildless browser UI and Node tests. */
(function(root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.OutreachCore = api;
})(typeof globalThis === 'object' ? globalThis : this, function() {
  'use strict';
  const templateNames = Object.freeze({policy_information:'Request policy information',account_status:'Notify of death & request account status',cancel_service:'Cancel a recurring service',balance_confirmation:'Request a final statement',request_records:'Request records or a duplicate document'});
  const defaults = {insurance:'policy_information',storage:'request_records',subscriptions:'cancel_service',medical:'balance_confirmation',bonds:'request_records','notify-employer':'account_status','gather-records':'request_records'};
  const fieldLabels = {writer_name:'Your full name',writer_phone:'Your phone',relationship:'Your relationship / authority',date_of_death:'Date of death'};
  const placeholders = {writer_name:'[YOUR FULL NAME]',writer_phone:'[YOUR PHONE]',relationship:'[YOUR RELATIONSHIP / AUTHORITY]',date_of_death:'[DATE OF DEATH]'};
  const sourceLabels = {records:'From his records',directory:'From the offline directory',lookup:'Looked up · please verify',user:'Entered by you'};
  const validEmail = value => typeof value === 'string' && value.length <= 254 && /^[A-Z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Z0-9](?:[A-Z0-9-]*[A-Z0-9])?(?:\.[A-Z0-9](?:[A-Z0-9-]*[A-Z0-9])?)+$/i.test(value) && !/[\r\n]/.test(value);
  const emailDomain = value => validEmail(value) ? value.split('@')[1].toLowerCase() : '';
  const reservedEmail = value => /(^|\.)(invalid|example|test|localhost)$/.test(emailDomain(value)) || /^(example\.(com|org|net))$/.test(emailDomain(value));
  const noReply = value => /^(?:no[._-]?reply|do[._-]?not[._-]?reply|notifications|marketing)(?:[+._-][^@]*)?@/i.test(value);
  const safeURL = value => {try {const u=new URL(value);return u.protocol==='https:'&&!u.username&&!u.password ? u.href : null;} catch{return null;}};
  const snapshot = draft => ({provider_id:(draft.provider_id&&draft.provider_id!=='user'?draft.provider_id:draft.recipient_provider?.provider_id&&draft.recipient_provider.provider_id!=='user'?draft.recipient_provider.provider_id:null),recipient:String(draft.recipient||'').trim(),subject:String(draft.subject||''),body:String(draft.body||''),attachments:Array.isArray(draft.attachments)?draft.attachments.filter(v=>typeof v==='string').slice(0,20):[],attachment_files:Array.isArray(draft.attachment_files)?draft.attachment_files.map(v=>({id:v.id,name:v.name,size:v.size,sha256:v.sha256})):[]});
  const canonicalSnapshot = draft => JSON.stringify(snapshot(draft));
  const validDate = value => /^\d{4}-\d{2}-\d{2}$/.test(value||'') && Number.isFinite(Date.parse(value)) && new Date(value).toISOString().slice(0,10)===value;
  function maskIdentifier(value) {
    const clean=String(value||'').replace(/[^a-zA-Z0-9]/g,'');
    return clean.length>=4 ? 'ending '+clean.slice(-4) : '[MASKED ACCOUNT REFERENCE]';
  }
  const normalizeSensitive = value => String(value||'').normalize('NFKC').replace(/[\u200B-\u200F\u202A-\u202E\u2060\uFEFF]/g,'').replace(/[‐‑‒–—−]/g,'-');
  const validPhone = value => {const s=String(value||'').trim(),n=s.replace(/\D/g,'');return /^[+]?[- ()\d.]+$/.test(s)&&((n.length===10)||(n.length===11&&n.startsWith('1'))||(s.startsWith('+')&&n.length>=10&&n.length<=15));};
  function blockedFields(draft) {
    const value=normalizeSensitive([draft.recipient,draft.subject,draft.body,...(draft.attachments||[]),...(draft.attachment_files||[]).map(f=>f.name)].join('\n')), blocked=[];
    const phone=normalizeSensitive(draft.fields?.writer_phone||'');
    // Exempt the declared, valid phone only on its intended contact line, never elsewhere.
    const withoutDate=draft.fields?.date_of_death&&validDate(draft.fields.date_of_death)?value.split(draft.fields.date_of_death).join('[DATE OF DEATH]'):value;
    const withoutPhone=withoutDate.split('\n').map(line=>validPhone(phone)&&/^\s*(?:You can reach me at|Please contact me at|Contact(?: phone)?|Phone(?: number)?|Telephone)\s*:?\s*/i.test(line)?line.replace(phone,'[CONTACT PHONE]'):line).join('\n');
    for(const known of draft.known_sensitive_identifiers||[]) if(String(known).length>4&&value.includes(normalizeSensitive(known)))blocked.push('Full account or policy identifier');
    if(/\b\d{3}[ -]?\d{2}[ -]?\d{4}\b/.test(value)||/\b(?:ssn|social security(?: number)?)\s*[:#-]?\s*\d/i.test(value))blocked.push('Social Security number');
    if(/\b(?:date of birth|birth date|dob|born)\s*(?:on\s*)?[:=-]?\s*(?:\d|[a-z]+\s+\d)/i.test(value))blocked.push('Date of birth');
    const accountPattern=/\b(?:bank account|bank details|account|acct|routing|iban|policy)\s*(?:number|no\.?|#|id|reference)?\s*[:#=-]?\s*([A-Z0-9][A-Z0-9\s-]{4,34})/ig;
    for(const match of value.matchAll(accountPattern)) {
      if(/^(?:ending|ends|last|status|information|holder|number|reference|records|or|and|of|with|is|was|remains|recorded|details|before|for|in|has|to|that|could|can|on|may|as|at|from|the|this|no|not|please|confirmation|record|access|provided)\b/i.test(match[1]))continue;
      const identifier=match[1].split(/[\n.,;]/)[0].trim().replace(/[\s-]/g,'');
      if(identifier.replace(/\D/g,'').length>4){blocked.push('Full account or policy identifier');break;}
    }
    if(/(?<!\d)\d(?:[ -]?\d){7,}(?!\d)/.test(withoutPhone)&&!blocked.includes('Full account or policy identifier'))blocked.push('Full account or policy identifier');
    return [...new Set(blocked)];
  }
  function disclosures(draft) {
    const value=[draft.subject,draft.body].join('\n'), fields=draft.fields||{}, result=['Recipient email address'];
    if(value.includes(draft.deceased_name||'Arun Rao')) result.push('Arun’s full name');
    for(const [key,label] of Object.entries({writer_name:'Your name',writer_phone:'Your phone number',relationship:'Your relationship or authority',date_of_death:'Date of death'})) if(fields[key]&&value.includes(fields[key]))result.push(label);
    if(/\bending\s+[a-z0-9]{4}\b/i.test(value))result.push('Masked account or policy reference');
    if(/\b\d{4}-\d{2}-\d{2}\b/.test(value)&&!result.includes('Date of death'))result.push('Dates included in the letter');
    if(draft.attachments?.length)result.push('Attachment reminder labels (no files in compose links)');
    if(draft.body_edited)result.push('Any other details in your edited letter');
    return result;
  }
  function preflight(draft, options={}) {
    const s=snapshot(draft), issues=[], blocked=blockedFields(draft), ph=[...new Set((s.subject+'\n'+s.body).match(/\[[^\]\r\n]+\]/g)||[])];
    if(!validEmail(s.recipient))issues.push('Enter one valid recipient email address.');
    else if(reservedEmail(s.recipient))issues.push('This is a reserved example address. Choose a mailbox you control.');
    else if(noReply(s.recipient))issues.push('Choose a contact address that accepts replies.');
    if(!s.subject.trim())issues.push('Add a subject.');
    if(/[\r\n]/.test(s.subject))issues.push('Keep the subject on one line.');
    if(!s.body.trim())issues.push('Write the letter before reviewing.');
    if(ph.length)issues.push('Fill the remaining placeholders: '+ph.join(', ')+'.');
    for(const [field,label] of Object.entries(fieldLabels))if(!String(draft.fields?.[field]||'').trim())issues.push('Add '+label.toLowerCase()+'.');
    if(draft.fields?.writer_phone&&!validPhone(draft.fields.writer_phone))issues.push('Enter a valid contact phone number.');
    if(draft.fields?.date_of_death&&!validDate(draft.fields.date_of_death))issues.push('Enter a valid date of death.');
    else if(draft.fields?.date_of_death&&draft.fields.date_of_death>new Date().toISOString().slice(0,10))issues.push('Date of death cannot be in the future.');
    if(blocked.length)issues.push('Remove '+blocked.join(', ')+'. Ask for a secure portal or postal process instead.');
    const provider=draft.recipient_provider||{}, provenance=provider.source_kind||'user';
    const known=(options.verifiedDomains||[]).includes(emailDomain(s.recipient));
    const owned=validEmail(options.demoMailbox)&&emailDomain(options.demoMailbox)===emailDomain(s.recipient)&&s.recipient.split('@')[0].split('+')[0].toLowerCase()===options.demoMailbox.split('@')[0].split('+')[0].toLowerCase();
    const domainWarning=validEmail(s.recipient)&&!known&&!owned;
    return {snapshot:s,issues,blocked_fields:blocked,placeholders:ph,disclosed_fields:disclosures(draft),can_handoff:issues.length===0,compose_available:s.body.length<1500,recipient_confirmation_required:domainWarning||provenance==='lookup'||provenance==='user',domain_warning:domainWarning,source_kind:provenance};
  }
  function gmailURL(draft) {
    const s=snapshot(draft);
    if(!validEmail(s.recipient)||/[\r\n]/.test(s.subject))throw new Error('Invalid email envelope.');
    return 'https://mail.google.com/mail/?'+new URLSearchParams({view:'cm',fs:'1',to:s.recipient,su:s.subject,body:s.body}).toString();
  }
  function mailtoURL(draft) {const s=snapshot(draft);if(!validEmail(s.recipient)||/[\r\n]/.test(s.subject))throw new Error('Invalid email envelope.');return 'mailto:'+encodeURIComponent(s.recipient)+'?subject='+encodeURIComponent(s.subject)+'&body='+encodeURIComponent(s.body);}
  function demoAddress(mailbox, alias) {
    if(!validEmail(mailbox)||reservedEmail(mailbox)||!alias||!/^[a-z0-9-]+$/.test(alias))return '';
    const [local,domain]=mailbox.split('@');
    if(!['gmail.com','googlemail.com'].includes(domain.toLowerCase()))return mailbox;
    return local.split('+')[0]+'+'+alias+'@'+domain.toLowerCase();
  }
  function rankCandidates(candidates) {
    const tier={records:0,directory:1,lookup:2,user:3}, role=v=>/^(claims|bereavement|estates|support|service)(?:[.+_-]|@)/i.test(v)?0:1;
    return [...candidates].filter(p=>p.channels?.some(c=>c.kind==='email'&&validEmail(c.value)&&!noReply(c.value))).sort((a,b)=>(tier[a.source_kind]??4)-(tier[b.source_kind]??4)||role(a.channels.find(c=>c.kind==='email').value)-role(b.channels.find(c=>c.kind==='email').value)||String(b.document_date||'').localeCompare(String(a.document_date||'')));
  }
  function buildDraft(finding, templateId, fields={}, recipient='', provider=null) {
    const id=Object.hasOwn(templateNames,templateId)?templateId:defaults[finding.finding_id]||'request_records';
    const f=Object.fromEntries(Object.keys(fieldLabels).map(k=>[k,String(fields[k]||'').trim()]));
    const v=k=>f[k]||placeholders[k], name=finding.deceased_name||'Arun Rao';
    const safeMasked=/^(?:policy|account|reference) ending [A-Za-z0-9]{1,4}$/i.test(finding.masked_identifier||'')?String(finding.masked_identifier).replace(/^(?:policy|account|reference)\s+/i,''):'';
    const identifier=safeMasked||(finding.account_hint?maskIdentifier(finding.account_hint):'');
    const ref=identifier?`The available record identifies the ${id==='policy_information'?'policy':'account'} ${identifier}.`:'I do not yet have a confirmed account reference. Please explain how to identify the relevant records securely.';
    const requests={policy_information:['Confirm whether the historical policy is still active.','Explain the authorization needed to request current policy information and the recorded beneficiary designation.'],account_status:['Explain the authority and documents needed to discuss this account.','Provide the current status and any next steps after that authority is established.'],cancel_service:['Please cancel this recurring service once you have verified my authority.','Confirm any remaining charges and the effective cancellation date.'],balance_confirmation:['Provide an updated, itemized statement after confirming my authority.','Confirm whether any recorded payment was applied and explain any remaining balance.'],request_records:finding.finding_id==='storage'?['Explain how an authorized family member can arrange a visit and collect belongings.','List the required documents and provide a copy of the rental agreement. This is not a cancellation request.']:['Explain the authority needed to request these records.','Provide the relevant record or explain how to obtain a duplicate securely.']};
    const body=`Dear team,\n\nMy name is ${v('writer_name')}. I am writing as ${v('relationship')} regarding ${name}, who died on ${v('date_of_death')}.\n\n${ref}\n\n${requests[id].map((r,i)=>`${i+1}. ${r}`).join('\n')}\n\nI can supply a death certificate and evidence of authority through your secure process. Please explain what is required before I share documents.\n\nYou can reach me at ${v('writer_phone')}.\n\nThank you,\n${v('writer_name')}`;
    const d={id:'local-'+(typeof crypto!=='undefined'&&crypto.randomUUID?crypto.randomUUID():Date.now().toString(36)+Math.random().toString(36).slice(2)),finding_id:finding.finding_id,provider_id:provider?.provider_id||finding.provider_id||null,template_id:id,fields:f,recipient,recipient_provider:provider,subject:templateNames[id]+' — '+name,body,attachments:[],attachment_suggestions:['Death certificate (PDF), only if required','Evidence of authority, only if required'],deceased_name:name,status:'draft',generation:{mode:'template',warning:'Prepared from a local template. No language model was used.'},created_at:new Date().toISOString(),updated_at:new Date().toISOString()};
    d.disclosed_fields=disclosures(d);return d;
  }
  function markSent(draft, consent, now=new Date()) {
    if(!consent||consent.outreach_id!==draft.id)throw new Error('Review and authorize a handoff first.');
    if(canonicalSnapshot(consent.snapshot)!==canonicalSnapshot(draft))throw new Error('This draft changed after its last authorized handoff. Review it again.');
    const follow=new Date(now);follow.setDate(follow.getDate()+14);
    return {...draft,status:'waiting',sent_at:now.toISOString(),reminder_date:[follow.getFullYear(),String(follow.getMonth()+1).padStart(2,'0'),String(follow.getDate()).padStart(2,'0')].join('-'),updated_at:now.toISOString()};
  }
  function markReplied(draft,now=new Date()) {if(draft.status!=='waiting')throw new Error('Mark the letter as sent before recording a reply.');return {...draft,status:'review',replied_at:now.toISOString(),updated_at:now.toISOString()};}
  return {templateNames,defaults,fieldLabels,sourceLabels,validEmail,emailDomain,reservedEmail,noReply,safeURL,snapshot,canonicalSnapshot,validDate,validPhone,maskIdentifier,blockedFields,disclosures,preflight,gmailURL,mailtoURL,demoAddress,rankCandidates,buildDraft,markSent,markReplied};
});

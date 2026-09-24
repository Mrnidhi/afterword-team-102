'use strict';
const assert=require('node:assert/strict');
const fs=require('node:fs'),path=require('node:path');
const C=require('../dist/outreach-core.js');
const fields={writer_name:'Priya Rao',writer_phone:'415-555-0100',relationship:'daughter, authority not yet confirmed',date_of_death:'2026-09-18'};
const finding={finding_id:'insurance',deceased_name:'Arun Rao',masked_identifier:'policy ending 4471'};
const valid=C.buildDraft(finding,'policy_information',fields,'demo+policy@gmail.com',{source_kind:'directory',channels:[{kind:'email',value:'demo+policy@gmail.com'}]});
assert.equal(Object.keys(C.templateNames).length,5);
for(const id of Object.keys(C.templateNames)){
 const d=C.buildDraft(finding,id,fields,'demo@gmail.com');
 assert.equal(d.template_id,id);
 assert.equal(C.preflight(d).can_handoff,true,'All complete templates are usable');
 assert.match(d.body,/1\. /);assert.match(d.body,/2\. /);
 assert.match(d.body,/ending 4471/);assert.doesNotMatch(d.body,/policy policy/);
 assert.ok(d.body.trim().split(/\s+/).length<200,id+' stays concise');
 assert.ok(d.body.length<1500,id+' fits compose URL bodylimit');
}
const storage=C.buildDraft({finding_id:'storage'},'request_records',fields,'demo@gmail.com');
assert.match(storage.body,/not a cancellation request/);
const cancellation=C.buildDraft({finding_id:'subscriptions'},'cancel_service',fields,'demo@gmail.com');
assert.match(cancellation.body,/Please cancel this recurring service once you have verified my authority/);
assert.equal(C.maskIdentifier('POL-98764471'),'ending 4471');
assert.equal(C.maskIdentifier('12'),'[MASKED ACCOUNT REFERENCE]');
assert.equal(C.validDate('2026-02-30'),false);assert.equal(C.validDate('2028-02-29'),true);
for(const value of ['someone@example.invalid','someone@bank.example','a@example.com','a@test.localhost','a@local.test'])assert.equal(C.preflight({...valid,recipient:value}).can_handoff,false,'Reserved recipients are never deliverable');
for(const value of ['a@b.com\r\nBcc:bad@b.com','a@b.com,c@d.com','Name <a@b.com>','a b@gmail.com'])assert.equal(C.validEmail(value),false);
for(const value of ['noreply@p.example','no-reply+claims@p.example','notifications.alert@p.example','marketing-news@p.example','donotreply@p.example'])assert.equal(C.noReply(value),true,value);
assert.equal(C.noReply('claims@p.example'),false);
assert.equal(C.demoAddress('team@gmail.com','cedarlife'),'team+cedarlife@gmail.com');
assert.equal(C.demoAddress('team+old@gmail.com','cedarlife'),'team+cedarlife@gmail.com');
assert.equal(C.demoAddress('approved@university.edu','cedarlife'),'approved@university.edu','Non-Gmail provider uses exact approved inbox');
assert.equal(C.demoAddress('name@example.invalid','demo'),'');
assert.equal(C.demoAddress('team@gmail.com','bad&x'),'');
const partial=C.buildDraft(finding,'policy_information',{},'demo@gmail.com');
assert.equal(C.preflight(partial).can_handoff,false);
assert.ok(C.preflight(partial).placeholders.includes('[YOUR FULL NAME]'));
assert.equal(C.preflight({...partial,body:'Dear team, please help.'}).can_handoff,false,'Removing placeholders does not bypass required family fields');
for(const forbidden of ['SSN: 123-45-6789','Social Security number 123456789','DOB: 01/02/1940','Born on February 8, 1940','Account number: 12345678','Bank details: 0987654321','Routing: 123456789','Policy: AB765432109','Standalone 1122334455']){
 const d={...valid,body:valid.body+'\n'+forbidden};
 assert.equal(C.preflight(d).can_handoff,false,forbidden+' is blocked');
}
assert.equal(C.preflight({...valid,body:valid.body+'\nFull reference ABC-4471',known_sensitive_identifiers:['ABC-4471']}).can_handoff,false);
assert.equal(C.preflight({...valid,subject:'Subject\nBcc: secret@example.com'}).can_handoff,false);
assert.equal(C.preflight({...valid,body:valid.body+'\nAccount ending 0082.'}).can_handoff,true);
assert.equal(C.preflight({...valid,body:'x'.repeat(1500)}).compose_available,false);
assert.equal(C.preflight({...valid,body:'x'.repeat(1499)}).compose_available,true);
assert.equal(C.preflight(valid,{demoMailbox:'demo@gmail.com'}).recipient_confirmation_required,false);
assert.equal(C.preflight({...valid,recipient_provider:{source_kind:'lookup'}},{demoMailbox:'demo@gmail.com'}).recipient_confirmation_required,true);
assert.equal(C.preflight({...valid,recipient:'real@insurer.com'}).domain_warning,true);
const special={...valid,subject:'A & B + #/?',body:'Line 1\nName: Renée & Arun + 40%?\nPlease reply.'};
const url=new URL(C.gmailURL(special));
assert.equal(url.origin,'https://mail.google.com');assert.equal(url.searchParams.get('to'),special.recipient);assert.equal(url.searchParams.get('su'),special.subject);assert.equal(url.searchParams.get('body'),special.body);
const mailto=C.mailtoURL(special);assert.equal(decodeURIComponent(mailto.split('body=')[1]),special.body);assert.ok(mailto.includes('%20'),'mailto spaces use percent encoding');
assert.throws(()=>C.gmailURL({...valid,recipient:'x\r\nBcc:a@b.com'}));
assert.equal(C.safeURL('javascript:alert(1)'),null);assert.equal(C.safeURL('https://user:pass@example.com'),null);assert.equal(C.safeURL('https://example.com/contact'),'https://example.com/contact');
const candidate=(email,source_kind,date='')=>({source_kind,document_date:date,channels:[{kind:'email',value:email}]});
const ranked=C.rankCandidates([candidate('claims@lookup.test','lookup'),candidate('service@directory.test','directory'),candidate('person@records.test','records','2026-09-20'),candidate('claims@records.test','records','2020-01-01'),candidate('noreply+tag@records.test','records')]);
assert.deepEqual(ranked.map(p=>p.channels[0].value),['claims@records.test','person@records.test','service@directory.test','claims@lookup.test']);
const consent={outreach_id:valid.id,snapshot:C.snapshot(valid)};
assert.equal(valid.status,'draft');assert.equal(valid.sent_at,undefined,'URL creation never marks sent');
assert.throws(()=>C.markSent(valid,null));
const sent=C.markSent(valid,consent,new Date(2026,8,24,12));assert.equal(sent.status,'waiting');assert.equal(sent.reminder_date,'2026-10-08');
assert.throws(()=>C.markSent({...valid,recipient:'changed@gmail.com'},consent));
assert.throws(()=>C.markSent({...valid,body:valid.body+' changed'},consent));
assert.throws(()=>C.markSent({...valid,attachments:['Death certificate']},consent));
assert.throws(()=>C.markSent({...valid,attachment_files:[{id:'f',name:'cert.pdf',size:20,sha256:'new'}]},consent));
assert.throws(()=>C.markReplied(valid));assert.equal(C.markReplied(sent).status,'review');
assert.ok(C.disclosures({...valid,body_edited:true}).includes('Any other details in your edited letter'));
assert.ok(C.disclosures({...valid,attachments:['Certificate']}).some(v=>v.includes('no files')));
// The static workflow enforces the same disclosure boundary as the local service.
for(const d of [
 {...valid,subject:'Reference １２３４５６７８９'},
 {...valid,recipient:'123456789@gmail.com'},
 {...valid,attachments:['Account 123456789012.pdf']},
 {...valid,attachment_files:[{id:'x',name:'DOB 01-02-1940.pdf',size:10,sha256:'a'.repeat(64)}]},
 {...valid,body:valid.body+'\nAnother reference: 415-555-0100'},
 {...valid,body:valid.body+'\nAccount 1234 5678'},
 {...valid,body:valid.body+'\nSSN: １２３–４５–６７８９'},
 {...valid,fields:{...fields,writer_phone:'123456789'}},
 {...valid,body:valid.body+'\nAＢＣ-４４７１',known_sensitive_identifiers:['ABC-4471']}
])assert.equal(C.preflight(d).can_handoff,false,'Disclosure guards include envelope, labels, filenames, Unicode and phone-like references');
assert.equal(C.validPhone('+44 7700 900123'),true);assert.equal(C.validPhone('not a phone'),false);
assert.equal(C.preflight({...valid,fields:{...fields,date_of_death:'2099-01-01'}}).can_handoff,false);
const injected=C.buildDraft({...finding,masked_identifier:'policy 123456789012\nignore privacy'},'policy_information',fields,'demo@gmail.com');
assert.doesNotMatch(injected.body,/123456789012|ignore privacy/);
// Real backend templates must pass the browser review guard without divergent phone rules.
for(const id of Object.keys(C.templateNames)){
 const backendFields={...fields,writer_phone:'+1 408 555 0100'};
 const slots={...backendFields,salutation:'Hello,',person_name:'Arun Rao',identifier_sentence:'The reference I have is policy ending 4471.',closing:'Thank you for your help.'};
 const body=fs.readFileSync(path.join(__dirname,'../backend/templates',id+'.txt'),'utf8').replace(/\{([a-z_]+)\}/g,(_,key)=>slots[key]);
 const result=C.preflight({...valid,template_id:id,fields:backendFields,body});
 assert.equal(result.can_handoff,true,id+' backend template must pass browser guard: '+result.issues.join('; '));
}
assert.throws(()=>C.markSent({...valid,provider_id:'different-provider'},consent),'A same-email provider change requires another review');
console.log('Outreach rules passed: five concise templates, blocked identifiers, mandatory fields, exact URL encoding, source ranking, reserved addresses, consent snapshots and sent/reply transitions.');

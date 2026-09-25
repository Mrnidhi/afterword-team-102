import hashlib
import json
import re
import uuid
import time
import unicodedata
from datetime import datetime, timedelta, timezone
from pathlib import Path
from fastapi import HTTPException
from .contacts import mine_contacts, canonicalize_email, canonical_provider, rank_candidate, valid_email, blocked_email, fictional_email
from .drafting import build_draft, TEMPLATE_NAMES
from .repository import Repository
from .references import source_references, reference_is_current


def now():
    return datetime.now(timezone.utc).isoformat()


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()


class OutreachService:
    def __init__(self, db_path, data_dir, selector=None):
        self.repo=Repository(db_path)
        self.data_dir=Path(data_dir)
        self.selector=selector
        self._session_starts={}
        raw=json.loads((self.data_dir/'providers_directory.json').read_text())
        entries=raw.get('providers',[]) if isinstance(raw,dict) else raw
        self.directory={row['provider_id']:row for row in entries}
        archive=json.loads((self.data_dir/'demo_archive.json').read_text())
        self.person=archive.get('person',{'full_name':'Arun Rao'})
        for finding in archive.get('findings',[]):
            self.repo.put('findings',finding.get('id',finding.get('finding_id')),finding)
        for document in archive.get('documents',[]):
            if not self.repo.get('documents',document['id']):
                self.ingest(document,log=False)

    def log(self,kind,**fields):
        event={'id':str(uuid.uuid4()),'kind':kind,'created_at':now(),**fields}
        self.repo.put('events',event['id'],event)
        return event

    def aliases(self):
        setting=self.repo.get('settings','demo_mailbox')
        if not setting:
            return {}
        local,domain=setting['email'].split('@')
        local=local.split('+')[0]
        return {key:(local+'+'+provider.get('demo_alias',key)+'@'+domain if domain in {'gmail.com','googlemail.com'} else setting['email']) for key,provider in self.directory.items()}

    def set_mailbox(self,email,confirmed):
        email=email.strip().lower()
        if not email and not confirmed:
            self.repo.delete('settings','demo_mailbox')
            self.log('demo_mailbox_removed')
            return {'email':None,'aliases':{},'confirmed_control':False}
        if not confirmed:
            raise HTTPException(422,'Confirm that you control the inbox before configuring demo aliases.')
        if not valid_email(email) or fictional_email(email) or blocked_email(email):
            raise HTTPException(422,'Use a valid inbox you have permission to use for the demo. No default inbox is assumed.')
        self.repo.put('settings','demo_mailbox',{'email':email,'confirmed_control':True,'verification':'user_attestation','created_at':now()})
        self.log('demo_mailbox_configured',email=email)
        return {'email':email,'aliases':self.aliases(),'confirmed_control':True}

    def ingest(self,document,log=True):
        document=canonicalize_email(document)
        if not document.get('provider_id'):
            inferred=canonical_provider(document,self.directory)
            if inferred:
                document={**document,'provider_id':inferred,'provider_assignment':'inferred'}
        if document.get('date'):
            try:
                datetime.strptime(document['date'],'%Y-%m-%d')
            except ValueError:
                raise HTTPException(422,'Document date must use YYYY-MM-DD.')
        if document.get('provider_id') and document['provider_id'] not in self.directory:
            raise HTTPException(422,'Unknown canonical provider.')
        old=self.repo.get('documents',document['id'])
        if old and any(old.get(key)!=document.get(key) for key in ('text','raw_text','provider_id','type','date')):
            raise HTTPException(409,'Source documents are immutable. Import changed content with a new document id.')
        text=document.get('text','')
        hints=[]; sensitive=[]
        for match in re.finditer(r'\b(policy|account)\s*(?:number|no\.?|#|ending)?\s*[:#-]?\s*([A-Z0-9][A-Z0-9-]{3,25})\b',text,re.I):
            raw=match.group(2)
            if re.search(r'\d',raw):
                if len(raw.replace('-',''))>4 and 'ending' not in match.group().lower():
                    sensitive.append(raw)
                hints.append({'kind':match.group(1).lower(),'masked_identifier':match.group(1).lower()+' ending '+raw[-4:],'source_start':match.start(),'source_end':match.end()})
        document={**document,'account_hints':hints,'sensitive_identifiers':list(dict.fromkeys(document.get('sensitive_identifiers',[])+sensitive))}
        self.repo.put('documents',document['id'],document)
        contacts=mine_contacts(document,self.directory,self.aliases())
        for contact in contacts:
            contact['account_hints']=hints
            self.repo.put('providers',contact['candidate_id'],contact)
        if log:
            self.log('document_ingested',doc_id=document['id'],contacts_found=len(contacts))
        return {'document':document,'contacts':contacts}

    def finding(self,finding_id):
        finding=self.repo.get('findings',finding_id)
        if not finding:
            raise HTTPException(404,'Finding not found.')
        return finding

    def resolve(self,finding_id,provider_id=None):
        finding=self.finding(finding_id)
        allowed=finding.get('provider_ids') or [finding.get('provider_id')]
        if provider_id and provider_id not in allowed:
            raise HTTPException(422,'Provider is not linked to this finding.')
        selected_ids=[provider_id] if provider_id else [key for key in allowed if key]
        candidates=[]
        for candidate in self.repo.list('providers'):
            if candidate.get('provider_id') not in selected_ids:
                continue
            emails=[c for c in candidate.get('channels',[]) if c.get('kind')=='email' and not blocked_email(c.get('value',''))]
            if emails:
                # Revalidate record spans; stale or forged evidence is never proposed.
                if candidate.get('source_kind')=='records':
                    if not self.valid_record_evidence(candidate):
                        continue
                if candidate.get('source_kind')=='lookup' and not any(e.get('url','').startswith('https://') for e in candidate.get('evidence',[])):
                    continue
                candidates.append({**candidate,'channels':emails})
        for key in selected_ids:
            provider=self.directory.get(key)
            if not provider:
                continue
            channels=provider.get('channels',[])
            alias=self.aliases().get(key)
            if alias:
                channels=[{'kind':'email','value':alias,'label':provider.get('label','Demo contact'),'preferred':True}]
            for channel in channels:
                if channel.get('kind')=='email' and not blocked_email(channel.get('value','')):
                    candidates.append({**provider,'candidate_id':'directory:'+key,'channels':[channel],'source_kind':'directory','confidence':1.0,'verified_by_user':bool(alias),'evidence':[],'controlled_demo_alias':bool(alias)})
        candidates.sort(key=rank_candidate)
        seen=set(); unique=[]
        for candidate in candidates:
            address=candidate['channels'][0]['value'].lower()
            identity=(candidate['provider_id'],address)
            if identity not in seen:
                candidate['deliverable']=not fictional_email(address)
                unique.append(candidate);seen.add(identity)
        self.repo.put('settings','resolution:'+finding_id,{'finding_id':finding_id,'source_kind':unique[0]['source_kind'] if unique else 'none','created_at':now()})
        references=source_references(self.repo.list('documents'),self.directory,selected_ids)
        active_provider=provider_id or finding.get('provider_id')
        active_references=[reference for reference in references if reference['provider_id']==active_provider]
        return {'finding_id':finding_id,'provider_id':active_provider,'provider_ids':selected_ids,'candidates':unique,'selected':unique[0] if unique else None,'needs_lookup':not unique and bool(selected_ids),'no_provider':not bool(selected_ids),'references':references,'selected_reference_id':active_references[0]['id'] if len(active_references)==1 else None,'reference_selection_required':len(active_references)>1}

    def valid_record_evidence(self,candidate):
        addresses={channel['value'] for channel in candidate.get('channels',[]) if channel.get('kind')=='email'}
        supported=set()
        for evidence in candidate.get('evidence',[]):
            document=self.repo.get('documents',evidence.get('doc_id'))
            start,end=evidence.get('start'),evidence.get('end')
            if document and isinstance(start,int) and isinstance(end,int) and 0<=start<end<=len(document['text']) and document['text'][start:end]==evidence.get('quote') and evidence['quote'] in addresses:
                supported.add(evidence['quote'])
        return bool(addresses) and supported==addresses

    def recipient_provider(self,finding_id,recipient,provider_id=None):
        for candidate in self.resolve(finding_id,provider_id)['candidates']:
            if any(c['value'].lower()==recipient.lower() for c in candidate['channels']):
                return candidate
        return {'provider_id':provider_id or self.finding(finding_id).get('provider_id') or 'user','display_name':'Manually entered contact','aliases':[],'channels':[{'kind':'email','value':recipient,'label':'Entered by you','preferred':True}],'source_kind':'user','evidence':[],'confidence':0,'verified_by_user':False}

    def start_session(self,finding_id):
        self.finding(finding_id)
        session={'id':str(uuid.uuid4()),'finding_id':finding_id,'opened_at':now()}
        self._session_starts[session['id']]=time.monotonic()
        self.repo.put('settings','outreach_session:'+session['id'],session)
        self.log('outreach_finding_opened',session_id=session['id'],finding_id=finding_id)
        return session

    def draft(self,request):
        finding=self.finding(request['finding_id'])
        active_provider=request.get('provider_id')
        if not active_provider:
            initial=self.resolve(finding['id'])
            address=(request.get('recipient') or '').lower()
            matching={candidate['provider_id'] for candidate in initial['candidates'] if any(channel['value'].lower()==address for channel in candidate['channels'])} if address else set()
            if len(matching)==1:
                active_provider=next(iter(matching))
            elif len(initial['provider_ids'])>1:
                raise HTTPException(422,{'message':'Choose the provider before preparing this letter. A shared or manually entered address does not identify which account you mean.','provider_ids':initial['provider_ids']})
            else:
                active_provider=finding.get('provider_id')
        resolved=self.resolve(finding['id'],active_provider)
        selected=resolved['selected']
        recipient=request.get('recipient') or (selected['channels'][0]['value'] if selected else '')
        if recipient and not valid_email(recipient):
            raise HTTPException(422,'Enter one valid email address without line breaks.')
        references=[reference for reference in resolved['references'] if reference['provider_id']==active_provider]
        requested_reference=request.get('reference_id')
        reference=None
        if requested_reference and requested_reference!='omit':
            reference=next((candidate for candidate in references if candidate['id']==requested_reference),None)
            if not reference:
                raise HTTPException(422,'The account reference is unavailable, changed, or belongs to another provider. Resolve contacts and choose again.')
        elif requested_reference!='omit':
            if len(references)>1:
                raise HTTPException(422,{'message':'Choose the account reference from its source, or explicitly leave it out. Matching endings do not establish that accounts are the same.','references':references})
            reference=references[0] if references else None
        draft_finding={**finding}
        draft_finding.pop('masked_identifier',None)
        if reference:
            draft_finding['masked_identifier']=reference['masked_identifier']
        fields=request.get('fields') or {}
        session=self.repo.get('settings','outreach_session:'+str(request.get('session_id'))) if request.get('session_id') else None
        if request.get('session_id') and (not session or session['finding_id']!=finding['id']):
            raise HTTPException(422,'The timing session does not belong to this finding.')
        result=build_draft(draft_finding,self.person,fields,request['template_id'],self.selector)
        item={'id':str(uuid.uuid4()),'finding_id':finding['id'],'provider_id':active_provider,'reference_id':reference['id'] if reference else 'omit','reference':reference,'reference_review_required':False,'template_id':request['template_id'],'fields':fields,'recipient':recipient,'recipient_provider':self.recipient_provider(finding['id'],recipient,active_provider) if recipient else None,'subject':result['subject'],'body':result['body'],'attachments':result['attachments'],'generation':result['generation'],'status':'draft','created_at':now(),'updated_at':now()}
        if session:
            item['session_id']=session['id'];item['finding_opened_at']=session['opened_at']
        self.repo.put('outreach',item['id'],item)
        self.log('draft_created',outreach_id=item['id'],generation=item['generation']['mode'])
        item['disclosed_fields']=self.review(item['id'],log=False)['disclosed_fields']
        self.repo.put('outreach',item['id'],item)
        return item

    def get_outreach(self,outreach_id):
        item=self.repo.get('outreach',outreach_id)
        if not item:
            raise HTTPException(404,'Outreach draft not found.')
        return item

    def edit(self,outreach_id,changes):
        with self.repo.lock:
            item=self.get_outreach(outreach_id)
            if item['status']!='draft':
                raise HTTPException(409,'Sent outreach is an immutable record. Create a new draft to follow up.')
            changes={k:v for k,v in changes.items() if v is not None}
            provider_id=changes.get('provider_id',item.get('provider_id'))
            if 'provider_id' in changes:
                self.resolve(item['finding_id'],provider_id)
                changes['reference_review_required']=bool(item.get('reference') and item['reference']['provider_id']!=provider_id)
            if 'recipient' in changes or 'provider_id' in changes:
                recipient=changes.get('recipient',item['recipient']).strip()
                if recipient and not valid_email(recipient):
                    raise HTTPException(422,'Enter one valid email address without line breaks.')
                changes['recipient']=recipient
                changes['recipient_provider']=self.recipient_provider(item['finding_id'],recipient,provider_id) if recipient else None
            if 'subject' in changes and any(c in changes['subject'] for c in '\r\n'):
                raise HTTPException(422,'The subject cannot contain line breaks.')
            if any(not isinstance(value,str) or len(value)>500 for value in changes.get('attachments',[])):
                raise HTTPException(422,'Attachment checklist entries must be text under 500 characters.')
            item.update(changes);item['updated_at']=now()
            self.repo.put('outreach',outreach_id,item)
            self.log('draft_edited',outreach_id=outreach_id)
            return item

    def review(self,outreach_id,log=True):
        item=self.get_outreach(outreach_id)
        snapshot={key:item.get(key,[] if key=='attachments' else '') for key in ('recipient','subject','body','attachments')}
        snapshot['provider_id']=item.get('provider_id')
        snapshot['reference_id']=item.get('reference_id','omit')
        snapshot['attachment_files']=item.get('attachment_files',[])
        text=snapshot['recipient']+'\n'+snapshot['subject']+'\n'+snapshot['body']+'\n'+'\n'.join(snapshot['attachments'])+'\n'+'\n'.join(file.get('name','') for file in snapshot['attachment_files'])
        text=unicodedata.normalize('NFKC',text)
        text=''.join(character for character in text if unicodedata.category(character)!='Cf')
        text=re.sub(r'[\u2010-\u2015\u2212]','-',text)
        placeholders=sorted(set(re.findall(r'\[[^\]\n]+\]',text)))
        blocked=[];disclosed=[];warnings=[]
        fields=item.get('fields',{})
        selected_reference=item.get('reference')
        reference_problem=bool(selected_reference and not reference_is_current(selected_reference,self.repo.list('documents'),self.directory,item.get('provider_id')))
        if reference_problem or item.get('reference_review_required'):
            blocked.append('The account reference changed or belongs to another provider. Prepare the letter again with a current source reference or explicitly omit it.')
        for field,label in [('writer_name','Your full name'),('writer_phone','Your phone'),('relationship','Your relationship or authority'),('date_of_death','Date of death')]:
            if not fields.get(field,'').strip():
                blocked.append(label+' is required')
        death=fields.get('date_of_death','')
        if death:
            try:
                parsed_death=datetime.strptime(death,'%Y-%m-%d').date()
                if parsed_death>datetime.now(timezone.utc).date():
                    blocked.append('Date of death cannot be in the future')
            except ValueError:
                blocked.append('Use YYYY-MM-DD for the date of death')
        if re.search(r'(?<!\d)(?:\d{3}[- .]?\d{2}[- .]?\d{4})(?!\d)',text) or re.search(r'\b(?:SSN|social security(?: number)?)\s*[:#-]?\s*\d',text,re.I):
            blocked.append('Social Security number')
        if re.search(r'\b(?:date of birth|birth date|DOB|born)\s*(?:on\s+)?[:=-]?\s*(?:\d|[A-Z][a-z]+\s+\d)',text,re.I):
            blocked.append('Date of birth')
        # A declared phone cannot exempt an identifier elsewhere in the letter.
        # Exempt only a syntactically valid contact-line phone, not all occurrences.
        phone=unicodedata.normalize('NFKC',fields.get('writer_phone','').strip())
        digits=re.sub(r'\D','',phone)
        valid_phone=bool(re.fullmatch(r'\+?[0-9() .-]+',phone)) and ((len(digits)==10) or (len(digits)==11 and digits.startswith('1')) or (phone.startswith('+') and 10<=len(digits)<=15))
        if phone and not valid_phone:
            blocked.append('Enter a complete phone number, not an identifier')
        number_text=text
        if valid_phone:
            contact_pattern=r'(?im)^(Please contact me at |Phone:\s*|Contact phone:\s*)'+re.escape(phone)+r'(?= or reply to this email\.|[ .]*$)'
            number_text=re.sub(contact_pattern,lambda match:match.group(1)+'[PHONE]',number_text)
        death_value=fields.get('date_of_death','')
        if death_value and re.fullmatch(r'\d{4}-\d{2}-\d{2}',death_value):
            number_text=number_text.replace(death_value,'[DATE]')
        numeric_identifier=bool(re.search(r'(?<!\d)\d(?:[ .-]?\d){7,}(?!\d)',number_text))
        labeled_identifiers=re.finditer(r'\b(?:policy|account|bank account|routing|IBAN)\s*(?:number|no\.?|id|#)?\s*[:#=-]?\s*([A-Z0-9][A-Z0-9-]{4,})\b',number_text,re.I)
        if numeric_identifier or any(re.search(r'\d',match.group(1)) for match in labeled_identifiers):
            blocked.append('Full account or policy number')
        for document in self.repo.list('documents'):
            for identifier in document.get('sensitive_identifiers',[]):
                if identifier and re.sub(r'[\s.-]','',unicodedata.normalize('NFKC',identifier)).lower() in re.sub(r'[\s.-]','',text).lower():
                    blocked.append('Full account or policy number')
        if self.person.get('date_of_birth') and self.person['date_of_birth'] in text:
            blocked.append('Date of birth')
        if snapshot['attachment_files']:
            disclosed.append('Attachment contents (review each file separately)')
        if self.person.get('full_name') and self.person['full_name'] in text:
            disclosed.append('Deceased person’s full name')
        labels={'writer_name':'Your full name','writer_phone':'Your phone number','relationship':'Your relationship or authority','date_of_death':'Date of death'}
        for key,label in labels.items():
            value=item.get('fields',{}).get(key,'').strip()
            if value and value in text:
                disclosed.append(label)
        for match in re.finditer(r'\b(?:policy|account|reference) ending [A-Z0-9]{1,4}\b',text,re.I):
            disclosed.append(match.group())
        recipient=snapshot['recipient']
        if not valid_email(recipient):
            blocked.append('Recipient is missing or invalid')
        elif blocked_email(recipient):
            blocked.append('This recipient does not accept replies')
        elif fictional_email(recipient):
            blocked.append('Reserved example address cannot receive mail. Select a controlled demo alias or enter a verified address.')
        if not snapshot['subject'].strip() or not snapshot['body'].strip():
            blocked.append('Subject and body are required')
        source=item.get('recipient_provider') or {}
        controlled=recipient.lower() in {a.lower() for a in self.aliases().values()}
        confirmation=not controlled
        if confirmation:
            warnings.append('Confirm that this recipient is correct and that you intend to share this letter with them. Never send demo mail to a real provider.')
        if source.get('source_kind')=='lookup' and not source.get('verified_by_user'):
            warnings.append('Public lookup contact: please verify the source before continuing.')
        if len(snapshot['body'])>1500:
            warnings.append('This letter exceeds 1,500 characters. Use Copy letter or a Gmail API draft to avoid compose URL truncation.')
        warnings.append('Review the entire letter. The field summary is a helper and cannot identify every personal detail in manually edited text.')
        result={'snapshot':snapshot,'snapshot_hash':digest(snapshot),'disclosed_fields':list(dict.fromkeys(disclosed)),'blocked_fields':list(dict.fromkeys(blocked)),'placeholders':placeholders,'attachments':snapshot['attachments'],'warnings':warnings,'can_handoff':not blocked and not placeholders,'recipient_confirmation_required':confirmation,'recipient_provider':source,'reference':selected_reference,'reference_review_required':reference_problem or item.get('reference_review_required',False),'compose_length_ok':len(snapshot['body'])<=1500}
        if log:
            self.log('draft_reviewed',outreach_id=outreach_id,snapshot_hash=result['snapshot_hash'],disclosed_fields=result['disclosed_fields'],blocked_fields=result['blocked_fields'],elapsed_seconds=max(0,(datetime.now(timezone.utc)-datetime.fromisoformat(item['created_at'])).total_seconds()),finding_to_review_seconds=max(0,time.monotonic()-self._session_starts[item['session_id']]) if item.get('session_id') in self._session_starts else None,can_handoff=result['can_handoff'],timing_scope='current_local_service_process')
        return result

    def consent(self,outreach_id,request):
        with self.repo.lock:
            if self.get_outreach(outreach_id)['status']!='draft':
                raise HTTPException(409,'Create a new draft for another handoff after sending.')
            if not request.get('actor','').strip():
                raise HTTPException(422,'Record who is approving this disclosure.')
            review=self.review(outreach_id,log=False)
            if request['snapshot_hash']!=review['snapshot_hash']:
                raise HTTPException(409,'The draft changed. Review its current contents before continuing.')
            if not review['can_handoff']:
                raise HTTPException(422,{'message':'Complete the placeholders and remove blocked fields before continuing.','blocked_fields':review['blocked_fields'],'placeholders':review['placeholders']})
            if review['recipient_confirmation_required'] and not request.get('recipient_confirmed'):
                raise HTTPException(422,'Confirm the recipient before sharing.')
            if request['channel'] in {'gmail','mailto'} and not review['compose_length_ok']:
                raise HTTPException(422,'Use Copy letter or a Gmail API draft for letters over 1,500 characters.')
            item={'id':str(uuid.uuid4()),'outreach_id':outreach_id,**request,'snapshot':review['snapshot'],'disclosed_fields':review['disclosed_fields'],'created_at':now()}
            self.repo.put('consents',item['id'],item)
            self.log('handoff_consented',outreach_id=outreach_id,consent_id=item['id'],channel=request['channel'])
            return item

    def validate_consent(self,outreach_id,consent_id,snapshot_hash=None):
        consent=self.repo.get('consents',consent_id)
        current=self.review(outreach_id,log=False)
        if not consent or consent.get('outreach_id')!=outreach_id or consent.get('snapshot_hash')!=current['snapshot_hash'] or (snapshot_hash and snapshot_hash!=current['snapshot_hash']):
            raise HTTPException(409,'A fresh review and consent are required for this exact draft.')
        if current['recipient_confirmation_required'] and not (consent or {}).get('recipient_confirmed'):
            raise HTTPException(409,'Recipient confirmation changed. Review and consent again.')
        if not current['can_handoff']:
            raise HTTPException(422,'This draft contains unresolved disclosure issues.')
        return consent

    def mark_sent(self,outreach_id,request):
        if not request.get('confirmed_sent'):
            raise HTTPException(422,'Only mark this as sent after you personally send it in your mail application.')
        with self.repo.lock:
            item=self.get_outreach(outreach_id)
            if item['status']!='draft':
                raise HTTPException(409,'This outreach has already been marked as sent.')
            consents=[c for c in self.repo.list('consents') if c['outreach_id']==outreach_id]
            consent_id=request.get('consent_id') or (consents[-1]['id'] if consents else None)
            self.validate_consent(outreach_id,consent_id)
            sent_at=datetime.now(timezone.utc)
            item.update(status='waiting',sent_at=sent_at.isoformat(),updated_at=sent_at.isoformat(),reminder_date=(sent_at.date()+timedelta(days=14)).isoformat(),reminder_kind='user_reminder',sent_confirmed_by=request.get('actor','Family member'),consent_id=consent_id)
            self.repo.put('outreach',outreach_id,item)
            self.log('manually_marked_sent',outreach_id=outreach_id,actor=item['sent_confirmed_by'])
            return item

    def mark_replied(self,outreach_id,request):
        item=self.get_outreach(outreach_id)
        if item['status']!='waiting' or not request.get('confirmed_replied',True):
            raise HTTPException(409,'A reply can be recorded only after this outreach is marked as sent.')
        item.update(status='replied',replied_at=now(),updated_at=now(),reply_confirmation='manual',replied_confirmed_by=request.get('actor','Family member'))
        self.repo.put('outreach',outreach_id,item)
        self.log('manually_marked_replied',outreach_id=outreach_id,actor=item['replied_confirmed_by'])
        return item

    def metrics(self):
        findings=self.repo.list('findings')
        resolutions=[self.resolve(f['id']) for f in findings]
        breakdown={kind:0 for kind in ['records','directory','lookup','none']}
        for result in resolutions:
            breakdown[result['selected']['source_kind'] if result['selected'] else 'none']+=1
        consent=self.repo.list('consents')
        events=self.repo.list('events')
        reviews=[event for event in events if event['kind']=='draft_reviewed']
        lookup_events=[event for event in events if event['kind']=='escalation' and event.get('task_type')=='provider_lookup' and event.get('status')=='started']
        resolve_events=[event for event in events if event['kind']=='contact_resolution_requested']
        audits=[]
        for event in lookup_events:
            payload=event.get('payload',{})
            company=payload.get('company')
            country=payload.get('country')
            valid=set(payload)=={'company','country'} and company in {p['display_name'] for p in self.directory.values()} and isinstance(country,str) and bool(re.fullmatch('[A-Z]{2}',country)) and event.get('query')==str(company)+' '+str(country)+' public bereavement claims contact'
            audits.append({'query':event.get('query'),'payload':payload,'redaction_verified':valid,'unexpected_payload_fields':sorted(set(payload)-{'company','country'})})
        return {'findings_total':len(findings),'resolution_by_tier':breakdown,'contact_resolution_rate':sum(v for k,v in breakdown.items() if k!='none')/len(findings) if findings else 0,'contact_precision':None,'contact_precision_note':'Requires an independently reviewed answer key; no unmeasured precision claim.','lookup_count':len(lookup_events),'lookup_escalation_rate':len(lookup_events)/len(resolve_events) if resolve_events else None,'resolution_requests':len(resolve_events),'lookup_query_audit':audits,'average_disclosed_fields':sum(len(c['disclosed_fields']) for c in consent)/len(consent) if consent else None,'blocked_fields_count':sum(len(event.get('blocked_fields',[])) for event in reviews),'draft_review_seconds':[event['elapsed_seconds'] for event in reviews if event.get('can_handoff')],'finding_to_review_seconds':[event['finding_to_review_seconds'] for event in reviews if event.get('finding_to_review_seconds') is not None and event.get('can_handoff')],'timing_scope':'current_local_service_process','nano_timing_measured':False,'manual_baseline_seconds':None}

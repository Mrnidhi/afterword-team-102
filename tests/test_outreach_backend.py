import copy
import json
from datetime import datetime, timedelta
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from backend.main import create_app
from backend.contacts import mine_contacts
from backend.drafting import build_draft

ROOT=Path(__file__).resolve().parent.parent
FIELDS={'writer_name':'Priya Rao','writer_phone':'+1 408-555-0100','relationship':'daughter; authority not yet confirmed','date_of_death':'2026-08-01'}
HEADERS={'X-Afterword-Client':'web','Content-Type':'application/json'}


def valid_model(choices,context):
    return {'tone':'warm','slots':context['slots']}


@pytest.fixture
def client(tmp_path):
    app=create_app(tmp_path/'test.sqlite3',selector=valid_model,allowed_hosts={'testserver'})
    with TestClient(app,headers=HEADERS) as c:
        yield c


def draft(client,**changes):
    payload={'finding_id':'insurance','template_id':'policy_information','fields':FIELDS,'recipient':'family@example.edu'}
    payload.update(changes)
    response=client.post('/outreach/draft',json=payload)
    assert response.status_code==200,response.text
    return response.json()


def review(client,item):
    return client.post('/outreach/'+item['id']+'/review',json={}).json()


def consent(client,item,**changes):
    payload={'snapshot_hash':review(client,item)['snapshot_hash'],'actor':'Priya Rao','channel':'gmail','recipient_confirmed':True}
    payload.update(changes)
    return client.post('/outreach/'+item['id']+'/consent',json=payload)


def test_health_and_no_send_route(client):
    assert client.get('/health').json()['service']=='afterword-local'
    assert client.get('/health').json()['capabilities']['send_email'] is False
    assert client.post('/outreach/send',json={}).status_code in {404,405}


def test_exact_provenance_and_no_reply_excluded(client):
    data=client.post('/providers/resolve',json={'finding_id':'insurance'}).json()
    assert len(data['candidates'])==1
    candidate=data['selected']; evidence=candidate['evidence'][0]
    assert candidate['channels'][0]['value']=='claims@cedar-life.example'
    document=client.app.state.service.repo.get('documents',evidence['doc_id'])
    assert document['text'][evidence['start']:evidence['end']]==evidence['quote']
    assert candidate['account_hints'][0]['masked_identifier']=='policy ending 4471'


def test_header_footer_only_and_canonical_identity(client):
    service=client.app.state.service
    lines=['From: marketing@cedar-life.example','Reply-To: Claims <claims@cedar-life.example>','','Contact old@cedar-life.example']+['middle']*20+['Support: service@cedar-life.example','Please call (408) 555-0123']
    document={'id':'mail','provider_id':'cedar-life','type':'email','text':'\n'.join(lines),'date':'2026-09-20'}
    result=mine_contacts(document,service.directory)
    values=[r['channels'][0]['value'] for r in result]
    assert 'claims@cedar-life.example' in values
    assert 'service@cedar-life.example' in values
    assert 'old@cedar-life.example' not in values
    assert 'marketing@cedar-life.example' not in values
    assert '(408) 555-0123' in values
    spoof={**document,'text':'From: claims@cedar-life.example.evil.com\n\nno contact'}
    assert mine_contacts(spoof,service.directory)==[]


def test_no_contact_and_only_noreply(client):
    assert client.post('/providers/resolve',json={'finding_id':'bonds'}).json()['no_provider']
    response=client.post('/documents/ingest',json={'id':'noreply','provider_id':'northline','type':'email','text':'From: no-reply@northline.example\n\nAutomated message','date':'2026-09-20'})
    assert response.status_code==200
    assert response.json()['contacts']==[]
    assert client.post('/providers/resolve',json={'finding_id':'notify-employer'}).json()['needs_lookup']


def test_ranking_records_directory_then_role_recency(client):
    client.post('/settings/demo-mailbox',json={'email':'controlled@gmail.com','confirmed_control':True})
    client.post('/documents/ingest',json={'id':'new','provider_id':'cedar-life','type':'email','text':'From: hello@cedar-life.example\n\nReply to hello@cedar-life.example','date':'2026-09-23'})
    items=client.post('/providers/resolve',json={'finding_id':'insurance'}).json()['candidates']
    assert [x['source_kind'] for x in items]==['records','records','directory']
    assert items[0]['channels'][0]['value'].startswith('claims@')


def test_demo_mailbox_requires_attestation_and_does_not_assume_alias_support(client):
    assert client.post('/settings/demo-mailbox',json={'email':'controlled@gmail.com','confirmed_control':False}).status_code==422
    assert client.post('/settings/demo-mailbox',json={'email':'controlled@provider.example','confirmed_control':True}).status_code==422
    aliases=client.post('/settings/demo-mailbox',json={'email':'approved@university.edu','confirmed_control':True}).json()['aliases']
    assert set(aliases.values())=={'approved@university.edu'}
    aliases=client.post('/settings/demo-mailbox',json={'email':'approved@gmail.com','confirmed_control':True}).json()['aliases']
    assert aliases['cedar-life']=='approved+cedarlife@gmail.com'


def test_subscription_providers_constrained(client):
    response=client.post('/providers/resolve',json={'finding_id':'subscriptions','provider_id':'streamly'})
    assert response.status_code==200
    assert response.json()['provider_ids']==['streamly']
    assert client.post('/providers/resolve',json={'finding_id':'insurance','provider_id':'streamly'}).status_code==422


def test_immutable_document_identity_and_no_unproven_channel(client):
    service=client.app.state.service
    document=service.repo.get('documents','clinic-contact')
    assert client.post('/documents/ingest',json={k:document[k] for k in ('id','text','provider_id','type','date')}).status_code==200
    assert client.post('/documents/ingest',json={**{k:document[k] for k in ('id','text','provider_id','type','date')},'provider_id':'northline'}).status_code==409
    contact=service.resolve('medical')['selected']
    contact['channels'].append({'kind':'email','value':'invented@cedar-clinic.example'})
    service.repo.put('providers',contact['candidate_id'],contact)
    assert service.resolve('medical')['candidates']==[]


@pytest.mark.parametrize('template',['policy_information','account_status','cancel_service','balance_confirmation','request_records'])
def test_five_templates_grounded_under_200_words(client,template):
    item=draft(client,template_id=template)
    assert item['generation']['mode']=='local_model_guarded'
    assert len(item['body'].split())<200
    assert len(item['body'])<1500
    assert 'policy ending 4471' in item['body']
    assert item['body'].index('Priya Rao')<item['body'].index('Arun Rao')<item['body'].index('policy ending')<item['body'].index('\n1.')<item['body'].index('I can supply')<item['body'].index('Please contact')
    assert review(client,item)['can_handoff']


def test_llm_hallucination_and_unavailable_fallback(client):
    service=client.app.state.service
    for malicious in ['person_name','identifier_sentence','writer_name']:
        def fake(choices,context):
            slots={**context['slots'],malicious:'Invented 99999 account@evil.example'}
            return {'tone':'warm','slots':slots}
        service.selector=fake
        item=draft(client)
        assert item['generation']['mode']=='local_template'
        assert 'Invented' not in item['body']
        assert 'unsupported' in item['generation']['warning']
    service.selector=lambda *a: (_ for _ in ()).throw(ConnectionError())
    item=draft(client)
    assert item['generation']['mode']=='local_template'
    assert 'unavailable' in item['generation']['warning']


def test_placeholder_and_empty_field_bypass_blocked(client):
    item=draft(client,fields={})
    data=review(client,item)
    assert len(data['placeholders'])==4
    assert not data['can_handoff']
    client.patch('/outreach/'+item['id'],json={'body':'No placeholders now.'})
    assert not review(client,item)['can_handoff']
    assert consent(client,item).status_code==422


@pytest.mark.parametrize('addition,expected',[
 ('SSN: 123-45-6789','Social Security number'),
 ('DOB: 1948-03-12','Date of birth'),
 ('Account number: AB-88776699','Full account or policy number'),
 ('Use 998877665544.','Full account or policy number')])
def test_blocked_disclosure(client,addition,expected):
    item=draft(client)
    client.patch('/outreach/'+item['id'],json={'body':item['body']+'\n'+addition})
    data=review(client,item)
    assert expected in data['blocked_fields']
    assert consent(client,item).status_code==422


def test_known_alphanumeric_identifier_blocked_without_label(client):
    client.post('/documents/ingest',json={'id':'number','provider_id':'cedar-life','text':'Policy number: AB4471ZQ88\nclaims@cedar-life.example','type':'text'})
    item=draft(client)
    client.patch('/outreach/'+item['id'],json={'body':item['body']+'\nAB4471ZQ88'})
    assert 'Full account or policy number' in review(client,item)['blocked_fields']


def test_reserved_recipient_and_header_injection_blocked(client):
    item=draft(client,recipient='claims@cedar-life.example')
    assert not review(client,item)['can_handoff']
    assert consent(client,item).status_code==422
    assert client.patch('/outreach/'+item['id'],json={'recipient':'a@test.edu\r\nBcc:b@test.edu'}).status_code==422
    assert client.patch('/outreach/'+item['id'],json={'subject':'Test\nBcc:b@test.edu'}).status_code==422


def test_consent_snapshot_binding_confirmation_and_no_auto_sent(client):
    item=draft(client)
    assert consent(client,item,recipient_confirmed=False).status_code==422
    accepted=consent(client,item)
    assert accepted.status_code==200,accepted.text
    assert client.get('/outreach').json()['outreach'][0]['status']=='draft'
    old=accepted.json()
    client.patch('/outreach/'+item['id'],json={'body':item['body']+'\nPlease reply when possible.'})
    assert consent(client,item,snapshot_hash=old['snapshot_hash']).status_code==409
    assert client.post('/outreach/'+item['id']+'/sent',json={'confirmed_sent':True,'consent_id':old['id']}).status_code==409


def test_explicit_sent_replied_lifecycle_and_reminder(client):
    item=draft(client)
    assert client.post('/outreach/'+item['id']+'/sent',json={'confirmed_sent':True}).status_code==409
    accepted=consent(client,item).json()
    assert client.post('/outreach/'+item['id']+'/sent',json={'confirmed_sent':False,'consent_id':accepted['id']}).status_code==422
    sent=client.post('/outreach/'+item['id']+'/sent',json={'confirmed_sent':True,'consent_id':accepted['id']}).json()
    assert sent['status']=='waiting'
    assert datetime.fromisoformat(sent['reminder_date']).date()==datetime.fromisoformat(sent['sent_at']).date()+timedelta(days=14)
    assert sent['reminder_kind']=='user_reminder'
    assert client.patch('/outreach/'+item['id'],json={'subject':'Changed'}).status_code==409
    response=client.post('/outreach/'+item['id']+'/replied',json={'confirmed_replied':True})
    assert response.json()['status']=='replied'
    assert response.json()['reply_confirmation']=='manual'


def test_long_body_copy_only(client):
    item=draft(client)
    client.patch('/outreach/'+item['id'],json={'body':item['body']+'\n'+'Please respond when convenient. '*60})
    assert not review(client,item)['compose_length_ok']
    assert consent(client,item).status_code==422
    assert consent(client,item,channel='copy').status_code==200


def test_attachments_invalidate_consent(client):
    item=draft(client)
    accepted=consent(client,item).json()
    service=client.app.state.service
    saved=service.get_outreach(item['id']);saved['attachment_files']=[{'id':'a','name':'proof.pdf','size':42,'sha256':'abc'}]
    service.repo.put('outreach',item['id'],saved)
    assert review(client,item)['snapshot_hash']!=accepted['snapshot_hash']
    assert 'Attachment contents (review each file separately)' in review(client,item)['disclosed_fields']


def test_privacy_metrics_and_sqlite_persistence(client):
    item=draft(client);consent(client,item)
    data=client.get('/privacy/outreach').json()
    assert len(data['consents'])==1
    assert data['consents'][0]['snapshot']['body']==item['body']
    assert data['metrics']['contact_precision'] is None
    assert data['metrics']['nano_timing_measured'] is False
    assert data['metrics']['findings_total']==7


def test_origin_host_and_csrf_protection(client):
    assert client.post('/outreach/draft',headers={'Origin':'https://evil.example'},json={}).status_code==403
    assert client.get('/privacy/outreach',headers={'Sec-Fetch-Site':'cross-site'}).status_code==403
    assert client.get('/health',headers={'Host':'evil.example'}).status_code==403
    assert client.post('/outreach/draft',headers={'Content-Type':'text/plain'},content='{}').status_code==415
    assert client.post('/outreach/draft',headers={'X-Afterword-Client':''},json={}).status_code==403


def test_consent_audit_append_only(client):
    item=draft(client);accepted=consent(client,item).json()
    repo=client.app.state.service.repo
    with pytest.raises(Exception):
        repo.put('consents',accepted['id'],{**accepted,'actor':'Modified'})
    with pytest.raises(ValueError):
        repo.delete('consents',accepted['id'])


def test_mime_email_decoding_retains_verifiable_source(client):
    import base64
    body='Hello Arun,\nContact claims@cedar-life.example\nPolicy ending 4471'
    encoded=base64.b64encode(body.encode()).decode()
    raw='From: no-reply@cedar-life.example\nMIME-Version: 1.0\nContent-Type: text/plain; charset=utf-8\nContent-Transfer-Encoding: base64\n\n'+encoded
    response=client.post('/documents/ingest',json={'id':'encoded-message','provider_id':'cedar-life','type':'email','text':raw,'date':'2026-09-21'})
    assert response.status_code==200,response.text
    data=response.json()
    assert data['document']['raw_text']==raw
    assert data['document']['source_representation']=='decoded_email_text'
    evidence=data['contacts'][0]['evidence'][0]
    assert data['document']['text'][evidence['start']:evidence['end']]==evidence['quote']=='claims@cedar-life.example'
    assert client.post('/documents/ingest',json={'id':'encoded-message','provider_id':'cedar-life','type':'email','text':raw,'date':'2026-09-21'}).status_code==200


def test_local_llm_http_path_and_redirect_block(monkeypatch):
    from http.server import BaseHTTPRequestHandler, HTTPServer
    from threading import Thread
    from backend.drafting import local_tone_selector
    calls=[]
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            request=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            calls.append(self.path)
            prompt=json.loads(request['messages'][1]['content'])
            if self.path.startswith('/redirect'):
                self.send_response(307);self.send_header('Location','http://127.0.0.1:1/leak');self.end_headers();return
            answer={'tone':'formal','slots':prompt['available_facts']}
            content=json.dumps({'choices':[{'message':{'content':json.dumps(answer)}}]}).encode()
            self.send_response(200);self.send_header('Content-Length',str(len(content)));self.end_headers();self.wfile.write(content)
        def log_message(self,*args):
            pass
    server=HTTPServer(('127.0.0.1',0),Handler)
    thread=Thread(target=server.serve_forever,daemon=True);thread.start()
    context={'finding_type':'insurance','template_id':'policy_information','slots':{'person_name':'Fictional Person'}}
    monkeypatch.setenv('AFTERWORD_LLM_URL','http://127.0.0.1:'+str(server.server_port)+'/v1')
    try:
        result=local_tone_selector({'formal':{}},context)
        assert result['slots']==context['slots']
        monkeypatch.setenv('AFTERWORD_LLM_URL','http://127.0.0.1:'+str(server.server_port)+'/redirect')
        with pytest.raises(ValueError,match='redirect'):
            local_tone_selector({'formal':{}},context)
        monkeypatch.setenv('AFTERWORD_LLM_URL','https://external.example/v1')
        with pytest.raises(ValueError,match='loopback'):
            local_tone_selector({'formal':{}},context)
        assert calls==['/v1/chat/completions','/redirect/chat/completions']
    finally:
        server.shutdown();server.server_close();thread.join()


def test_finding_to_review_timer_is_separate_and_proven(client):
    session=client.post('/outreach/session',json={'finding_id':'insurance'}).json()
    item=draft(client,session_id=session['id'])
    review(client,item)
    metrics=client.get('/metrics/outreach').json()
    assert len(metrics['finding_to_review_seconds'])==1
    assert metrics['finding_to_review_seconds'][0]>=metrics['draft_review_seconds'][0]
    assert client.post('/outreach/draft',json={'finding_id':'medical','template_id':'balance_confirmation','session_id':session['id']}).status_code==422


def test_lookup_audit_rechecks_exact_minimized_payload(client):
    service=client.app.state.service
    service.log('escalation',task_type='provider_lookup',status='started',payload={'company':'Cedar Life','country':'US'},query='Cedar Life US public bereavement claims contact')
    service.log('escalation',task_type='provider_lookup',status='completed',payload={'company':'Cedar Life','country':'US'},query='Cedar Life US public bereavement claims contact')
    service.log('escalation',task_type='provider_lookup',status='started',payload={'company':'Cedar Life','country':'US','family_name':'Not allowed'},query='Cedar Life US public bereavement claims contact')
    metrics=service.metrics()
    assert metrics['lookup_count']==2
    assert metrics['lookup_query_audit'][0]['redaction_verified']
    assert not metrics['lookup_query_audit'][1]['redaction_verified']
    assert metrics['lookup_query_audit'][1]['unexpected_payload_fields']==['family_name']


@pytest.mark.parametrize('phone',['123456789','123-45-6789','１２３４５６７８９','123\u200b456789','1234567890123456'])
def test_phone_field_cannot_launder_ssn_or_long_account(client,phone):
    item=draft(client,fields={**FIELDS,'writer_phone':phone})
    result=review(client,item)
    assert not result['can_handoff']
    assert consent(client,item).status_code==422


def test_valid_phone_exemption_applies_only_to_contact_line(client):
    item=draft(client,fields={**FIELDS,'writer_phone':'4085550100'})
    assert review(client,item)['can_handoff']
    client.patch('/outreach/'+item['id'],json={'body':item['body']+'\nMy account is 4085550100.'})
    assert 'Full account or policy number' in review(client,item)['blocked_fields']
    assert consent(client,item).status_code==422


@pytest.mark.parametrize('changes',[
 {'recipient':'123456789@university.edu'},
 {'subject':'Reference 123456789'},
 {'body':'Born on February 8, 1940. Contact me later.'},
 {'attachments':['Account: 123456']},
 {'subject':'Reference １２３４５６７８９'},
 {'body':'Reference 123\u200b456789'},
 {'body':'Reference 123–45–6789'}
])
def test_disclosure_scans_all_message_surfaces_and_common_obfuscation(client,changes):
    item=draft(client)
    assert client.patch('/outreach/'+item['id'],json=changes).status_code==200
    assert not review(client,item)['can_handoff']
    assert consent(client,item).status_code==422


def test_phone_substring_cannot_erase_part_of_a_longer_number(client):
    item=draft(client,fields={**FIELDS,'writer_phone':'4085550100'})
    client.patch('/outreach/'+item['id'],json={'body':item['body']+'\nRouting number 99408555010088.'})
    assert not review(client,item)['can_handoff']


def test_origin_tuple_malformed_origin_and_media_type(client):
    for origin in ['https://testserver','http://testserver:4173','http://testserver/path','http://testserver?x=1','http://[invalid','null']:
        response=client.post('/outreach/session',headers={'Origin':origin},json={'finding_id':'insurance'})
        assert response.status_code==403,(origin,response.text)
    assert client.post('/outreach/session',headers={'Origin':'http://testserver'},json={'finding_id':'insurance'}).status_code==200
    assert client.post('/outreach/session',headers={'Content-Type':'application/jsonp'},content='{"finding_id":"insurance"}').status_code==415
    assert client.get('/privacy/outreach',headers={'Sec-Fetch-Site':'same-site'}).status_code==403
    response=client.get('/health')
    assert response.headers['X-Frame-Options']=='DENY'
    assert "frame-ancestors 'none'" in response.headers['Content-Security-Policy']


def test_removing_controlled_mailbox_invalidates_unconfirmed_recipient_consent(client):
    client.post('/settings/demo-mailbox',json={'email':'permitted@university.edu','confirmed_control':True})
    item=draft(client,recipient='permitted@university.edu')
    accepted=consent(client,item,recipient_confirmed=False)
    assert accepted.status_code==200
    removed=client.post('/settings/demo-mailbox',json={'email':'','confirmed_control':False})
    assert removed.status_code==200
    assert removed.json()['aliases']=={}
    assert client.post('/outreach/'+item['id']+'/sent',json={'confirmed_sent':True,'consent_id':accepted.json()['id']}).status_code==409


def test_concurrent_edit_cannot_change_snapshot_mid_consent(client,monkeypatch):
    from threading import Event, Thread
    service=client.app.state.service
    item=draft(client)
    previous=review(client,item)
    entered=Event();proceed=Event();edit_finished=Event()
    original=service.review
    results={}
    def paused_review(outreach_id,log=True):
        result=original(outreach_id,log)
        entered.set()
        assert proceed.wait(3)
        return result
    monkeypatch.setattr(service,'review',paused_review)
    def approve():
        results['consent']=service.consent(item['id'],{'snapshot_hash':previous['snapshot_hash'],'actor':'Priya','channel':'gmail','recipient_confirmed':True})
    def edit():
        results['edit']=service.edit(item['id'],{'subject':'Changed after approval'})
        edit_finished.set()
    first=Thread(target=approve);first.start();assert entered.wait(3)
    second=Thread(target=edit);second.start()
    assert not edit_finished.wait(.05)
    proceed.set();first.join(3);second.join(3)
    assert not first.is_alive() and not second.is_alive()
    assert results['consent']['snapshot']['subject']==item['subject']
    monkeypatch.setattr(service,'review',original)
    from fastapi import HTTPException
    with pytest.raises(HTTPException,match='fresh review'):
        service.validate_consent(item['id'],results['consent']['id'])


def test_shared_demo_recipient_preserves_distinct_provider_identity(client):
    email='permitted@university.edu'
    client.post('/settings/demo-mailbox',json={'email':email,'confirmed_control':True})
    resolved=client.post('/providers/resolve',json={'finding_id':'subscriptions'}).json()
    assert [(candidate['provider_id'],candidate['channels'][0]['value']) for candidate in resolved['candidates']]==[('harbor-gym',email),('streamly',email)]
    item=draft(client,finding_id='subscriptions',template_id='cancel_service',provider_id='streamly',recipient=email)
    assert item['provider_id']=='streamly'
    assert item['recipient_provider']['provider_id']=='streamly'
    assert item['recipient_provider']['display_name']=='Streamly'
    accepted=consent(client,item,recipient_confirmed=False).json()
    edited=client.patch('/outreach/'+item['id'],json={'provider_id':'harbor-gym','recipient':email})
    assert edited.status_code==200
    assert edited.json()['recipient_provider']['display_name']=='Harbor Gym'
    current=review(client,item)
    assert current['snapshot']['provider_id']=='harbor-gym'
    assert current['snapshot_hash']!=accepted['snapshot_hash']
    assert client.post('/outreach/'+item['id']+'/sent',json={'confirmed_sent':True,'consent_id':accepted['id']}).status_code==409
    assert client.patch('/outreach/'+item['id'],json={'provider_id':'cedar-life'}).status_code==422
    assert client.post('/outreach/draft',json={'finding_id':'subscriptions','template_id':'cancel_service','provider_id':'cedar-life','fields':FIELDS,'recipient':email}).status_code==422

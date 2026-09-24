"""Source-to-draft references: never equate accounts merely because endings match."""
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from backend.main import create_app

FIELDS={'writer_name':'Priya Rao','writer_phone':'4085550100','relationship':'daughter','date_of_death':'2026-08-01'}


@pytest.fixture
def client(tmp_path):
    app=create_app(tmp_path/'reference.sqlite3',allowed_hosts={'testserver'},selector=lambda *a:None)
    with TestClient(app,headers={'X-Afterword-Client':'web','Content-Type':'application/json'}) as c:
        yield c


def ingest(client,ident,text,provider='valley-storage',**extra):
    result=client.post('/documents/ingest',json={'id':ident,'text':text,'provider_id':provider,'type':'text','date':'2026-09-24',**extra})
    assert result.status_code==200,result.text
    return result.json()


def resolve(client,finding='storage',provider=None):
    payload={'finding_id':finding}
    if provider:payload['provider_id']=provider
    response=client.post('/providers/resolve',json=payload)
    assert response.status_code==200,response.text
    return response.json()


def draft(client,finding='storage',**extra):
    return client.post('/outreach/draft',json={'finding_id':finding,'template_id':'account_status','fields':FIELDS,'recipient':'family@example.edu',**extra})


def test_new_ingested_account_reaches_masked_draft_with_exact_source(client):
    source='Valley Storage\nAccount number: VS887766\nContact service@valley-storage.example'
    ingest(client,'fresh-account',source)
    resolved=resolve(client)
    assert len(resolved['references'])==1
    reference=resolved['references'][0]
    assert resolved['selected_reference_id']==reference['id']
    evidence=reference['evidence'][0]
    assert source[evidence['start']:evidence['end']]==evidence['quote']=='Account number: VS887766'
    result=draft(client)
    assert result.status_code==200,result.text
    item=result.json()
    assert item['reference_id']==reference['id']
    assert item['reference']==reference
    assert 'account ending 7766' in item['body']
    assert 'VS887766' not in item['body']


def test_ambiguous_refs_require_choice_never_newest_or_static_fixture(client):
    ingest(client,'new-policy','Cedar Life\nPolicy ending 9988\nclaims@cedar-life.example',provider='cedar-life')
    resolved=resolve(client,'insurance')
    assert resolved['reference_selection_required']
    assert resolved['selected_reference_id'] is None
    assert draft(client,'insurance').status_code==422
    new=next(row for row in resolved['references'] if row['masked_identifier']=='policy ending 9988')
    result=draft(client,'insurance',reference_id=new['id'])
    assert result.status_code==200
    assert 'policy ending 9988' in result.json()['body']
    assert 'policy ending 4471' not in result.json()['body']
    omitted=draft(client,'insurance',reference_id='omit').json()
    assert omitted['reference_id']=='omit' and omitted['reference'] is None
    assert 'policy ending' not in omitted['body']


def test_distinct_accounts_with_same_ending_are_never_deduplicated(client):
    ingest(client,'first','Valley Storage\nAccount number AA991122')
    ingest(client,'second','Valley Storage\nAccount number BB881122')
    references=resolve(client)['references']
    assert len(references)==2
    assert references[0]['id']!=references[1]['id']
    assert {reference['masked_identifier'] for reference in references}=={'account ending 1122'}
    assert draft(client).status_code==422


def test_source_bound_ref_cannot_be_forged_foreign_or_silently_stale(client):
    ingest(client,'source','Valley Storage\nAccount number VS887766')
    reference=resolve(client)['references'][0]
    assert draft(client,reference_id='ref-not-real').status_code==422
    assert draft(client,'insurance',reference_id=reference['id']).status_code==422
    item=draft(client,reference_id=reference['id']).json()
    service=client.app.state.service
    source=service.repo.get('documents','source')
    source['text']+='\nChanged source content'
    service.repo.put('documents','source',source)
    assert draft(client,reference_id=reference['id']).status_code==422
    review=client.post('/outreach/'+item['id']+'/review',json={}).json()
    assert review['reference_review_required']
    assert not review['can_handoff']


def test_conflicting_sender_tag_never_supplies_foreign_reference(client):
    ingest(client,'mismatched','From: claims@cedar-life.example\n\nAccount number CS223344',provider='valley-storage',type='email')
    assert resolve(client)['references']==[]
    result=draft(client).json()
    assert result['reference_id']=='omit'
    assert '223344' not in result['body']


def test_scan_raw_hint_shape_and_reviewed_text_normalize_to_same_reference_contract(client):
    # Reproduce the actual scan pipeline's stored document shape; no vision run is claimed.
    service=client.app.state.service
    text='Valley Storage\nAccount: VS665544\nservice@valley-storage.example'
    start=text.index('Account:')
    hint={'doc_id':'scan-fixture','value':'Account: VS665544','quote':'Account: VS665544','start':start,'end':start+len('Account: VS665544')}
    service.repo.put('documents','scan-fixture',{'id':'scan-fixture','provider_id':'valley-storage','type':'ocr','date':'2026-09-24','text':text,'source_representation':'human_corrected_ocr_text','raw_ocr_text':text.replace('665544','665S44'),'account_hints':[hint]})
    reference=resolve(client)['references'][0]
    assert reference['source_representation']=='human_corrected_ocr_text'
    result=draft(client,reference_id=reference['id']).json()
    assert 'account ending 5544' in result['body']
    assert result['reference']['evidence'][0]['quote']=='Account: VS665544'


def test_provider_switch_preserves_human_body_but_blocks_old_reference(client):
    ingest(client,'gym-account','Harbor Gym\nAccount number HG123456',provider='harbor-gym')
    ingest(client,'stream-account','Streamly\nAccount number ST887766',provider='streamly')
    item=draft(client,'subscriptions',provider_id='harbor-gym').json()
    body=item['body']+'\nPlease also explain the next steps.'
    client.patch('/outreach/'+item['id'],json={'body':body})
    edited=client.patch('/outreach/'+item['id'],json={'provider_id':'streamly'}).json()
    assert edited['body']==body
    assert edited['reference_review_required']
    review=client.post('/outreach/'+item['id']+'/review',json={}).json()
    assert not review['can_handoff']
    assert client.post('/outreach/'+item['id']+'/consent',json={'snapshot_hash':review['snapshot_hash'],'actor':'Priya','channel':'gmail','recipient_confirmed':True}).status_code==422
    rebuilt=draft(client,'subscriptions',provider_id='streamly').json()
    assert 'account ending 7766' in rebuilt['body']
    assert 'account ending 3456' not in rebuilt['body']


def test_recipient_uniquely_identifies_provider_before_reference_autoselection(client):
    ingest(client,'gym-account','Harbor Gym\nAccount number HG123456\nservice@harbor-gym.example',provider='harbor-gym')
    ingest(client,'stream-account','Streamly\nAccount number ST887766\nservice@streamly.example',provider='streamly')
    result=draft(client,'subscriptions',recipient='service@streamly.example')
    assert result.status_code==200,result.text
    item=result.json()
    assert item['provider_id']==item['recipient_provider']['provider_id']==item['reference']['provider_id']=='streamly'
    assert 'account ending 7766' in item['body']
    assert draft(client,'subscriptions').status_code==422
    client.post('/settings/demo-mailbox',json={'email':'permitted@example.edu','confirmed_control':True})
    assert draft(client,'subscriptions',recipient='permitted@example.edu').status_code==422
    assert draft(client,'subscriptions',provider_id='streamly',recipient='permitted@example.edu').status_code==200


def test_no_reference_and_invalid_legacy_fixture_value_do_not_invent_one(client):
    result=draft(client).json()
    assert result['reference_id']=='omit'
    assert result['reference'] is None
    service=client.app.state.service
    finding=service.finding('storage');finding['masked_identifier']='account ending 9999'
    service.repo.put('findings','storage',finding)
    result=draft(client).json()
    assert '9999' not in result['body']


def test_spaced_numeric_reference_retains_correct_final_digits(client):
    ingest(client,'spaced','Valley Storage\nAccount number: 1234 5678 9012')
    result=draft(client).json()
    assert result['reference']['masked_identifier']=='account ending 9012'
    assert '1234 5678 9012' not in result['body']


@pytest.mark.parametrize('identifier',[
 'ABCD1234/5678',
 '1234.5678',
 'ABCD1234\\5678',
 'ABCD1234:5678',
 'ABCD1234-',
 'A'*39+'1234',
 'ABCD1234 12345678901234567890',
 'ABCD1234 EFGH5678'
])
def test_unsupported_or_oversized_reference_is_not_prefix_matched(client,identifier):
    ingest(client,'unsupported','Valley Storage\nAccount number: '+identifier)
    assert resolve(client)['references']==[]
    result=draft(client).json()
    assert result['reference_id']=='omit'
    assert 'account ending' not in result['body']


def test_mask_preserves_source_identifier_case(client):
    ingest(client,'case-sensitive','Valley Storage\nAccount number: AA8877bC')
    result=draft(client).json()
    assert result['reference']['masked_identifier']=='account ending 77bC'
    assert 'account ending 77bC' in result['body']

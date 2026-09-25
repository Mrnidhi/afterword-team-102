"""Exercise the actual offline application boundary without a GPU or cloud account."""
from concurrent.futures import ThreadPoolExecutor
from threading import Event

from fastapi.testclient import TestClient
import pytest

from backend.main import create_app
from backend import app as translation


def extracted(text, source, doc_id, reference_date=None):
    return {'contract':'afterword.finding/v1','id':doc_id,'source':source,
            'status':'accepted','route':'memory','finding':{'cat':'personal','triage':'memory','money_at_stake':0},
            'evidence':[],'checks':{'schema_errors':[],'grounded':{}},
            'meta':{'engine':'test','model':'injected-test','tier':'L1','latency_ms':1,'output_tokens':3,'raw':None}}


@pytest.fixture
def client(tmp_path,monkeypatch):
    monkeypatch.setattr(translation,'health',lambda:{'status':'ok','llm':False,'embeddings':False})
    monkeypatch.setenv('AFTERWORD_GMAIL_CLIENT_ID','configured-test-client')
    monkeypatch.setenv('AFTERWORD_LOOKUP_ENDPOINT','https://search.example/api')
    app=create_app(db_path=tmp_path/'outreach.sqlite3',findings_db=tmp_path/'findings.sqlite3',
                   translations_db=tmp_path/'translations.sqlite3',offline=True,
                   extractor=extracted,allowed_hosts={'testserver'})
    with TestClient(app) as client:
        yield client


HEADERS={'X-Afterword-Client':'web'}


def test_live_contract_routes_and_offline_health_share_one_origin(client):
    response=client.post('/extract',json={'id':'family-1','source':'letter','text':'Keep the blue notebook.\n'},headers=HEADERS)
    assert response.status_code==200
    assert response.json()['route']=='memory'
    stored=client.get('/findings/family-1').json()
    assert stored['text']=='Keep the blue notebook.\n'
    assert client.get('/findings').json()['total']==1
    health=client.get('/health').json()
    assert health['contract']=='afterword.finding/v1'
    assert health['offline'] and health['capabilities']['extract']
    assert health['capabilities']['gmail_compose'] is False
    assert health['telemetry']['entities_sent_to_cloud'] == 0
    assert health['telemetry']['scope'] == 'current_offline_application'
    assert health['capabilities']['translation'] is False
    assert health['model'] is None


def test_offline_app_has_no_cloud_routes_even_with_configured_environment(client):
    routes=set(client.app.openapi()['paths'])
    for path in ['/providers/lookup','/integrations/gmail/authorize','/integrations/gmail/callback','/outreach/{outreach_id}/gmail-draft']:
        assert path not in routes
    assert client.post('/providers/lookup',json={},headers=HEADERS).status_code in {404,405}
    assert client.post('/integrations/gmail/authorize',json={},headers=HEADERS).status_code in {404,405}


def test_runtime_bootstrap_prevents_fixture_boot_and_limits_network(client):
    response=client.get('/runtime-config.js')
    assert response.status_code==200 and '"extraction": true' in response.text
    assert '"offline": true' in response.text and '"preview": false' in response.text
    assert "connect-src 'self'" in response.headers['content-security-policy']
    assert "font-src 'self'" in response.headers['content-security-policy']


def test_extraction_rejects_cross_origin_requests(client):
    response=client.post('/extract',json={'id':'x','source':'letter','text':'Hello'},
                         headers={'Origin':'https://unrelated.example'})
    assert response.status_code==403
    assert client.get('/findings').json()['total']==0


def test_translation_endpoints_require_loopback_ports():
    for endpoint,port in [('https://example.com/v1',8000),('http://127.0.0.1:8090/v1',8000),
                          ('http://user:password@127.0.0.1:8000/v1',8000),('http://127.0.0.1:8003/v1?redirect=1',8003)]:
        with pytest.raises(translation.HTTPException):
            translation.local_endpoint(endpoint,port)


def test_translation_model_identity_refreshes_without_backend_restart(monkeypatch):
    class Response:
        def __init__(self,identity):self.identity=identity
        def raise_for_status(self):pass
        def json(self):return {'data':[{'id':self.identity}]}
    class Client:
        identity='base-weights'
        def get(self,url):return Response(self.identity)
    transport=Client()
    monkeypatch.setattr(translation,'_client',transport)
    monkeypatch.setattr(translation,'LLM_URL','http://127.0.0.1:8000/v1')
    assert translation.llm_model_id()=='base-weights'
    transport.identity='fine-tuned-weights'
    assert translation.llm_model_id()=='fine-tuned-weights'


def outreach_request():
    return {'finding_id':'storage','provider_id':'valley-storage',
            'template_id':'request_records','reference_id':'omit',
            'fields':{'writer_name':'Priya Rao','writer_phone':'+1 408 555 0100',
                      'relationship':'daughter','date_of_death':'2026-09-01'}}


def offline_app_for_selector(tmp_path):
    return create_app(db_path=tmp_path/'outreach.sqlite3',findings_db=tmp_path/'findings.sqlite3',
                      translations_db=tmp_path/'translations.sqlite3',offline=True,
                      extractor=extracted,allowed_hosts={'testserver'})


def test_offline_outreach_tone_selector_holds_the_shared_inference_lock(tmp_path,monkeypatch):
    from backend import drafting
    from backend.extraction_service import MODEL_LOCK

    entered=Event()
    release=Event()

    def select(choices,context):
        entered.set()
        if not release.wait(3):
            raise RuntimeError('Test did not release the simulated tone selection.')
        return {'tone':'plain','slots':context['slots']}

    # Replace only HTTP/model work. Exercise the real offline factory, route,
    # draft service and wrapper which must serialize with document extraction.
    monkeypatch.setattr(drafting,'local_tone_selector',select)
    monkeypatch.setenv('AFTERWORD_LLM_URL','http://127.0.0.1:8000/v1')
    app=offline_app_for_selector(tmp_path)
    with TestClient(app) as client, ThreadPoolExecutor(max_workers=1) as pool:
        pending=pool.submit(client.post,'/outreach/draft',json=outreach_request(),headers=HEADERS)
        try:
            assert entered.wait(3), 'The request never reached the local tone selector.'
            # A second thread cannot acquire the very lock used by extraction.
            # This avoids proving serialization using a sleep or a separate lock.
            acquired=MODEL_LOCK.acquire(blocking=False)
            if acquired:
                MODEL_LOCK.release()
            assert acquired is False, 'Outreach model work bypassed the shared inference lock.'
        finally:
            release.set()
        response=pending.result(timeout=3)
    assert response.status_code==200
    assert response.json()['generation']['mode']=='local_model_guarded'
    assert response.json()['status']=='draft'


@pytest.mark.parametrize('endpoint',[
    'http://127.0.0.1:8090/v1',
    'http://127.0.0.1:8003/v1',
    'https://external.example/v1',
    'http://127.0.0.1:8000/v1?forward=external',
])
def test_offline_outreach_rejects_wrong_model_destination_before_selection(tmp_path,monkeypatch,endpoint):
    from backend import drafting

    calls=[]

    def select(choices,context):
        calls.append(context)
        return {'tone':'plain','slots':context['slots']}

    monkeypatch.setattr(drafting,'local_tone_selector',select)
    monkeypatch.setenv('AFTERWORD_LLM_URL',endpoint)
    with TestClient(offline_app_for_selector(tmp_path)) as client:
        response=client.post('/outreach/draft',json=outreach_request(),headers=HEADERS)
    assert response.status_code==200
    assert calls==[], 'A forbidden destination reached the model selector.'
    assert response.json()['generation']['mode']=='local_template'
    assert response.json()['generation']['warning']
    assert 'Priya Rao' in response.json()['body']

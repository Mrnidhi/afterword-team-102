import hashlib
import json
import sqlite3
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from backend.extraction_contract import CONTRACT, BatchInput, ExtractInput
from backend.extraction_engine import LocalEngine, LocalTransport, ModelResponse, NoRedirect, local_model_url
from backend.extraction_repository import FindingRepository, SourceConflict
from backend.extraction_routes import mount_extraction
from backend.extraction_service import ExtractionService

ROOT = Path(__file__).resolve().parents[1]


def item(identifier='letter-1', text='Monthly charge: $12.99\nReference AB1234', **fields):
    return {'id': identifier, 'source': 'letter', 'text': text, **fields}


class Transport:
    def __init__(self, prediction=None):
        self.prediction = prediction or {'cat': 'subscription', 'amt': 12.99, 'kind': 'charge', 'rec': 'monthly', 'act': 'cancel', 'ev': [1]}
        self.calls = []
        self.model = 'base-model'

    def post(self, url, timeout, json):
        self.calls.append((url, json))
        if isinstance(self.prediction, Exception):
            raise self.prediction
        return ModelResponse({'choices': [{'message': {'content': globals()['json'].dumps(self.prediction)}}],
                              'model': self.model, 'usage': {'completion_tokens': 37}})

    def get(self, url, timeout):
        self.calls.append((url, None))
        return ModelResponse({'data': [{'id': self.model}]})


def engine(transport=None):
    return LocalEngine(ROOT / 'model', 'http://127.0.0.1:8000/v1', transport or Transport())


def service(tmp_path, transport=None):
    return ExtractionService(tmp_path / 'findings.sqlite3', engine(transport))


def client_for(service):
    app = FastAPI()
    mount_extraction(app, service=service)
    return TestClient(app)


def test_authoritative_files_are_unchanged():
    hashes = {'engine.py': '4c367313536c3141a6884a8693ed9401b1705a0a0f70a60d318d81621e70995c',
              'schema.py': '208f56672424addc2e88ec39b037e39cca03996b56161011b69337f198d18b4e',
              'metrics.py': '7f2aef153abc7dc5f49579f475472d8409ddfb24b089c8281f2d1a6f5e6d6cab',
              'prep_public.py': '954583453393583a4d966dbd14b9dbcc3037f6aea9ca9602c10507603179835f'}
    for filename, expected in hashes.items():
        assert hashlib.sha256((ROOT / 'model' / filename).read_bytes()).hexdigest() == expected


def test_authoritative_engine_enriches_and_preserves_exact_lines(tmp_path):
    transport = Transport()
    target = service(tmp_path, transport)
    source = item(text='Monthly charge: $12.99\r\n\r\n  Reference AB1234  \n')
    result = target.extract(source)
    assert result['contract'] == CONTRACT
    assert result['finding']['money_at_stake'] == 155.88
    assert result['status'] == 'accepted'
    assert result['meta']['model'] == 'base-model'
    assert result['meta']['output_tokens'] == 37
    assert result['evidence'] == [{'line': 1, 'text': 'Monthly charge: $12.99'}]
    assert transport.calls[0][1]['messages'][1]['content'] == '1| Monthly charge: $12.99\n2| \n3|   Reference AB1234  '
    assert target.get(source['id'])['text'] == source['text']


def test_reference_date_is_passed_as_date_to_real_enrichment(tmp_path):
    transport = Transport({'cat': 'retirement', 'amt': 100, 'kind': 'benefit', 'rec': 'monthly', 'act': 'stop_payment', 'due': 30, 'ev': [1]})
    target = service(tmp_path, transport)
    source = item(text='Benefit 100; respond in 30 days.', reference_date='2026-09-01')
    result = target.extract(source)
    assert result['finding']['deadline_date'] == '2026-10-01'
    assert result['finding']['money_at_stake'] == 600
    assert target.get(source['id'])['reference_date'] == '2026-09-01'
    assert target.collection()['findings'][0]['reference_date'] == '2026-09-01'
    assert 'reference_date' not in result
    assert 'reference_date' not in target.extract(source)


def test_oversized_inference_input_is_stored_whole_without_model_call(tmp_path):
    transport = Transport()
    target = ExtractionService(tmp_path / 'bounded.sqlite3', engine(transport), max_input_chars=32)
    source = item(text='  ' + 'long document\r\n' * 8)
    result = target.extract(source)
    assert result['status'] == 'failed'
    assert 'No model request was made' in result['checks']['error']
    assert transport.calls == []
    assert target.get(source['id'])['text'] == source['text']
    assert target.health()['max_input_chars'] == 32
    target.max_input_chars = 1000
    target.extract(source, retry=True)
    assert sum(body is not None for url, body in transport.calls) == 1


def test_inference_limit_is_configurable_and_default_is_conservative(tmp_path, monkeypatch):
    monkeypatch.delenv('AFTERWORD_EXTRACT_MAX_CHARS', raising=False)
    assert service(tmp_path).max_input_chars == 32000
    monkeypatch.setenv('AFTERWORD_EXTRACT_MAX_CHARS', '64000')
    assert service(tmp_path).max_input_chars == 64000
    monkeypatch.setenv('AFTERWORD_EXTRACT_MAX_CHARS', '0')
    with pytest.raises(ValueError):
        service(tmp_path)


def test_model_failure_envelope_is_persisted_and_batch_continues(tmp_path):
    transport = Transport(RuntimeError('service stopped'))
    target = service(tmp_path, transport)
    results = target.extract_batch([item('a'), item('b')])
    assert [row['status'] for row in results] == ['failed', 'failed']
    assert all(row['route'] is None and row['finding'] is None for row in results)
    assert target.collection()['counts']['failed'] == 2
    assert len(transport.calls) == 2


def test_engine_postprocessing_error_is_a_failure_not_an_http_crash(tmp_path):
    transport = Transport({'cat': 'bank', 'amt': 'not a number', 'ev': [1]})
    response = client_for(service(tmp_path, transport)).post('/extract', json=item())
    assert response.status_code == 200
    assert response.json()['status'] == 'failed'
    assert response.json()['finding'] is None


def test_grounding_failure_keeps_engine_judgement_and_reason(tmp_path):
    result = service(tmp_path, Transport({'cat': 'bank', 'amt': 9876, 'ev': [1]})).extract(item())
    assert result['status'] == 'needs_review'
    assert result['checks']['grounded']['amt'] is False
    assert result['meta']['raw'] is not None


@pytest.mark.parametrize('category,route', [('personal', 'memory'), ('irrelevant', 'drop')])
def test_memory_and_drop_routes_are_stored(tmp_path, category, route):
    target = service(tmp_path, Transport({'cat': category}))
    result = target.extract(item())
    assert result['route'] == route
    assert target.collection()['counts'][route] == 1


def test_reopen_preserves_exact_contract_and_source(tmp_path):
    target = service(tmp_path)
    target.extract(item())
    expected = target.get('letter-1')
    target.repo.close()
    reopened = FindingRepository(tmp_path / 'findings.sqlite3')
    assert reopened.get('letter-1') == expected
    columns = [row['name'] for row in reopened.connection.execute('PRAGMA table_info(findings)')]
    assert columns == ['id', 'source', 'status', 'route', 'finding_json', 'evidence_json', 'checks_json', 'meta_json', 'text', 'created_at']


def test_identical_reimport_is_idempotent_and_retry_is_explicit(tmp_path):
    transport = Transport()
    target = service(tmp_path, transport)
    first = target.extract(item())
    created = target.get('letter-1')['created_at']
    assert target.extract(item()) == first
    assert len(transport.calls) == 1
    transport.model = 'fine-tuned-model'
    second = target.extract(item(), retry=True)
    assert second['meta']['model'] == 'fine-tuned-model'
    assert len(transport.calls) == 2
    assert target.get('letter-1')['created_at'] == created


@pytest.mark.parametrize('change', [{'text': 'Changed content'}, {'source': 'sms'}, {'reference_date': '2026-09-01'}])
def test_changed_source_context_conflicts_even_on_retry(tmp_path, change):
    target = service(tmp_path)
    target.extract(item())
    with pytest.raises(SourceConflict):
        target.extract({**item(), **change}, retry=True)
    assert target.get('letter-1')['text'] == item()['text']


def test_batch_conflict_checked_before_any_model_call(tmp_path):
    transport = Transport()
    target = service(tmp_path, transport)
    target.extract(item('existing'))
    with pytest.raises(SourceConflict):
        target.extract_batch([item('new'), item('existing', text='new text')])
    assert len(transport.calls) == 1
    assert target.get('new') is None


def test_single_and_batch_share_one_serialization_boundary(tmp_path):
    transport = Transport()
    core = engine(transport)
    lock = threading.Lock()
    active = 0
    high_water = 0
    order = []

    def extract(text, **kwargs):
        nonlocal active, high_water
        with lock:
            active += 1
            high_water = max(high_water, active)
            order.append(kwargs['doc_id'])
        time.sleep(0.01)
        try:
            return core.extract(text, **kwargs)
        finally:
            with lock:
                active -= 1

    target = ExtractionService(tmp_path / 'serial.sqlite3', extract)
    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = [pool.submit(target.extract_batch, [item('b1'), item('b2')]),
                   pool.submit(target.extract, item('s1')), pool.submit(target.extract, item('s2'))]
        for future in futures:
            future.result()
    assert high_water == 1
    assert order.index('b2') == order.index('b1') + 1


def test_http_contract_collection_and_retrieval(tmp_path):
    target = service(tmp_path)
    client = client_for(target)
    response = client.post('/extract/batch', json={'items': [item('first'), item('second')]})
    assert response.status_code == 200
    assert isinstance(response.json(), list)
    collection = client.get('/findings').json()
    assert collection['contract'] == CONTRACT
    assert collection['total'] == 2
    assert collection['counts']['extract'] == 2
    assert client.get('/findings/first').json()['text'] == item()['text']
    assert client.get('/findings/absent').status_code == 404
    assert client.post('/extract', json=item('first', 'different')).status_code == 409
    assert client.post('/extract?retry=true', json=item('first')).status_code == 200


@pytest.mark.parametrize('bad', [item(source='voice'), item(id='../outside'), item(text=' \r\n'), item(reference_date='not a date')])
def test_invalid_input_is_rejected_without_model_call(tmp_path, bad):
    transport = Transport()
    response = client_for(service(tmp_path, transport)).post('/extract', json=bad)
    assert response.status_code == 422
    assert transport.calls == []


def test_batch_limits_and_duplicate_ids():
    for items in ([], [item()] * 2, [item(str(n)) for n in range(101)]):
        with pytest.raises(ValidationError):
            BatchInput(items=items)
    with pytest.raises(ValidationError):
        BatchInput(items=[item(str(n), 'a' * 2_000_000) for n in range(11)])


def test_live_model_identity_refresh_does_not_generate_tokens():
    transport = Transport()
    target = engine(transport)
    assert target.health()['model'] == 'base-model'
    transport.model = 'fine-tuned-model'
    assert target.health()['model'] == 'fine-tuned-model'
    assert all(url.endswith('/models') and body is None for url, body in transport.calls)


@pytest.mark.parametrize('url', ['https://api.example.com/v1', 'http://127.0.0.1:8090/v1',
                               'http://user:secret@127.0.0.1:8000/v1', 'http://localhost:8000/v1?token=a',
                               'http://localhost:8000/v1#fragment', 'http://127.0.0.1:8000/other'])
def test_external_or_wrong_model_endpoint_is_rejected(url):
    with pytest.raises(ValueError):
        local_model_url(url)


def test_transport_ignores_proxy_environment_and_denies_redirects(monkeypatch):
    monkeypatch.setenv('HTTP_PROXY', 'http://external.invalid:9000')
    transport = LocalTransport('http://localhost:8000/v1')
    assert transport.base_url == 'http://127.0.0.1:8000/v1'
    assert not any(getattr(handler, 'proxies', None) for handler in transport.opener.handlers)
    with pytest.raises(ValueError):
        NoRedirect().redirect_request(None, None, 302, '', {}, 'https://external.invalid')
    with pytest.raises(ValueError):
        transport.post('https://external.invalid/chat/completions', json={})


def test_missing_engine_fails_visibly_without_fixtures(tmp_path):
    target = ExtractionService(':memory:', LocalEngine(tmp_path / 'missing'))
    assert target.health()['available'] is False
    result = target.extract(item())
    assert result['status'] == 'failed'
    assert result['finding'] is None


def test_corrupted_adapter_evidence_is_not_published_as_accepted(tmp_path):
    real = engine()

    def corrupt(text, **kwargs):
        result = real.extract(text, **kwargs)
        result['evidence'][0]['text'] = 'fabricated evidence'
        return result

    target = ExtractionService(':memory:', corrupt)
    assert target.extract(item())['status'] == 'failed'


def test_legacy_database_is_rejected_without_altering_data(tmp_path):
    path = tmp_path / 'legacy.sqlite3'
    connection = sqlite3.connect(path)
    connection.execute('CREATE TABLE findings(id TEXT PRIMARY KEY,payload TEXT NOT NULL)')
    connection.execute('INSERT INTO findings VALUES (?,?)', ('original', '{}'))
    connection.commit()
    connection.close()
    with pytest.raises(ValueError, match='separate findings database'):
        FindingRepository(path)
    connection = sqlite3.connect(path)
    assert connection.execute('SELECT * FROM findings').fetchall() == [('original', '{}')]

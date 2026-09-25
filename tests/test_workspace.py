"""Local access control and profile persistence; no models or external services."""
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from backend.main import create_app
from backend.workspace import COOKIE, SESSION_SECONDS, Workspace, password_hash

HEADERS = {'X-Afterword-Client': 'web'}
PROFILE = {'display_name': 'Test family member', 'estate_name': 'Test family workspace',
           'password': 'fictional-password-for-tests'}


def application(tmp_path, **kwargs):
    return create_app(db_path=tmp_path/'outreach.sqlite3', workspace_db=tmp_path/'workspace.sqlite3',
                      allowed_hosts={'testserver'}, require_login=True, **kwargs)


@pytest.fixture
def client(tmp_path):
    with TestClient(application(tmp_path), headers=HEADERS) as client:
        yield client


def setup(client, **values):
    response = client.post('/workspace/setup', json={**PROFILE, **values})
    assert response.status_code == 200, response.text
    return response


def test_setup_cookie_profile_and_hashed_credentials(client, tmp_path):
    assert client.get('/workspace/session').json() == {
        'enabled': True, 'require_login': True, 'setup_required': True,
        'authenticated': False, 'profile': None}
    response = setup(client)
    value = response.json()
    assert value['authenticated'] and not value['setup_required']
    assert value['profile']['writer_name'] == ''
    assert value['profile']['demo_mailbox_confirmed'] is False
    assert 'HttpOnly' in response.headers['set-cookie']
    assert 'SameSite=strict' in response.headers['set-cookie']
    assert f'Max-Age={SESSION_SECONDS}' in response.headers['set-cookie']
    assert 'password' not in json.dumps(value)
    db = client.app.state.workspace.connection
    row = db.execute('SELECT password_hash,password_salt FROM workspace').fetchone()
    assert row['password_hash'] != PROFILE['password'] and len(row['password_salt']) == 64
    assert db.execute('SELECT token_hash FROM workspace_sessions').fetchone()[0] != client.cookies.get(COOKIE)
    assert (tmp_path/'workspace.sqlite3').stat().st_mode & 0o777 == 0o600
    assert client.get('/providers').status_code == 200


def test_portable_scrypt_matches_native_openssl_vector(monkeypatch):
    import hashlib
    # Recorded from native OpenSSL scrypt with these exact parameters; protects
    # login compatibility between Apple Python and the Linux HP deployment.
    expected = ('87e8f2a41979f1876d4cd17231e43ce75010b1851524a65302cf61dfdf0c6dea'
                '626a2f84ab41f09d083b2ce6e539dd869be7623810686e9bd7c2aa758bce6805')
    monkeypatch.delattr(hashlib, 'scrypt', raising=False)
    assert password_hash(PROFILE['password'], bytes(range(32))) == expected


def test_https_session_cookie_is_secure(tmp_path):
    with TestClient(application(tmp_path), base_url='https://testserver', headers=HEADERS) as client:
        response = setup(client)
        assert 'Secure' in response.headers['set-cookie']
        assert client.get('/providers').status_code == 200


def test_auth_gate_covers_data_and_settings_but_keeps_shell_public(client):
    for path in ('/', '/index.html', '/runtime-config.js', '/health', '/workspace/session'):
        assert client.get(path).status_code == 200, path
    runtime = client.get('/runtime-config.js').text
    assert '"workspace": true' in runtime and '"requireLogin": true' in runtime
    for path in ('/providers', '/documents', '/outreach', '/privacy/outreach', '/metrics/outreach',
                 '/openapi.json', '/api-docs', '/findings', '/findings/pretend.js'):
        response = client.get(path)
        assert response.status_code == 401, path
        assert isinstance(response.json()['detail'], str)
    for path in ('/extract', '/extract/batch', '/ingest/extract', '/outreach/draft',
                 '/settings/demo-mailbox', '/translate'):
        assert client.post(path, json={}).status_code == 401, path
    assert client.patch('/workspace/profile', json={'display_name': 'Other'}).status_code == 401


def test_offline_gate_wraps_newly_mounted_extraction_routes(tmp_path):
    def do_not_extract(*args, **kwargs):
        raise AssertionError('Unauthenticated requests must never reach the model.')
    app = application(tmp_path, offline=True, findings_db=tmp_path/'findings.sqlite3',
                      translations_db=tmp_path/'translations.sqlite3', extractor=do_not_extract)
    with TestClient(app, headers=HEADERS) as client:
        assert client.get('/findings').status_code == 401
        assert client.post('/extract', json={'id': 'a', 'source': 'file', 'text': 'private'}).status_code == 401
        setup(client)
        assert client.get('/findings').json()['total'] == 0


def test_existing_workspace_cannot_be_reset_and_profile_survives_restart(client, tmp_path):
    setup(client, writer_name='Fictional writer', reading_language='es')
    assert client.post('/workspace/setup', json={**PROFILE, 'display_name': 'Replacement'}).status_code == 409
    client.post('/workspace/logout', json={})
    with TestClient(application(tmp_path), headers=HEADERS) as restarted:
        status = restarted.get('/workspace/session').json()
        assert not status['setup_required'] and status['profile'] is None
        assert restarted.post('/workspace/login', json={'password': PROFILE['password']}).status_code == 200
        assert restarted.get('/workspace/session').json()['profile']['writer_name'] == 'Fictional writer'
        assert restarted.get('/workspace/session').json()['profile']['reading_language'] == 'es'


def test_logout_revokes_copied_cookie_and_login_rotates_session(client):
    setup(client)
    original = client.cookies.get(COOKIE)
    assert client.post('/workspace/login', json={'password': PROFILE['password']}).status_code == 200
    replacement = client.cookies.get(COOKIE)
    assert original != replacement
    store = client.app.state.workspace
    assert not store.authenticated(original) and store.authenticated(replacement)
    response = client.post('/workspace/logout', json={})
    assert response.status_code == 200 and response.json()['profile'] is None
    assert not store.authenticated(replacement)
    assert client.get('/providers', headers={'Cookie': f'{COOKIE}={replacement}'}).status_code == 401


def test_expired_session_rejected_server_side(client):
    setup(client)
    store = client.app.state.workspace
    now = store.clock()
    store.clock = lambda: now + SESSION_SECONDS + 1
    assert client.get('/workspace/session').json()['authenticated'] is False
    assert client.get('/documents').status_code == 401
    assert client.patch('/workspace/profile', json={'display_name': 'Changed'}).status_code == 401


def test_wrong_password_has_bounded_retry_and_never_issues_cookie(client):
    setup(client)
    client.post('/workspace/logout', json={})
    for _ in range(5):
        response = client.post('/workspace/login', json={'password': 'incorrect-test-password'})
        assert response.status_code == 401
        assert 'set-cookie' not in response.headers
    assert client.post('/workspace/login', json={'password': PROFILE['password']}).status_code == 429
    store = client.app.state.workspace
    now = store.clock()
    store.clock = lambda: now + 61
    assert client.post('/workspace/login', json={'password': PROFILE['password']}).status_code == 200


@pytest.mark.parametrize('changes', [
    {'password': 'short'}, {'display_name': ''}, {'estate_name': ''},
    {'writer_name': 'Name\nInjected'}, {'writer_phone': 'not a phone'},
    {'reading_language': 'unavailable'}, {'demo_mailbox': 'person@provider.example'},
    {'demo_mailbox_confirmed': True}, {'demo_mailbox_confirmed': 'true'},
    {'date_of_death': '2026-02-30'}, {'date_of_death': (date.today()+timedelta(days=1)).isoformat()},
    {'unexpected': 'field'}, {'writer_name': None},
])
def test_invalid_setup_has_clear_error_without_bootstrap_side_effects(client, changes):
    response = client.post('/workspace/setup', json={**PROFILE, **changes})
    assert response.status_code == 422, response.text
    assert isinstance(response.json()['detail'], str)
    assert client.get('/workspace/session').json()['setup_required']


def test_profile_update_preserves_other_fields_and_needs_new_mailbox_attestation(client):
    setup(client, writer_name='Fictional writer', demo_mailbox='test-family@university.edu',
          demo_mailbox_confirmed=True)
    response = client.patch('/workspace/profile', json={'reading_language': 'hi'})
    assert response.status_code == 200
    assert response.json()['profile']['writer_name'] == 'Fictional writer'
    assert response.json()['profile']['demo_mailbox_confirmed']
    response = client.patch('/workspace/profile', json={'demo_mailbox': 'different-family@university.edu'})
    assert response.json()['profile']['demo_mailbox_confirmed'] is False
    # Saving a profile is not recipient consent or an implicit email action.
    assert client.app.state.service.repo.list('consents') == []
    assert client.app.state.service.repo.get('settings', 'demo_mailbox') is None
    response = client.patch('/workspace/profile', json={'password': 'new-test-password'})
    assert response.status_code == 422
    assert client.patch('/workspace/profile', json={'date_of_death': ''}).status_code == 200


def test_bootstrap_race_allows_exactly_one_owner(tmp_path):
    stores = [Workspace(tmp_path/'race.sqlite3') for _ in range(2)]
    def initialize(index):
        try:
            stores[index].setup({**PROFILE, 'display_name': f'Family {index}'})
            return 200
        except HTTPException as exc:
            return exc.status_code
    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(initialize, (0, 1)))
    assert sorted(outcomes) == [200, 409]
    assert stores[0].connection.execute('SELECT count(*) FROM workspace').fetchone()[0] == 1
    assert stores[0].connection.execute('SELECT count(*) FROM workspace_sessions').fetchone()[0] == 1


def test_same_origin_protection_still_applies_to_setup(client):
    assert client.post('/workspace/setup', json=PROFILE, headers={'Origin': 'https://untrusted.example'}).status_code == 403
    assert client.post('/workspace/setup', content=json.dumps(PROFILE), headers={'Content-Type': 'text/plain'}).status_code == 415
    assert client.get('/workspace/session').json()['setup_required']


def test_no_personal_mailbox_exposed_by_public_health(client):
    client.app.state.service.repo.put('settings', 'demo_mailbox', {'email': 'private-test@university.edu'})
    assert client.get('/health').json()['demo_mailbox'] is None


def test_auth_flag_default_preserves_existing_api_and_env_paths(tmp_path, monkeypatch):
    monkeypatch.delenv('AFTERWORD_REQUIRE_LOGIN', raising=False)
    monkeypatch.setenv('AFTERWORD_DATA_DIR', str(tmp_path/'private-runtime'))
    app = create_app(db_path=tmp_path/'outreach.sqlite3', allowed_hosts={'testserver'})
    with TestClient(app, headers=HEADERS) as client:
        assert client.get('/providers').status_code == 200
        assert client.get('/workspace/session').json()['require_login'] is False
        assert client.patch('/workspace/profile', json={'display_name': 'Denied'}).status_code == 401
    assert (tmp_path/'private-runtime/workspace.sqlite3').is_file()
    monkeypatch.setenv('AFTERWORD_REQUIRE_LOGIN', '1')
    second = create_app(db_path=tmp_path/'second.sqlite3', allowed_hosts={'testserver'})
    with TestClient(second, headers=HEADERS) as client:
        assert client.get('/providers').status_code == 401

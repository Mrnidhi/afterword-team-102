"""Configuration-only readiness: never read token contents or contact providers."""
from datetime import datetime, timezone
import importlib.util
import json
import os
from pathlib import Path
import platform
import shutil
import time
import urllib.parse
import urllib.request

from .router import NoRedirect


def loopback_url(value):
    try:
        parsed = urllib.parse.urlsplit(value)
        return parsed.scheme == 'http' and parsed.hostname in {'127.0.0.1', 'localhost', '::1'} and not any((parsed.username, parsed.password, parsed.query, parsed.fragment)) and bool(parsed.port is None or 0 < parsed.port < 65536)
    except (TypeError, ValueError):
        return False


def token_metadata(path, repo_root):
    """File presence/permissions only. Deliberately never opens the token file."""
    try:
        target = Path(path).expanduser().absolute()
        resolved = target.resolve()
        external = resolved != repo_root and repo_root not in resolved.parents
        exists = target.is_file() and not target.is_symlink()
        return {'file_present': exists, 'outside_repository': external, 'owner_only': bool(exists and not target.stat().st_mode & 0o077), 'symlink': target.is_symlink(), 'contents_read': False}
    except (OSError, ValueError):
        return {'file_present': False, 'outside_repository': False, 'owner_only': False, 'symlink': False, 'contents_read': False, 'metadata_error': True}


def readiness(environ=None, repo_root=None):
    env = os.environ if environ is None else environ
    root = Path(repo_root or Path(__file__).resolve().parents[1]).resolve()
    llm = env.get('AFTERWORD_LLM_URL', 'http://127.0.0.1:8000/v1')
    vision = env.get('AFTERWORD_VISION_ENDPOINT', '')
    lookup = env.get('AFTERWORD_LOOKUP_ENDPOINT', '')
    redirect = env.get('AFTERWORD_GMAIL_REDIRECT_URI', '')
    try:
        callback = urllib.parse.urlsplit(redirect)
        callback_valid = bool(redirect) and (loopback_url(redirect) or (callback.scheme == 'https' and bool(callback.hostname) and not any((callback.username, callback.password, callback.query, callback.fragment)))) and callback.path == '/integrations/gmail/callback'
        lookup_parsed = urllib.parse.urlsplit(lookup)
        lookup_valid = bool(lookup) and lookup_parsed.scheme == 'https' and bool(lookup_parsed.hostname) and not any((lookup_parsed.username, lookup_parsed.password))
    except (ValueError, TypeError):
        callback_valid = lookup_valid = False
    token = token_metadata(env.get('AFTERWORD_GMAIL_TOKEN_FILE', '~/.local/share/afterword/gmail-tokens.json'), root)
    binary = env.get('AFTERWORD_TESSERACT_BIN') or shutil.which('tesseract')
    ocr_available = bool(binary and Path(binary).is_file() and os.access(binary, os.X_OK))
    google_config = {key: bool(env.get(variable)) for key, variable in [('client_id_present', 'AFTERWORD_GMAIL_CLIENT_ID'), ('client_secret_present', 'AFTERWORD_GMAIL_CLIENT_SECRET'), ('callback_present', 'AFTERWORD_GMAIL_REDIRECT_URI')]}
    google_config.update(callback_valid=callback_valid, token_metadata=token, permissions_verified=False, live_draft_verified=False)
    configured = all(google_config[key] for key in ('client_id_present', 'client_secret_present', 'callback_present', 'callback_valid'))
    google_config['configured'] = configured
    actions = []
    if not env.get('AFTERWORD_LLM_MODEL') or not loopback_url(llm):
        actions.append({'id': 'local_model', 'action': 'Install and serve the selected local model, set AFTERWORD_LLM_MODEL and the loopback base URL, then explicitly run the models probe.'})
    if not loopback_url(vision) or not env.get('AFTERWORD_VISION_MODEL'):
        actions.append({'id': 'vision_model', 'action': 'Configure the loopback vision endpoint and model on the HP. Confirm a scanned source with matching OCR before contact extraction.'})
    if not ocr_available:
        actions.append({'id': 'ocr', 'action': 'Install Tesseract locally or set AFTERWORD_TESSERACT_BIN to its executable; no cloud OCR is used.'})
    if not lookup_valid:
        actions.append({'id': 'public_lookup', 'action': 'Configure an approved public HTTPS search adapter. Each actual company/country query still requires family approval.'})
    if not configured:
        actions.append({'id': 'google_oauth', 'action': 'Configure a Google OAuth test client outside the repository, enable Gmail API and register the exact local callback.'})
    if not token['file_present']:
        actions.append({'id': 'gmail_connection', 'action': 'Use the Gmail connection screen to approve draft access. Add read-only access separately only if reply tracking is wanted.'})
    if token['file_present'] and (not token['outside_repository'] or not token['owner_only'] or token['symlink']):
        actions.append({'id': 'credential_storage', 'action': 'Move the token file outside the repository with owner-only permissions; reconnect if the file is not trustworthy.'})
    return {'schema_version': 1, 'checked_at': datetime.now(timezone.utc).isoformat(), 'inspection': 'configuration_and_file_metadata_only', 'network_requests': 0, 'token_contents_read': False, 'machine_architecture': platform.machine(), 'hardware_identity_verified': False, 'local_model': {'endpoint_explicitly_configured': bool(env.get('AFTERWORD_LLM_URL')), 'loopback_endpoint_valid': loopback_url(llm), 'model_name_present': bool(env.get('AFTERWORD_LLM_MODEL')), 'inference_verified': False}, 'vision': {'endpoint_present': bool(vision), 'loopback_endpoint_valid': bool(vision) and loopback_url(vision), 'model_name_present': bool(env.get('AFTERWORD_VISION_MODEL')), 'inference_verified': False}, 'ocr': {'executable_available': ocr_available, 'image_validation_available': importlib.util.find_spec('PIL') is not None, 'execution_verified': False}, 'public_lookup': {'endpoint_present': bool(lookup), 'https_configuration_valid': lookup_valid, 'credential_present': bool(env.get('AFTERWORD_LOOKUP_TOKEN')), 'dns_or_network_verified': False}, 'gmail': google_config, 'next_actions': actions, 'live_acceptance_complete': False}


def probe_models(base_url, selected_model='', opener=None):
    """Explicit caller opt-in only: GET loopback /models; no inference or documents."""
    if not loopback_url(base_url):
        raise ValueError('A model probe only accepts a local loopback HTTP base URL.')
    started = time.perf_counter()
    request = urllib.request.Request(base_url.rstrip('/') + '/models', headers={'Accept': 'application/json'})
    open_request = opener or urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect()).open
    try:
        with open_request(request, timeout=3) as response:
            raw = response.read(1_000_001)
            if len(raw) > 1_000_000:
                raise ValueError('Oversized models response')
            result = json.loads(raw)
        data = result.get('data')
        if not isinstance(data, list):
            raise ValueError('Invalid models response')
        ids = [item['id'] for item in data if isinstance(item, dict) and isinstance(item.get('id'), str)]
        return {'attempted': True, 'reachable': True, 'model_count': len(ids), 'selected_model_present': selected_model in ids if selected_model else None, 'elapsed_ms': round((time.perf_counter() - started) * 1000, 2), 'measurement': 'models_list_request_only', 'inference_verified': False}
    except Exception:
        return {'attempted': True, 'reachable': False, 'elapsed_ms': round((time.perf_counter() - started) * 1000, 2), 'reason': 'The local models endpoint did not return a usable response.', 'inference_verified': False}

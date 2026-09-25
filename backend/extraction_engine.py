"""Load the team's unchanged engine with a loopback-only HTTP transport."""
import builtins
import json
import os
import types
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit

from .extraction_contract import CONTRACT

ROOT = Path(__file__).resolve().parents[1]


def local_model_url(value):
    parsed = urlsplit(value)
    if (parsed.scheme != 'http' or parsed.hostname not in {'127.0.0.1', 'localhost', '::1'}
            or parsed.port != 8000 or parsed.username or parsed.password
            or parsed.query or parsed.fragment or parsed.path.rstrip('/') != '/v1'):
        raise ValueError('The extraction model must use loopback HTTP on port 8000 at /v1.')
    # Avoid hostname resolution for localhost and keep the approved destination exact.
    host = '[::1]' if parsed.hostname == '::1' else '127.0.0.1'
    return 'http://' + host + ':8000/v1'


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError('Local model redirects are disabled.')


class ModelResponse:
    def __init__(self, value):
        self.value = value

    def raise_for_status(self):
        pass  # urllib already raises for non-success HTTP responses.

    def json(self):
        return self.value


class LocalTransport:
    """Only the two required model operations; proxy environment is ignored."""
    def __init__(self, base_url, opener=None):
        self.base_url = local_model_url(base_url)
        self.opener = opener or urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())

    def _request(self, method, url, timeout, payload=None):
        allowed = self.base_url + ('/chat/completions' if method == 'POST' else '/models')
        if url != allowed:
            raise ValueError('This operation is outside the local model boundary.')
        raw = None if payload is None else json.dumps(payload, allow_nan=False).encode('utf-8')
        request = urllib.request.Request(url, data=raw, method=method,
                                         headers={'Content-Type': 'application/json', 'Accept': 'application/json'})
        with self.opener.open(request, timeout=min(max(float(timeout), 0.1), 180)) as response:
            body = response.read(2_000_001)
        if len(body) > 2_000_000:
            raise ValueError('The local model response is too large.')
        return ModelResponse(json.loads(body))

    def post(self, url, timeout=120, json=None):
        return self._request('POST', url, timeout, json)

    def get(self, url, timeout=2):
        return self._request('GET', url, timeout)


def load_source(path, name, imports=None):
    """Isolated imports preserve authoritative source without global sys.path hacks.

    The engine expects `requests`, `schema`, and `metrics`. Its private import
    namespace supplies those dependencies; unrelated application modules are
    never monkey-patched. Only the requests transport is restricted here.
    """
    module = types.ModuleType(name)
    module.__file__ = str(path)
    standard_import = builtins.__import__
    imports = imports or {}

    def scoped_import(import_name, globals=None, locals=None, fromlist=(), level=0):
        if level == 0 and import_name in imports:
            return imports[import_name]
        return standard_import(import_name, globals, locals, fromlist, level)

    module.__dict__['__builtins__'] = {**vars(builtins), '__import__': scoped_import}
    exec(compile(path.read_bytes(), str(path), 'exec'), module.__dict__)
    return module


class LocalEngine:
    def __init__(self, model_dir=None, base_url=None, transport=None):
        self.model_dir = Path(model_dir or os.environ.get('AFTERWORD_MODEL_DIR', ROOT / 'model')).expanduser().resolve()
        self.base_url = local_model_url(base_url or os.environ.get('AFTERWORD_LLM_URL', 'http://127.0.0.1:8000/v1'))
        self.transport = transport or LocalTransport(self.base_url)
        self.module = None
        self.load_error = None
        try:
            self.schema = load_source(self.model_dir / 'schema.py', '_afterword_schema')
            metrics = load_source(self.model_dir / 'metrics.py', '_afterword_metrics', {'schema': self.schema})
            self.module = load_source(self.model_dir / 'engine.py', '_afterword_engine',
                                      {'schema': self.schema, 'metrics': metrics, 'requests': self.transport})
            if self.module.CONTRACT != CONTRACT:
                raise ValueError('Unsupported extraction engine contract.')
        except Exception as exc:
            self.module = None
            self.load_error = 'Local extraction engine could not load: ' + type(exc).__name__

    def extract(self, text, source, doc_id, reference_date=None):
        if self.module is None:
            raise RuntimeError(self.load_error)
        return self.module.extract(text, source=source, doc_id=doc_id,
                                   reference_date=reference_date, llm_url=self.base_url)

    def health(self):
        result = {'contract': CONTRACT, 'engine': getattr(self.module, 'ENGINE_VERSION', None),
                  'model': None, 'models': [], 'available': False,
                  'endpoint': self.base_url, 'local_only': True}
        if self.module is None:
            return {**result, 'error': self.load_error}
        try:
            payload = self.transport.get(self.base_url + '/models', timeout=2).json()
            ids = [row['id'] for row in payload.get('data', []) if isinstance(row, dict) and isinstance(row.get('id'), str)]
            return {**result, 'model': ids[0] if len(ids) == 1 else None, 'models': ids,
                    'available': bool(ids), 'error': None if ids else 'No served model was reported.'}
        except Exception:
            return {**result, 'error': 'The local model service is unavailable.'}

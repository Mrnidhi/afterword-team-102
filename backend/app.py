"""Afterword translation service: POST /translate, GET /languages, GET /health.

Only ever sees the plain-language text a caller passes in — never the raw
source documents. Calls the local LLM and embedding servers over HTTP.

Run it (needs fastapi/uvicorn/httpx — present in the `zgx` conda env):

  cd backend && /home/hp24/miniforge3/envs/zgx/bin/python -m uvicorn app:app --port 8010

Config (env vars, all optional):
  LLM_URL               default http://127.0.0.1:8000/v1
  EMBED_URL              default http://127.0.0.1:8003/v1
  ROUND_TRIP_THRESHOLD   default 0.85  (validated in phase 0 — see MULTILINGUAL-PLAN.md)
  PROMPT_VERSION         default "2" — bump to invalidate the cache after a prompt change
  DB_PATH                default ~/Documents/Afterword-Integration/runtime/translations.sqlite3
  PROMPT_VERSION         default "2" — bump to invalidate the cache after a prompt change
  DB_PATH                default ~/Documents/Afterword-Integration/runtime/translations.sqlite3
"""
import hashlib
import json
import os
import re
import sqlite3
import sys
import threading
import time
from contextlib import contextmanager
from collections import Counter
from collections import Counter
from pathlib import Path
from urllib.parse import urlsplit
from urllib.parse import urlsplit

import httpx
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

sys.path.insert(0, str(Path(__file__).resolve().parent))
from demo_content import demo_texts  # noqa: E402
from translate import check, protect, restore  # noqa: E402
import auth  # noqa: E402

LLM_URL = os.environ.get('LLM_URL', 'http://127.0.0.1:8000/v1')
EMBED_URL = os.environ.get('EMBED_URL', 'http://127.0.0.1:8003/v1')
THRESHOLD = float(os.environ.get('ROUND_TRIP_THRESHOLD', '0.85'))
PROMPT_VERSION = os.environ.get('PROMPT_VERSION', '2')
# Separate from the operator's prompt version: even a pinned old environment
# must not replay translations accepted before the protected-details guard.
TOKEN_GUARD_VERSION = '2'
DB_PATH = Path(os.environ.get('DB_PATH', Path.home() / 'Documents/Afterword-Integration/runtime/translations.sqlite3'))
PROMPT_VERSION = os.environ.get('PROMPT_VERSION', '2')
# Separate from the operator's prompt version: even a pinned old environment
# must not replay translations accepted before the protected-details guard.
TOKEN_GUARD_VERSION = '2'
DB_PATH = Path(os.environ.get('DB_PATH', Path.home() / 'Documents/Afterword-Integration/runtime/translations.sqlite3'))
MAX_CHARS = 12000
REQUEST_TIMEOUT = 60.0

# Phase 0 findings: Vietnamese renders fine in the app's body font (Plus
# Jakarta Sans) with no fallback; Hindi needs Noto Sans Devanagari.
LANGUAGES = {
    'es': {'name': 'Spanish', 'native_name': 'Español', 'script': 'Latin', 'font': None},
    'vi': {'name': 'Vietnamese', 'native_name': 'Tiếng Việt', 'script': 'Latin', 'font': None},
    'hi': {'name': 'Hindi', 'native_name': 'हिन्दी', 'script': 'Devanagari',
           'font': {'family': 'Noto Sans Devanagari',
                    'css_url': None}},
                    'css_url': None}},
}
KINDS = {'summary', 'letter', 'instruction'}
CORS_ORIGINS = ['http://127.0.0.1:8080', 'http://localhost:8080']
HINDI_GLOSSARY_HINT = (
    '\nFor Hindi, keep insurance policy as पॉलिसी and provider as प्रदाता when those terms occur.'
)
NEGATION_RE = re.compile(r'\b(?:no|not|never|none|neither|nor|without|cannot|can\'t|won\'t|don\'t|isn\'t|wasn\'t|weren\'t|didn\'t|doesn\'t|hasn\'t|haven\'t|hadn\'t)\b', re.I)
CORS_ORIGINS = ['http://127.0.0.1:8080', 'http://localhost:8080']
HINDI_GLOSSARY_HINT = (
    '\nFor Hindi, keep insurance policy as पॉलिसी and provider as प्रदाता when those terms occur.'
)
NEGATION_RE = re.compile(r'\b(?:no|not|never|none|neither|nor|without|cannot|can\'t|won\'t|don\'t|isn\'t|wasn\'t|weren\'t|didn\'t|doesn\'t|hasn\'t|haven\'t|hadn\'t)\b', re.I)

FORWARD_PROMPT = (
    'You translate short texts for a family dealing with the practical affairs of someone who has died.\n'
    'Translate the user text from English into {language}. Output only the translation, nothing else.\n'
    'Rules:\n'
    '- Keep every token that looks like ⟦Tn⟧ exactly as written, once each. '
    'Never translate, remove or duplicate them.\n'
    '- Use plain, respectful, everyday words at roughly a sixth-grade reading level.\n'
    '- Prefer common {language} words over English finance jargon where one exists.\n'
    '- Do not add, remove or explain any facts. Keep the paragraph breaks.'
)
BACK_PROMPT = (
    'Translate the user text from {language} into English. Output only the translation, nothing else.\n'
    'Keep every token that looks like ⟦Tn⟧ exactly as written, once each.'
)


class TranslateRequest(BaseModel):
    text: str = Field(min_length=1, max_length=MAX_CHARS)
    target_lang: str
    kind: str


class TranslateResponse(BaseModel):
    text: str
    lang: str
    cached: bool
    round_trip_score: float
    protected_tokens_ok: bool
    low_confidence: bool
    ms: int


class SignupRequest(BaseModel):
    username: str
    display_name: str
    password: str


class LoginRequest(BaseModel):
    username: str
    password: str


class WorkspaceRequest(BaseModel):
    state: dict


app = FastAPI(title='Afterword translation service')
# Dev-only: the real demo serves dist/ from this same device (same origin, no
# CORS needed). Locally, dist/ and this API usually run on different ports —
# permissive CORS unblocks that without special-casing every dev port.
_client = httpx.Client(timeout=REQUEST_TIMEOUT,trust_env=False,follow_redirects=False)
# Dev-only: the real demo serves dist/ from this same device (same origin, no
# CORS needed). Locally, dist/ and this API usually run on different ports —
# permissive CORS unblocks that without special-casing every dev port.
_client = httpx.Client(timeout=REQUEST_TIMEOUT,trust_env=False,follow_redirects=False)
_model_id_cache = {'id': None}
_prewarm = {'done': 0, 'total': 0, 'started': False}
app.add_middleware(CORSMiddleware, allow_origins=CORS_ORIGINS,
                   allow_methods=['GET', 'POST', 'PUT'], allow_headers=['*'])
_prewarm = {'done': 0, 'total': 0, 'started': False}
app.add_middleware(CORSMiddleware, allow_origins=CORS_ORIGINS,
                   allow_methods=['GET', 'POST', 'PUT'], allow_headers=['*'])


@app.middleware('http')
async def privacy_headers(request, call_next):
    response = await call_next(request)
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['Referrer-Policy'] = 'no-referrer'
    response.headers['Permissions-Policy'] = 'camera=(), microphone=(), geolocation=()'
    response.headers['Content-Security-Policy'] = (
        "default-src 'self'; connect-src 'self'; img-src 'self' data:; "
        "font-src 'self'; style-src 'self'; script-src 'self'; "
        "object-src 'none'; base-uri 'self'; frame-ancestors 'none'; form-action 'self'")
    return response


# ---- storage -------------------------------------------------------------

def init_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(DB_PATH) as db:
        db.execute('''
            CREATE TABLE IF NOT EXISTS translations (
                lang TEXT NOT NULL,
                kind TEXT NOT NULL,
                source_hash TEXT NOT NULL,
                prompt_version TEXT NOT NULL,
                model_id TEXT NOT NULL,
                text TEXT NOT NULL,
                round_trip_score REAL NOT NULL,
                protected_tokens_ok INTEGER NOT NULL,
                negation_flip INTEGER NOT NULL DEFAULT 0,
                ms INTEGER NOT NULL,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                PRIMARY KEY (lang, kind, source_hash, prompt_version, model_id)
            )
        ''')
        columns = {row[1] for row in db.execute('PRAGMA table_info(translations)')}
        if 'negation_flip' not in columns:
        columns = {row[1] for row in db.execute('PRAGMA table_info(translations)')}
        if 'negation_flip' not in columns:
            db.execute('ALTER TABLE translations ADD COLUMN negation_flip INTEGER NOT NULL DEFAULT 0')


@contextmanager
def db_conn():
    db = sqlite3.connect(DB_PATH)
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    try:
        yield db
    finally:
        db.close()


@app.on_event('startup')
def _startup():
    init_db()
    auth.init_db()


# ---- model calls -----------------------------------------------------------

def llm_model_id():
    # Discover at request time: swapping weights must not require a backend restart.
    local_endpoint(LLM_URL,8000)
    response=_client.get(f'{LLM_URL}/models')
    response.raise_for_status()
    _model_id_cache['id'] = response.json()['data'][0]['id']
    # Discover at request time: swapping weights must not require a backend restart.
    local_endpoint(LLM_URL,8000)
    response=_client.get(f'{LLM_URL}/models')
    response.raise_for_status()
    _model_id_cache['id'] = response.json()['data'][0]['id']
    return _model_id_cache['id']


def local_endpoint(url,port):
    try:
        parsed=urlsplit(url)
        valid=(parsed.scheme=='http' and parsed.hostname in {'127.0.0.1','localhost','::1'} and parsed.port==port and not parsed.username and not parsed.password and not parsed.query and not parsed.fragment and parsed.path.rstrip('/')=='/v1')
    except ValueError:
        valid=False
    if not valid:
        raise HTTPException(503,'Translation requires the configured local model service.')


def local_endpoint(url,port):
    try:
        parsed=urlsplit(url)
        valid=(parsed.scheme=='http' and parsed.hostname in {'127.0.0.1','localhost','::1'} and parsed.port==port and not parsed.username and not parsed.password and not parsed.query and not parsed.fragment and parsed.path.rstrip('/')=='/v1')
    except ValueError:
        valid=False
    if not valid:
        raise HTTPException(503,'Translation requires the configured local model service.')


def chat(system, text):
    local_endpoint(LLM_URL,8000)
    local_endpoint(LLM_URL,8000)
    r = _client.post(f'{LLM_URL}/chat/completions', json={
        'messages': [{'role': 'system', 'content': system}, {'role': 'user', 'content': text}],
        'temperature': 0, 'max_tokens': 2048})
    r.raise_for_status()
    return r.json()['choices'][0]['message']['content'].strip()


def embed(texts):
    local_endpoint(EMBED_URL,8003)
    local_endpoint(EMBED_URL,8003)
    r = _client.post(f'{EMBED_URL}/embeddings', json={'input': texts})
    r.raise_for_status()
    return [d['embedding'] for d in r.json()['data']]


def cosine(a, b):
    va, vb = embed([a, b])  # bge embeddings are pre-normalized
    return sum(x * y for x, y in zip(va, vb))


def translate_with_retry(system, masked, tokens):
    """One attempt, then one retry if a protected token was dropped, duplicated
    or invented. Returns (text, problems) — problems is empty when every
    token survived, from whichever attempt did best."""
    translated = chat(system, masked)
    problems = protected_problems(translated, tokens)
    problems = protected_problems(translated, tokens)
    if problems:
        retry = chat(system, masked)
        retry_problems = protected_problems(retry, tokens)
        retry_problems = protected_problems(retry, tokens)
        if len(retry_problems) < len(problems):
            return retry, retry_problems
    return translated, problems


_TOKEN_MARKUP = re.compile(r'[⟦⟧]|\\u27e[67]|\[{1,2}\s*[Tt]\s*\d+\s*\]{1,2}', re.I)


def protected_problems(text, tokens):
    """Check exact known tokens and reject unknown or malformed marker remnants."""
    if not isinstance(text, str) or not text.strip():
        return ['empty translation']
    problems = check(text, tokens)
    remainder = text
    for token in tokens:
        remainder = remainder.replace(token.sentinel, '')
    if _TOKEN_MARKUP.search(remainder):
        problems.append('unknown or corrupted protected-detail marker')
    return problems


def restored_details_ok(text, tokens):
    if not isinstance(text, str) or not text.strip() or _TOKEN_MARKUP.search(text):
        return False
    required = Counter(token.value for token in tokens)
    observed = Counter(token.value for token in protect(text)[1])
    return all(observed[value] >= count for value, count in required.items())


def unsafe_translation():
    # The existing frontend keeps the complete English text above its error
    # state. Never label an English fallback or broken placeholders as translated.
    raise HTTPException(503, 'Local translation did not preserve the protected details. Original text remains available.')


def forward_prompt(language):
    prompt = FORWARD_PROMPT.format(language=language)
    return prompt + HINDI_GLOSSARY_HINT if language == 'Hindi' else prompt


def negation_flip(source, round_trip):
    """Flag changes in whether the English source contains a negation."""
    return bool(NEGATION_RE.search(source)) != bool(NEGATION_RE.search(round_trip))
_TOKEN_MARKUP = re.compile(r'[⟦⟧]|\\u27e[67]|\[{1,2}\s*[Tt]\s*\d+\s*\]{1,2}', re.I)


def protected_problems(text, tokens):
    """Check exact known tokens and reject unknown or malformed marker remnants."""
    if not isinstance(text, str) or not text.strip():
        return ['empty translation']
    problems = check(text, tokens)
    remainder = text
    for token in tokens:
        remainder = remainder.replace(token.sentinel, '')
    if _TOKEN_MARKUP.search(remainder):
        problems.append('unknown or corrupted protected-detail marker')
    return problems


def restored_details_ok(text, tokens):
    if not isinstance(text, str) or not text.strip() or _TOKEN_MARKUP.search(text):
        return False
    required = Counter(token.value for token in tokens)
    observed = Counter(token.value for token in protect(text)[1])
    return all(observed[value] >= count for value, count in required.items())


def unsafe_translation():
    # The existing frontend keeps the complete English text above its error
    # state. Never label an English fallback or broken placeholders as translated.
    raise HTTPException(503, 'Local translation did not preserve the protected details. Original text remains available.')


def forward_prompt(language):
    prompt = FORWARD_PROMPT.format(language=language)
    return prompt + HINDI_GLOSSARY_HINT if language == 'Hindi' else prompt


def negation_flip(source, round_trip):
    """Flag changes in whether the English source contains a negation."""
    return bool(NEGATION_RE.search(source)) != bool(NEGATION_RE.search(round_trip))


def do_translate(text, target_lang, kind, bypass_cache=False):
    if target_lang not in LANGUAGES:
        raise HTTPException(422, f'target_lang must be one of {sorted(LANGUAGES)}')
    if kind not in KINDS:
        raise HTTPException(422, f'kind must be one of {sorted(KINDS)}')

    if target_lang not in LANGUAGES:
        raise HTTPException(422, f'target_lang must be one of {sorted(LANGUAGES)}')
    if kind not in KINDS:
        raise HTTPException(422, f'kind must be one of {sorted(KINDS)}')

    t0 = time.perf_counter()
    if _TOKEN_MARKUP.search(text):
        unsafe_translation()
    masked, tokens = protect(text)
    if _TOKEN_MARKUP.search(text):
        unsafe_translation()
    masked, tokens = protect(text)
    source_hash = hashlib.sha256(text.encode()).hexdigest()
    model_id = llm_model_id()
    language = LANGUAGES[target_lang]['name']
    cache_version = PROMPT_VERSION + ':protected-' + TOKEN_GUARD_VERSION
    cache_version = PROMPT_VERSION + ':protected-' + TOKEN_GUARD_VERSION

    if not bypass_cache:
        with db_conn() as db:
            row = db.execute(
                'SELECT * FROM translations WHERE lang=? AND kind=? AND source_hash=? '
                'AND prompt_version=? AND model_id=?',
                (target_lang, kind, source_hash, cache_version, model_id)).fetchone()
        if row and bool(row['protected_tokens_ok']) and restored_details_ok(row['text'], tokens):
                (target_lang, kind, source_hash, cache_version, model_id)).fetchone()
        if row and bool(row['protected_tokens_ok']) and restored_details_ok(row['text'], tokens):
            return TranslateResponse(
                text=row['text'], lang=target_lang, cached=True,
                round_trip_score=row['round_trip_score'], protected_tokens_ok=True,
                round_trip_score=row['round_trip_score'], protected_tokens_ok=True,
                low_confidence=(row['round_trip_score'] < THRESHOLD) or bool(row['negation_flip']),
                ms=round((time.perf_counter() - t0) * 1000))

    translated, problems = translate_with_retry(forward_prompt(language), masked, tokens)
    if problems:
        unsafe_translation()
    if problems:
        unsafe_translation()
    back = chat(BACK_PROMPT.format(language=language), translated)
    if protected_problems(back, tokens):
        unsafe_translation()
    if protected_problems(back, tokens):
        unsafe_translation()
    restored_back = restore(back, tokens)
    score = cosine(text, restored_back)
    flipped = negation_flip(text, restored_back)
    flipped = negation_flip(text, restored_back)
    final_text = restore(translated, tokens)
    if not restored_details_ok(final_text, tokens):
        unsafe_translation()
    if not restored_details_ok(final_text, tokens):
        unsafe_translation()
    ms = round((time.perf_counter() - t0) * 1000)

    with db_conn() as db:
        db.execute('''INSERT OR REPLACE INTO translations
            (lang, kind, source_hash, prompt_version, model_id, text, round_trip_score, protected_tokens_ok, negation_flip, ms)
            VALUES (?,?,?,?,?,?,?,?,?,?)''',
            (target_lang, kind, source_hash, cache_version, model_id, final_text, score, True, flipped, ms))
            (target_lang, kind, source_hash, cache_version, model_id, final_text, score, True, flipped, ms))
        db.commit()
    return TranslateResponse(text=final_text, lang=target_lang, cached=False,
                             round_trip_score=score, protected_tokens_ok=True,
                             low_confidence=(score < THRESHOLD) or flipped, ms=ms)


def run_prewarm():
    entries = demo_texts()
    _prewarm.update(done=0, total=len(entries) * len(LANGUAGES), started=True)
    for kind, _entry_id, text in entries:
        for code in LANGUAGES:
            try:
                do_translate(text, code, kind)
            except Exception as exc:
                print(f'Prewarm skipped {code}/{kind}: {exc}', file=sys.stderr)
            finally:
                _prewarm['done'] += 1


@app.on_event('startup')
def _start_prewarm():
    if not _prewarm['started']:
        _prewarm['started'] = True
        threading.Thread(target=run_prewarm, daemon=True).start()


# ---- endpoints ---------------------------------------------------------------

@app.get('/languages')
def languages():
    return [{'code': code, **info} for code, info in LANGUAGES.items()]


@app.get('/health')
def health():
    def up(url):
        try:
            local_endpoint(url,8000 if url==LLM_URL else 8003)
            return _client.get(f'{url}/models', timeout=3).status_code == 200
        except (httpx.HTTPError,HTTPException):
            return False
    prewarm = f"{_prewarm['done']}/{_prewarm['total']}" if _prewarm['started'] else 'not started'
    return {'status': 'ok', 'llm': up(LLM_URL), 'embeddings': up(EMBED_URL), 'prewarm': prewarm}


@app.post('/translate', response_model=TranslateResponse)
def translate(req: TranslateRequest):
    return do_translate(req.text, req.target_lang, req.kind)


# ---- HP-local accounts and workspace state --------------------------------

def session_payload(session):
    return {'user': {'id': session['id'], 'username': session['username'],
                     'display_name': session['display_name']},
            'csrf_token': session['csrf_token']}


@app.post('/api/auth/signup')
def signup(req: SignupRequest, response: Response):
    user = auth.create_user(req.username, req.display_name, req.password)
    token, csrf = auth.begin_session(user)
    auth.set_session_cookie(response, token)
    return {'user': user, 'csrf_token': csrf}


@app.post('/api/auth/login')
def login(req: LoginRequest, response: Response):
    user = auth.verify_user(req.username, req.password)
    token, csrf = auth.begin_session(user)
    auth.set_session_cookie(response, token)
    return {'user': user, 'csrf_token': csrf}


@app.get('/api/auth/session')
def session(request: Request):
    return session_payload(auth.current_session(request))


@app.post('/api/auth/logout')
def logout(request: Request, response: Response):
    current = auth.current_session(request)
    auth.require_csrf(request, current)
    current = auth.current_session(request)
    auth.require_csrf(request, current)
    auth.end_session(request)
    auth.clear_session_cookie(response)
    return {'ok': True}


@app.get('/api/workspace')
def get_workspace(request: Request):
    current = auth.current_session(request)
    return auth.read_workspace(current['id'])
    current = auth.current_session(request)
    return auth.read_workspace(current['id'])


@app.put('/api/workspace')
def put_workspace(req: WorkspaceRequest, request: Request):
    current = auth.current_session(request)
    auth.require_csrf(request, current)
    return auth.write_workspace(current['id'], req.state)
    current = auth.current_session(request)
    auth.require_csrf(request, current)
    return auth.write_workspace(current['id'], req.state)


# ---- public landing and protected application shells ----------------------
# ---- public landing and protected application shells ----------------------

_dist_dir = Path(__file__).resolve().parent.parent / 'dist'


def static_file(name):
    return FileResponse(_dist_dir / name)


@app.get('/')
def landing():
    return static_file('landing.html')


@app.get('/login')
@app.get('/signup')
def auth_page():
    return static_file('auth.html')


@app.get('/app')
def app_without_slash():
    return RedirectResponse('/app/', status_code=307)


@app.get('/app/')
def workspace_page(request: Request):
    try:
        auth.current_session(request)
    except HTTPException:
        return RedirectResponse('/login?next=/app/', status_code=303)
    return static_file('app.html')


if _dist_dir.is_dir():
    app.mount('/', StaticFiles(directory=_dist_dir, html=True), name='dist')

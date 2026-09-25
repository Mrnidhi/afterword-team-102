"""Afterword translation service: POST /translate, GET /languages, GET /health.

Only ever sees the plain-language text a caller passes in — never the raw
source documents. Calls the local LLM and embedding servers over HTTP.

Run it (needs fastapi/uvicorn/httpx — present in the `zgx` conda env):

  cd backend && /home/hp24/miniforge3/envs/zgx/bin/python -m uvicorn app:app --port 8010

This also now serves dist/ itself at that same address (see the static mount
at the bottom of this file) — open http://<device>:8010/ for a same-origin
demo that needs no CORS and none of dist/i18n.js's dev-port URL guessing.

Config (env vars, all optional):
  LLM_URL               default http://127.0.0.1:8000/v1
  EMBED_URL              default http://127.0.0.1:8003/v1
  ROUND_TRIP_THRESHOLD   default 0.85  (validated in phase 0 — see MULTILINGUAL-PLAN.md)
  PROMPT_VERSION         default "3" — bump to invalidate the cache after a prompt or QC-check change
  DB_PATH                default backend/afterword.db
  CORS_ORIGINS           default "*" — comma-separated allowlist for any deployment that isn't same-origin
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
from pathlib import Path

import httpx
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

sys.path.insert(0, str(Path(__file__).resolve().parent))
from demo_content import demo_texts  # noqa: E402
from translate import check, protect, restore  # noqa: E402
import auth  # noqa: E402

LLM_URL = os.environ.get('LLM_URL', 'http://127.0.0.1:8000/v1')
EMBED_URL = os.environ.get('EMBED_URL', 'http://127.0.0.1:8003/v1')
THRESHOLD = float(os.environ.get('ROUND_TRIP_THRESHOLD', '0.85'))
# Bumped '1' -> '2' -> '3': the negation guard and Hindi glossary hint (v2),
# then translate.py's restore() no longer echoing an invented sentinel
# verbatim (v3) all change what counts as a trustworthy, clean translation —
# every cached row needs a fresh round trip through the new checks, not just
# a new prompt string.
PROMPT_VERSION = os.environ.get('PROMPT_VERSION', '3')
DB_PATH = Path(os.environ.get('DB_PATH', Path(__file__).resolve().parent / 'afterword.db'))
MAX_CHARS = 12000
REQUEST_TIMEOUT = 60.0
# Dev default stays permissive: dist/ and this API commonly run on different
# ports locally. Once dist/ is served from this same app (see the static
# mount at the bottom of this file) or from the same origin as a deployed
# backend, no cross-origin request ever happens and this setting is moot —
# for any other deployment, set CORS_ORIGINS to an explicit comma-separated
# allowlist instead of leaving the wildcard in place.
# Same-origin is the normal application mode.  The explicit local-dev list
# preserves the existing split-port developer workflow without allowing every
# website on a network to call this service.
CORS_ORIGINS = [origin for origin in os.environ.get(
    'CORS_ORIGINS', 'http://127.0.0.1:8080,http://localhost:8080').split(',') if origin]

# Phase 0 findings: Vietnamese renders fine in the app's body font (Plus
# Jakarta Sans) with no fallback; Hindi needs Noto Sans Devanagari.
LANGUAGES = {
    'es': {'name': 'Spanish', 'native_name': 'Español', 'script': 'Latin', 'font': None},
    'vi': {'name': 'Vietnamese', 'native_name': 'Tiếng Việt', 'script': 'Latin', 'font': None},
    'hi': {'name': 'Hindi', 'native_name': 'हिन्दी', 'script': 'Devanagari',
           'font': {'family': 'Noto Sans Devanagari',
                    'css_url': 'https://fonts.googleapis.com/css2?family=Noto+Sans+Devanagari:wght@400;600&display=swap'}},
}
KINDS = {'summary', 'letter', 'instruction'}

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

# Phase 0 and phase 6 both found this model repeatedly mistranslating two
# specific insurance/admin terms into Hindi ("policy" -> "नियमित नियम" /
# "नियमित प्रकाशन", "provider" -> "उपकरण"). es/vi never showed this problem, so
# this is a targeted glossary hint, not a general instruction added for every
# language. See MULTILINGUAL-PLAN.md's gap-resolution notes for the before/
# after re-translation that confirmed this actually fixes both cases.
HINDI_GLOSSARY_HINT = (
    "\n- For an insurance or financial 'policy', use पॉलिसी. For a service, "
    "insurance or medical 'provider', use प्रदाता. Do not paraphrase either word."
)


def forward_prompt(language):
    prompt = FORWARD_PROMPT.format(language=language)
    return prompt + HINDI_GLOSSARY_HINT if language == 'Hindi' else prompt


# Phase 0's calibration found round-trip cosine can score a flipped negation
# ("was applied" -> "was not applied") *above* the 0.85 threshold, since the
# two sentences are near-paraphrases in embedding space — a known blind spot,
# not something a similarity score alone can close. This is a cheap,
# deliberately narrow second check: it doesn't understand meaning, it only
# asks whether a negation word appears on one side of the round trip and not
# the other. That's enough to catch the specific failure mode phase 0 found
# without trying to build a general fact-checker.
NEGATION_RE = re.compile(
    r"\b(not|never|cannot|can't|won't|doesn't|didn't|isn't|wasn't|aren't|weren't|"
    r"hasn't|hadn't|no longer|without)\b", re.IGNORECASE)


def negation_flip(original, round_tripped):
    return bool(NEGATION_RE.search(original)) != bool(NEGATION_RE.search(round_tripped))


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
app.add_middleware(CORSMiddleware, allow_origins=CORS_ORIGINS, allow_methods=['GET', 'POST'], allow_headers=['*'])
_client = httpx.Client(timeout=REQUEST_TIMEOUT)
_model_id_cache = {'id': None}


@app.middleware('http')
async def privacy_headers(request, call_next):
    """Keep the browser on the HP-hosted application boundary by default."""
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
        # Migrates a database created before the negation guard existed —
        # CREATE TABLE IF NOT EXISTS above is a no-op against an existing
        # table, so an old afterword.db needs this column added explicitly.
        cols = {row[1] for row in db.execute('PRAGMA table_info(translations)')}
        if 'negation_flip' not in cols:
            db.execute('ALTER TABLE translations ADD COLUMN negation_flip INTEGER NOT NULL DEFAULT 0')


@contextmanager
def db_conn():
    # timeout=30: retry instead of failing immediately if another writer
    # (the prewarm thread, a concurrent request, metrics.py run alongside
    # the live server) holds the lock for a moment.
    db = sqlite3.connect(DB_PATH, timeout=30)
    db.row_factory = sqlite3.Row
    try:
        yield db
    finally:
        db.close()


_prewarm = {'done': 0, 'total': 0, 'started': False}


def run_prewarm():
    """Translates every finding, letter and task instruction into es/vi/hi at
    startup, so the demo never waits on a cold translation on stage. Each
    call goes through do_translate exactly as a real request would — a
    prior run's SQLite cache just makes most of these instant."""
    texts = demo_texts()
    _prewarm['total'] = len(texts) * len(LANGUAGES)
    for kind, content_id, text in texts:
        for lang in LANGUAGES:
            try:
                do_translate(text, lang, kind)
            except Exception as e:  # noqa: BLE001 — one bad item must not stop the rest
                print(f'[prewarm] failed: {kind}/{content_id}/{lang}: {e}')
            _prewarm['done'] += 1
    print(f"[prewarm] done: {_prewarm['done']}/{_prewarm['total']}")


@app.on_event('startup')
def _startup():
    init_db()
    auth.init_db()
    _prewarm['started'] = True
    threading.Thread(target=run_prewarm, daemon=True).start()


# ---- model calls -----------------------------------------------------------

def llm_model_id():
    # Cached for the process lifetime. Restart the service to pick up a model
    # swap on the Nano — that also naturally busts the cache (see PROMPT_VERSION).
    if not _model_id_cache['id']:
        _model_id_cache['id'] = _client.get(f'{LLM_URL}/models').json()['data'][0]['id']
    return _model_id_cache['id']


def chat(system, text):
    r = _client.post(f'{LLM_URL}/chat/completions', json={
        'messages': [{'role': 'system', 'content': system}, {'role': 'user', 'content': text}],
        'temperature': 0, 'max_tokens': 2048})
    r.raise_for_status()
    return r.json()['choices'][0]['message']['content'].strip()


def embed(texts):
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
    problems = check(translated, tokens)
    if problems:
        retry = chat(system, masked)
        retry_problems = check(retry, tokens)
        if len(retry_problems) < len(problems):
            return retry, retry_problems
    return translated, problems


# ---- endpoints ---------------------------------------------------------------

@app.get('/languages')
def languages():
    return [{'code': code, **info} for code, info in LANGUAGES.items()]


@app.get('/health')
def health():
    def up(url):
        try:
            return _client.get(f'{url}/models', timeout=3).status_code == 200
        except httpx.HTTPError:
            return False
    return {'status': 'ok', 'llm': up(LLM_URL), 'embeddings': up(EMBED_URL),
            'prewarm': f"{_prewarm['done']}/{_prewarm['total']}" if _prewarm['started'] else 'not started'}


def do_translate(text, target_lang, kind, bypass_cache=False):
    """The actual translate pipeline, shared by the /translate route, the
    startup prewarm, and metrics.py's cold-latency measurements (which pass
    bypass_cache=True to force a real model call instead of a cache hit —
    the result is still written to cache afterward, so it isn't wasted)."""
    t0 = time.perf_counter()
    source_hash = hashlib.sha256(text.encode()).hexdigest()
    model_id = llm_model_id()
    language = LANGUAGES[target_lang]['name']

    if not bypass_cache:
        with db_conn() as db:
            row = db.execute(
                'SELECT * FROM translations WHERE lang=? AND kind=? AND source_hash=? '
                'AND prompt_version=? AND model_id=?',
                (target_lang, kind, source_hash, PROMPT_VERSION, model_id)).fetchone()
        if row:
            return TranslateResponse(
                text=row['text'], lang=target_lang, cached=True,
                round_trip_score=row['round_trip_score'], protected_tokens_ok=bool(row['protected_tokens_ok']),
                low_confidence=(row['round_trip_score'] < THRESHOLD) or bool(row['negation_flip']),
                ms=round((time.perf_counter() - t0) * 1000))

    masked, tokens = protect(text)
    translated, problems = translate_with_retry(forward_prompt(language), masked, tokens)
    tokens_ok = not problems

    # The forward output already carries live sentinels, so it goes straight
    # into the back-translation call without re-masking.
    back = chat(BACK_PROMPT.format(language=language), translated)
    restored_back = restore(back, tokens)
    score = cosine(text, restored_back)
    neg_flip = negation_flip(text, restored_back)

    final_text = restore(translated, tokens)
    ms = round((time.perf_counter() - t0) * 1000)

    with db_conn() as db:
        db.execute('''INSERT OR REPLACE INTO translations
            (lang, kind, source_hash, prompt_version, model_id, text, round_trip_score, protected_tokens_ok, negation_flip, ms)
            VALUES (?,?,?,?,?,?,?,?,?,?)''',
            (target_lang, kind, source_hash, PROMPT_VERSION, model_id,
             final_text, score, tokens_ok, neg_flip, ms))
        db.commit()

    return TranslateResponse(text=final_text, lang=target_lang, cached=False,
                              round_trip_score=score, protected_tokens_ok=tokens_ok,
                              low_confidence=(score < THRESHOLD) or neg_flip, ms=ms)


@app.post('/translate', response_model=TranslateResponse)
def translate(req: TranslateRequest):
    if req.target_lang not in LANGUAGES:
        raise HTTPException(422, f'target_lang must be one of {sorted(LANGUAGES)}')
    if req.kind not in KINDS:
        raise HTTPException(422, f'kind must be one of {sorted(KINDS)}')
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
    session = auth.current_session(request)
    auth.require_csrf(request, session)
    auth.end_session(request)
    auth.clear_session_cookie(response)
    return {'ok': True}


@app.get('/api/workspace')
def get_workspace(request: Request):
    session = auth.current_session(request)
    return auth.read_workspace(session['id'])


@app.put('/api/workspace')
def put_workspace(req: WorkspaceRequest, request: Request):
    session = auth.current_session(request)
    auth.require_csrf(request, session)
    return auth.write_workspace(session['id'], req.state)


# ---- application shells -----------------------------------------------------

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


# ---- static frontend (the real, same-origin demo path) --------------------
# Phase 2 left this "not wired up yet" — dev has always run dist/ on its own
# `python3 -m http.server`, cross-origin from this API. Mounted last, after
# every API route above: FastAPI/Starlette tries routes in registration
# order, so /translate, /languages and /health always match their own exact
# route first, and only a path none of them own falls through to this mount.
# dist/ is a static, buildless SPA that routes with a URL hash (never sent to
# a server), so serving the one index.html plus its asset files is enough —
# no server-side catch-all/rewrite is needed for client-side routes like
# #evidence or #letters. Run the whole demo from one origin with:
#   cd backend && uvicorn app:app --port 8010
# then open http://<device>:8010/ — no CORS, no dev-port guess in i18n.js.
if _dist_dir.is_dir():
    app.mount('/', StaticFiles(directory=_dist_dir, html=True), name='dist')

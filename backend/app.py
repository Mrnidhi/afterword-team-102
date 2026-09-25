"""Afterword translation service: POST /translate, GET /languages, GET /health.

Only ever sees the plain-language text a caller passes in — never the raw
source documents. Calls the local LLM and embedding servers over HTTP.

Run it (needs fastapi/uvicorn/httpx — present in the `zgx` conda env):

  cd backend && /home/hp24/miniforge3/envs/zgx/bin/python -m uvicorn app:app --port 8010

Config (env vars, all optional):
  LLM_URL               default http://127.0.0.1:8000/v1
  EMBED_URL              default http://127.0.0.1:8003/v1
  ROUND_TRIP_THRESHOLD   default 0.85  (validated in phase 0 — see MULTILINGUAL-PLAN.md)
  PROMPT_VERSION         default "1" — bump to invalidate the cache after a prompt change
  DB_PATH                default ~/Documents/Afterword-Integration/runtime/translations.sqlite3
"""
import hashlib
import os
import sqlite3
import sys
import time
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urlsplit

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

sys.path.insert(0, str(Path(__file__).resolve().parent))
from translate import check, protect, restore  # noqa: E402

LLM_URL = os.environ.get('LLM_URL', 'http://127.0.0.1:8000/v1')
EMBED_URL = os.environ.get('EMBED_URL', 'http://127.0.0.1:8003/v1')
THRESHOLD = float(os.environ.get('ROUND_TRIP_THRESHOLD', '0.85'))
PROMPT_VERSION = os.environ.get('PROMPT_VERSION', '1')
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


app = FastAPI(title='Afterword translation service')
# Dev-only: the real demo serves dist/ from this same device (same origin, no
# CORS needed). Locally, dist/ and this API usually run on different ports —
# permissive CORS unblocks that without special-casing every dev port.
_client = httpx.Client(timeout=REQUEST_TIMEOUT,trust_env=False,follow_redirects=False)
_model_id_cache = {'id': None}


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
                ms INTEGER NOT NULL,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                PRIMARY KEY (lang, kind, source_hash, prompt_version, model_id)
            )
        ''')


@contextmanager
def db_conn():
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    try:
        yield db
    finally:
        db.close()


@app.on_event('startup')
def _startup():
    init_db()


# ---- model calls -----------------------------------------------------------

def llm_model_id():
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


def chat(system, text):
    local_endpoint(LLM_URL,8000)
    r = _client.post(f'{LLM_URL}/chat/completions', json={
        'messages': [{'role': 'system', 'content': system}, {'role': 'user', 'content': text}],
        'temperature': 0, 'max_tokens': 2048})
    r.raise_for_status()
    return r.json()['choices'][0]['message']['content'].strip()


def embed(texts):
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
            local_endpoint(url,8000 if url==LLM_URL else 8003)
            return _client.get(f'{url}/models', timeout=3).status_code == 200
        except (httpx.HTTPError,HTTPException):
            return False
    return {'status': 'ok', 'llm': up(LLM_URL), 'embeddings': up(EMBED_URL)}


@app.post('/translate', response_model=TranslateResponse)
def translate(req: TranslateRequest):
    if req.target_lang not in LANGUAGES:
        raise HTTPException(422, f'target_lang must be one of {sorted(LANGUAGES)}')
    if req.kind not in KINDS:
        raise HTTPException(422, f'kind must be one of {sorted(KINDS)}')

    t0 = time.perf_counter()
    source_hash = hashlib.sha256(req.text.encode()).hexdigest()
    model_id = llm_model_id()
    language = LANGUAGES[req.target_lang]['name']

    with db_conn() as db:
        row = db.execute(
            'SELECT * FROM translations WHERE lang=? AND kind=? AND source_hash=? '
            'AND prompt_version=? AND model_id=?',
            (req.target_lang, req.kind, source_hash, PROMPT_VERSION, model_id)).fetchone()
    if row:
        return TranslateResponse(
            text=row['text'], lang=req.target_lang, cached=True,
            round_trip_score=row['round_trip_score'], protected_tokens_ok=bool(row['protected_tokens_ok']),
            low_confidence=row['round_trip_score'] < THRESHOLD, ms=round((time.perf_counter() - t0) * 1000))

    masked, tokens = protect(req.text)
    translated, problems = translate_with_retry(FORWARD_PROMPT.format(language=language), masked, tokens)
    tokens_ok = not problems

    # The forward output already carries live sentinels, so it goes straight
    # into the back-translation call without re-masking.
    back = chat(BACK_PROMPT.format(language=language), translated)
    score = cosine(req.text, restore(back, tokens))

    final_text = restore(translated, tokens)
    ms = round((time.perf_counter() - t0) * 1000)

    with db_conn() as db:
        db.execute('''INSERT OR REPLACE INTO translations
            (lang, kind, source_hash, prompt_version, model_id, text, round_trip_score, protected_tokens_ok, ms)
            VALUES (?,?,?,?,?,?,?,?,?)''',
            (req.target_lang, req.kind, source_hash, PROMPT_VERSION, model_id,
             final_text, score, tokens_ok, ms))
        db.commit()

    return TranslateResponse(text=final_text, lang=req.target_lang, cached=False,
                              round_trip_score=score, protected_tokens_ok=tokens_ok,
                              low_confidence=score < THRESHOLD, ms=ms)

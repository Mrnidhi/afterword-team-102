"""One local family workspace, with a password and revocable device sessions.

This is a device-local access gate, not multi-user identity or an authority check.
The profile records only details the user explicitly supplies.
"""
import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
import time
from datetime import date
from pathlib import Path
from threading import RLock

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from .contacts import blocked_email, fictional_email, valid_email

COOKIE = 'afterword_session'
SESSION_SECONDS = 12 * 60 * 60
LANGUAGES = {'en', 'es', 'vi', 'hi'}
LIMITS = {'display_name': 150, 'estate_name': 150, 'person_name': 150,
          'writer_name': 150, 'writer_phone': 80, 'relationship': 200,
          'date_of_death': 10, 'reading_language': 5, 'demo_mailbox': 254}
DEFAULT_PROFILE = {**{key: '' for key in LIMITS}, 'reading_language': 'en',
                   'demo_mailbox_confirmed': False}


def profile_values(payload, previous=None):
    unknown = set(payload) - set(DEFAULT_PROFILE)
    if unknown:
        raise HTTPException(422, 'Unknown profile fields: ' + ', '.join(sorted(unknown)) + '.')
    result = dict(previous or DEFAULT_PROFILE)
    for key, value in payload.items():
        if key == 'demo_mailbox_confirmed':
            if not isinstance(value, bool):
                raise HTTPException(422, 'Mailbox confirmation must be true or false.')
        else:
            if not isinstance(value, str) or len(value) > LIMITS[key]:
                raise HTTPException(422, f'{key.replace("_", " ").capitalize()} must be text of at most {LIMITS[key]} characters.')
            value = value.strip()
            if any(ord(character) < 32 or ord(character) == 127 for character in value):
                raise HTTPException(422, 'Profile details cannot contain line breaks or control characters.')
        result[key] = value
    for key in ('display_name', 'estate_name'):
        if not result[key]:
            raise HTTPException(422, f'Enter {"your display name" if key == "display_name" else "a workspace name"}.')
    if result['reading_language'] not in LANGUAGES:
        raise HTTPException(422, 'Choose English, Spanish, Vietnamese, or Hindi as the reading language.')
    phone = result['writer_phone']
    if phone:
        digits = re.sub(r'\D', '', phone)
        if not re.fullmatch(r'\+?[\d ().-]+', phone) or not (
            (not phone.startswith('+') and (len(digits) == 10 or len(digits) == 11 and digits.startswith('1')))
            or phone.startswith('+') and 10 <= len(digits) <= 15
        ):
            raise HTTPException(422, 'Enter a valid contact phone number, or leave it blank for now.')
    if result['date_of_death']:
        try:
            supplied = date.fromisoformat(result['date_of_death'])
            if supplied.isoformat() != result['date_of_death'] or supplied > date.today():
                raise ValueError()
        except ValueError as exc:
            raise HTTPException(422, 'Enter a valid date of death that is not in the future, or leave it blank.') from exc
    email = result['demo_mailbox'].lower()
    if email and (not valid_email(email) or fictional_email(email) or blocked_email(email)):
        raise HTTPException(422, 'Enter a real mailbox you control, or leave the demo mailbox blank.')
    old_email = (previous or {}).get('demo_mailbox', '')
    if email != old_email and 'demo_mailbox_confirmed' not in payload:
        result['demo_mailbox_confirmed'] = False
    result['demo_mailbox'] = email
    if result['demo_mailbox_confirmed'] and not email:
        raise HTTPException(422, 'Enter the mailbox before confirming that you control it.')
    return result


def password_value(payload):
    value = payload.get('password')
    if not isinstance(value, str) or not 10 <= len(value) <= 1024:
        raise HTTPException(422, 'Use a password with 10 to 1024 characters.')
    return value


def password_hash(password, salt):
    if hasattr(hashlib, 'scrypt'):
        return hashlib.scrypt(password.encode('utf-8'), salt=salt, n=32768, r=8, p=1,
                              maxmem=128 * 1024 * 1024, dklen=64).hex()
    # Apple's older system Python omits hashlib.scrypt. Keep exactly the same
    # KDF and parameters when using the portable implementation.
    try:
        from cryptography.hazmat.primitives.kdf.scrypt import Scrypt
    except ImportError as exc:
        raise HTTPException(503, 'Local password storage is unavailable. Install the application requirements and try again.') from exc
    return Scrypt(salt=salt, length=64, n=32768, r=8, p=1).derive(password.encode('utf-8')).hex()


class Workspace:
    def __init__(self, db_path, require_login=False, clock=time.time):
        self.require_login = require_login
        self.clock = clock
        self.lock = RLock()
        if str(db_path) != ':memory:':
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(str(db_path), check_same_thread=False, timeout=10)
        self.connection.row_factory = sqlite3.Row
        with self.connection:
            self.connection.execute('''CREATE TABLE IF NOT EXISTS workspace (
                id INTEGER PRIMARY KEY CHECK (id=1), profile TEXT NOT NULL,
                password_salt TEXT NOT NULL, password_hash TEXT NOT NULL,
                failed_logins INTEGER NOT NULL DEFAULT 0, blocked_until REAL NOT NULL DEFAULT 0)''')
            self.connection.execute('''CREATE TABLE IF NOT EXISTS workspace_sessions (
                token_hash TEXT PRIMARY KEY, expires_at REAL NOT NULL)''')
        if str(db_path) != ':memory:':
            Path(db_path).chmod(0o600)

    def _row(self):
        return self.connection.execute('SELECT * FROM workspace WHERE id=1').fetchone()

    def authenticated(self, token):
        if not token or len(token) > 128:
            return False
        digest = hashlib.sha256(token.encode()).hexdigest()
        with self.lock:
            row = self.connection.execute('SELECT expires_at FROM workspace_sessions WHERE token_hash=?', (digest,)).fetchone()
            return bool(row and row['expires_at'] > self.clock())

    def session(self, token):
        with self.lock:
            row = self._row()
            authenticated = bool(row) and self.authenticated(token)
            return {'enabled': True, 'require_login': self.require_login,
                    'setup_required': row is None, 'authenticated': authenticated,
                    'profile': json.loads(row['profile']) if authenticated else None}

    def _issue_session(self):
        token = secrets.token_urlsafe(32)
        self.connection.execute('DELETE FROM workspace_sessions WHERE expires_at<=?', (self.clock(),))
        self.connection.execute('INSERT INTO workspace_sessions VALUES (?,?)',
                                (hashlib.sha256(token.encode()).hexdigest(), self.clock() + SESSION_SECONDS))
        return token

    def setup(self, payload):
        with self.lock:
            if self._row():
                raise HTTPException(409, 'This workspace is already set up. Sign in with its password.')
        password = password_value(payload)
        profile = profile_values({key: value for key, value in payload.items() if key != 'password'})
        salt = secrets.token_bytes(32)
        digest = password_hash(password, salt)
        with self.lock, self.connection:
            try:
                # The singleton primary key is also the cross-process bootstrap lock.
                self.connection.execute('INSERT INTO workspace (id,profile,password_salt,password_hash) VALUES (1,?,?,?)',
                                        (json.dumps(profile, ensure_ascii=False), salt.hex(), digest))
            except sqlite3.IntegrityError as exc:
                raise HTTPException(409, 'This workspace is already set up. Sign in with its password.') from exc
            token = self._issue_session()
        return token

    def login(self, payload):
        if set(payload) != {'password'}:
            raise HTTPException(422, 'Supply only the workspace password.')
        password = password_value(payload)
        with self.lock, self.connection:
            row = self._row()
            if not row:
                raise HTTPException(409, 'Set up this workspace before signing in.')
            if row['blocked_until'] > self.clock():
                raise HTTPException(429, 'Too many incorrect passwords. Try again in one minute.')
            digest = password_hash(password, bytes.fromhex(row['password_salt']))
            if not hmac.compare_digest(digest, row['password_hash']):
                attempts = (row['failed_logins'] if not row['blocked_until'] else 0) + 1
                blocked_until = self.clock() + 60 if attempts >= 5 else 0
                self.connection.execute('UPDATE workspace SET failed_logins=?,blocked_until=? WHERE id=1', (attempts, blocked_until))
                # Commit the failed attempt before raising an HTTP exception.
                self.connection.commit()
                raise HTTPException(401, 'The password is incorrect.')
            self.connection.execute('UPDATE workspace SET failed_logins=0,blocked_until=0 WHERE id=1')
            return self._issue_session()

    def logout(self, token):
        if token:
            with self.lock, self.connection:
                self.connection.execute('DELETE FROM workspace_sessions WHERE token_hash=?', (hashlib.sha256(token.encode()).hexdigest(),))

    def update(self, token, payload):
        with self.lock, self.connection:
            if not self.authenticated(token):
                raise HTTPException(401, 'Sign in to update your workspace profile.')
            profile = profile_values(payload, json.loads(self._row()['profile']))
            self.connection.execute('UPDATE workspace SET profile=? WHERE id=1', (json.dumps(profile, ensure_ascii=False),))
        return self.session(token)


async def _payload(request):
    body = await request.body()
    if len(body) > 16384:
        raise HTTPException(413, 'Workspace details are too large.')
    try:
        result = json.loads(body)
    except (ValueError, UnicodeDecodeError) as exc:
        raise HTTPException(422, 'Supply workspace details as a JSON object.') from exc
    if not isinstance(result, dict):
        raise HTTPException(422, 'Supply workspace details as a JSON object.')
    return result


def mount_workspace(app, db_path=None, require_login=None, static_dir=None):
    if require_login is None:
        require_login = os.environ.get('AFTERWORD_REQUIRE_LOGIN', '0') == '1'
    directory = Path(os.environ.get('AFTERWORD_DATA_DIR', str(Path.home() / 'Documents/Afterword-Integration/runtime')))
    workspace = Workspace(db_path or os.environ.get('AFTERWORD_WORKSPACE_DB', str(directory / 'workspace.sqlite3')), require_login)
    app.state.workspace = workspace
    static_dir = Path(static_dir).resolve() if static_dir else None
    router = APIRouter(prefix='/workspace')

    def session_cookie(response, token, request):
        response.set_cookie(COOKIE, token, max_age=SESSION_SECONDS, httponly=True,
                            secure=request.url.scheme == 'https', samesite='strict', path='/')

    @router.get('/session')
    def session(request: Request):
        return workspace.session(request.cookies.get(COOKIE))

    @router.post('/setup')
    async def setup(request: Request, response: Response):
        token = await run_in_threadpool(workspace.setup, await _payload(request))
        session_cookie(response, token, request)
        return workspace.session(token)

    @router.post('/login')
    async def login(request: Request, response: Response):
        token = await run_in_threadpool(workspace.login, await _payload(request))
        old_token = request.cookies.get(COOKIE)
        if old_token:
            workspace.logout(old_token)
        session_cookie(response, token, request)
        return workspace.session(token)

    @router.post('/logout')
    def logout(request: Request, response: Response):
        workspace.logout(request.cookies.get(COOKIE))
        response.delete_cookie(COOKIE, httponly=True, samesite='strict', path='/')
        return workspace.session(None)

    @router.patch('/profile')
    async def profile(request: Request):
        return await run_in_threadpool(workspace.update, request.cookies.get(COOKIE), await _payload(request))

    app.include_router(router)

    @app.middleware('http')
    async def require_workspace_session(request: Request, call_next):
        if workspace.require_login:
            path = request.url.path
            public = path in {'/health', '/workspace/session', '/workspace/setup', '/workspace/login'}
            if request.method in {'GET', 'HEAD'}:
                public = public or path in {'/', '/runtime-config.js'}
                if not public and static_dir:
                    candidate = (static_dir / path.lstrip('/')).resolve()
                    public = candidate.is_relative_to(static_dir) and candidate.is_file()
            if not public and not workspace.authenticated(request.cookies.get(COOKIE)):
                return JSONResponse({'detail': 'Sign in to your local workspace to continue.'}, status_code=401)
        return await call_next(request)

    return workspace

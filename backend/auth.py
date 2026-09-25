"""HP-local authentication and per-user workspace persistence for Afterword.

This module intentionally has no outbound dependencies: identities, sessions,
and workspace state live in SQLite on the HP machine.  Browser clients receive
only an opaque HttpOnly session cookie.
"""
import hashlib
import json
import os
import re
import secrets
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError
from fastapi import HTTPException, Request, Response


AUTH_DB_PATH = Path(os.environ.get(
    'WORKSPACE_DB_PATH', Path(__file__).resolve().parent / '.runtime' / 'afterword-workspace.db'))
SESSION_COOKIE = 'afterword_session'
SESSION_DAYS = int(os.environ.get('SESSION_DAYS', '7'))
COOKIE_SECURE = os.environ.get('COOKIE_SECURE', '').lower() in {'1', 'true', 'yes'}
MAX_STATE_BYTES = 220_000
USERNAME_RE = re.compile(r'^[a-z0-9][a-z0-9_.-]{2,31}$')
PASSWORD_UPPER_RE = re.compile(r'[A-Z]')
PASSWORD_LOWER_RE = re.compile(r'[a-z]')
PASSWORD_DIGIT_RE = re.compile(r'\d')
PASSWORD_SPECIAL_RE = re.compile(r'[^A-Za-z0-9]')
_passwords = PasswordHasher()


def now():
    return datetime.now(UTC).isoformat()


@contextmanager
def db_conn():
    AUTH_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(AUTH_DB_PATH, timeout=15)
    db.row_factory = sqlite3.Row
    try:
        yield db
    finally:
        db.close()


def init_db():
    with db_conn() as db:
        db.execute('PRAGMA journal_mode=WAL')
        db.execute('PRAGMA foreign_keys=ON')
        db.executescript('''
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY,
                username TEXT NOT NULL COLLATE NOCASE UNIQUE,
                display_name TEXT NOT NULL,
                password_hash TEXT NOT NULL,
                created_at TEXT NOT NULL,
                disabled_at TEXT
            );
            CREATE TABLE IF NOT EXISTS sessions (
                token_hash TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                csrf_token TEXT NOT NULL,
                created_at TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                last_seen_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_sessions_user_expires
            ON sessions(user_id, expires_at);
            CREATE TABLE IF NOT EXISTS workspace_state (
                user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
                state_json TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
        ''')
        db.execute('PRAGMA optimize')
        db.commit()


def _token_hash(token):
    return hashlib.sha256(token.encode('utf-8')).hexdigest()


def _validate_signup(username, display_name, password):
    username = str(username or '').strip().lower()
    display_name = str(display_name or '').strip()
    if not USERNAME_RE.fullmatch(username):
        raise HTTPException(422, 'Use 3–32 lowercase letters, numbers, dots, dashes, or underscores for your username.')
    if not 1 <= len(display_name) <= 80:
        raise HTTPException(422, 'Enter a display name between 1 and 80 characters.')
    password = str(password or '')
    if not 8 <= len(password) <= 128:
        raise HTTPException(422, 'Use a password of 8–128 characters.')
    if not (PASSWORD_UPPER_RE.search(password) and PASSWORD_LOWER_RE.search(password)
            and PASSWORD_DIGIT_RE.search(password) and PASSWORD_SPECIAL_RE.search(password)):
        raise HTTPException(422, 'Use an uppercase letter, lowercase letter, number, and special character.')
    return username, display_name


def create_user(username, display_name, password):
    username, display_name = _validate_signup(username, display_name, password)
    password_hash = _passwords.hash(password)
    with db_conn() as db:
        try:
            cursor = db.execute(
                'INSERT INTO users(username, display_name, password_hash, created_at) VALUES(?,?,?,?)',
                (username, display_name, password_hash, now()))
        except sqlite3.IntegrityError as exc:
            raise HTTPException(409, 'That username is already in use.') from exc
        user_id = cursor.lastrowid
        db.execute('INSERT INTO workspace_state(user_id, state_json, updated_at) VALUES(?,?,?)',
                   (user_id, '{}', now()))
        db.commit()
    return {'id': user_id, 'username': username, 'display_name': display_name}


def verify_user(username, password):
    with db_conn() as db:
        row = db.execute('SELECT * FROM users WHERE username=? AND disabled_at IS NULL',
                         (str(username or '').strip().lower(),)).fetchone()
    if not row:
        raise HTTPException(401, 'Incorrect username or password.')
    try:
        valid = _passwords.verify(row['password_hash'], str(password or ''))
    except (VerifyMismatchError, InvalidHashError):
        valid = False
    if not valid:
        raise HTTPException(401, 'Incorrect username or password.')
    return {'id': row['id'], 'username': row['username'], 'display_name': row['display_name']}


def begin_session(user):
    token = secrets.token_urlsafe(32)
    csrf = secrets.token_urlsafe(24)
    expiry = (datetime.now(UTC) + timedelta(days=SESSION_DAYS)).isoformat()
    with db_conn() as db:
        db.execute('INSERT INTO sessions(token_hash, user_id, csrf_token, created_at, expires_at, last_seen_at) VALUES(?,?,?,?,?,?)',
                   (_token_hash(token), user['id'], csrf, now(), expiry, now()))
        db.commit()
    return token, csrf


def set_session_cookie(response: Response, token):
    response.set_cookie(SESSION_COOKIE, token, max_age=SESSION_DAYS * 86400,
                        httponly=True, samesite='strict', secure=COOKIE_SECURE, path='/')


def clear_session_cookie(response: Response):
    response.delete_cookie(SESSION_COOKIE, path='/')


def current_session(request: Request):
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        raise HTTPException(401, 'Sign in to continue.')
    with db_conn() as db:
        row = db.execute('''SELECT s.csrf_token, s.expires_at, u.id, u.username, u.display_name
                            FROM sessions s JOIN users u ON u.id=s.user_id
                            WHERE s.token_hash=? AND u.disabled_at IS NULL''', (_token_hash(token),)).fetchone()
        if not row or row['expires_at'] <= now():
            if row:
                db.execute('DELETE FROM sessions WHERE token_hash=?', (_token_hash(token),))
                db.commit()
            raise HTTPException(401, 'Your session has expired. Sign in again.')
        db.execute('UPDATE sessions SET last_seen_at=? WHERE token_hash=?', (now(), _token_hash(token)))
        db.commit()
    return dict(row)


def require_csrf(request: Request, session):
    supplied = request.headers.get('X-CSRF-Token', '')
    if not supplied or not secrets.compare_digest(supplied, session['csrf_token']):
        raise HTTPException(403, 'Your session could not be verified. Refresh and try again.')


def read_workspace(user_id):
    with db_conn() as db:
        row = db.execute('SELECT state_json, updated_at FROM workspace_state WHERE user_id=?', (user_id,)).fetchone()
    return {'state': json.loads(row['state_json']) if row else {}, 'updated_at': row['updated_at'] if row else None}


def write_workspace(user_id, state):
    if not isinstance(state, dict):
        raise HTTPException(422, 'Workspace state must be an object.')
    encoded = json.dumps(state, separators=(',', ':'), ensure_ascii=False)
    if len(encoded.encode('utf-8')) > MAX_STATE_BYTES:
        raise HTTPException(413, 'Workspace data is too large to save.')
    with db_conn() as db:
        db.execute('''INSERT INTO workspace_state(user_id, state_json, updated_at) VALUES(?,?,?)
                      ON CONFLICT(user_id) DO UPDATE SET state_json=excluded.state_json, updated_at=excluded.updated_at''',
                   (user_id, encoded, now()))
        db.commit()
    return {'updated_at': now()}


def end_session(request: Request):
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        with db_conn() as db:
            db.execute('DELETE FROM sessions WHERE token_hash=?', (_token_hash(token),))
            db.commit()

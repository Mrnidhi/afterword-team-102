import json
import sqlite3
from pathlib import Path
from threading import RLock

TABLES = {'providers','documents','findings','outreach','consents','events','settings','lookups'}

class Repository:
    """Small local repository. Consent/events are append-only through this API."""
    def __init__(self, path):
        if str(path) != ':memory:':
            Path(path).parent.mkdir(parents=True,exist_ok=True)
        self.connection = sqlite3.connect(str(path),check_same_thread=False)
        self.lock = RLock()
        with self.connection:
            for table in TABLES:
                self.connection.execute(f'CREATE TABLE IF NOT EXISTS {table} (id TEXT PRIMARY KEY, payload TEXT NOT NULL)')
        if str(path) != ':memory:':
            Path(path).chmod(0o600)

    def get(self, table, key):
        self._table(table)
        with self.lock:
            row = self.connection.execute(f'SELECT payload FROM {table} WHERE id=?',(key,)).fetchone()
        return json.loads(row[0]) if row else None

    def list(self, table):
        self._table(table)
        with self.lock:
            rows = self.connection.execute(f'SELECT payload FROM {table} ORDER BY rowid').fetchall()
        return [json.loads(row[0]) for row in rows]

    def put(self, table, key, value):
        self._table(table)
        statement = 'INSERT' if table in {'consents','events'} else 'INSERT OR REPLACE'
        with self.lock, self.connection:
            self.connection.execute(f'{statement} INTO {table} (id,payload) VALUES (?,?)',(key,json.dumps(value,ensure_ascii=False)))
        return value

    def delete(self, table, key):
        self._table(table)
        if table in {'consents','events'}:
            raise ValueError('Audit records are append-only')
        with self.lock, self.connection:
            self.connection.execute(f'DELETE FROM {table} WHERE id=?',(key,))

    def _table(self, name):
        if name not in TABLES:
            raise ValueError('Unknown table')

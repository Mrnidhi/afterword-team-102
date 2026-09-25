"""Contract findings in their own SQLite database; legacy outreach is untouched."""
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock

from .extraction_contract import CONTRACT


class SourceConflict(ValueError):
    pass


class FindingRepository:
    def __init__(self, path):
        self.path = str(path)
        if self.path != ':memory:':
            destination = Path(path).expanduser()
            destination.parent.mkdir(parents=True, exist_ok=True)
            self.path = str(destination)
        self.lock = RLock()
        self.connection = sqlite3.connect(self.path, check_same_thread=False)
        self.connection.row_factory = sqlite3.Row
        columns = {row['name'] for row in self.connection.execute('PRAGMA table_info(findings)')}
        if columns and ('payload' in columns or 'finding_json' not in columns):
            self.connection.close()
            raise ValueError('Use a separate findings database, not the outreach database.')
        with self.connection:
            self.connection.execute('''CREATE TABLE IF NOT EXISTS findings (
                id TEXT PRIMARY KEY, source TEXT NOT NULL, status TEXT NOT NULL,
                route TEXT, finding_json TEXT NOT NULL, evidence_json TEXT NOT NULL,
                checks_json TEXT NOT NULL, meta_json TEXT NOT NULL,
                text TEXT NOT NULL, created_at TEXT NOT NULL)''')
            self.connection.execute('CREATE TABLE IF NOT EXISTS finding_inputs (id TEXT PRIMARY KEY, reference_date TEXT)')
        if self.path != ':memory:':
            Path(self.path).chmod(0o600)

    def close(self):
        self.connection.close()

    def get(self, identifier):
        with self.lock:
            row = self.connection.execute('SELECT f.*, i.reference_date FROM findings f LEFT JOIN finding_inputs i ON i.id=f.id WHERE f.id=?', (identifier,)).fetchone()
        return self._decode(row) if row else None

    def all(self):
        with self.lock:
            rows = self.connection.execute('SELECT f.*, i.reference_date FROM findings f LEFT JOIN finding_inputs i ON i.id=f.id ORDER BY f.created_at,f.id').fetchall()
        return [self._decode(row) for row in rows]

    def assert_same_source(self, item):
        with self.lock:
            existing = self.get(item.id)
            if existing:
                row = self.connection.execute('SELECT reference_date FROM finding_inputs WHERE id=?', (item.id,)).fetchone()
                stored_reference = row['reference_date'] if row else None
                supplied_reference = item.reference_date.isoformat() if item.reference_date else None
                if existing['text'] != item.text or existing['source'] != item.source or stored_reference != supplied_reference:
                    raise SourceConflict('This document id already belongs to different source text, source type, or reference date. Import it with a new id.')
            return existing

    def save(self, item, result):
        # Encoding with allow_nan=False prevents invalid JSON leaking into the UI.
        encoded = [json.dumps(result[key], ensure_ascii=False, allow_nan=False) for key in ('finding', 'evidence', 'checks', 'meta')]
        with self.lock, self.connection:
            existing = self.assert_same_source(item)
            created = existing['created_at'] if existing else datetime.now(timezone.utc).isoformat()
            self.connection.execute('''INSERT INTO findings
                (id,source,status,route,finding_json,evidence_json,checks_json,meta_json,text,created_at)
                VALUES (?,?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET
                status=excluded.status,route=excluded.route,finding_json=excluded.finding_json,
                evidence_json=excluded.evidence_json,checks_json=excluded.checks_json,meta_json=excluded.meta_json''',
                (item.id, item.source, result['status'], result['route'], *encoded, item.text, created))
            self.connection.execute('INSERT OR IGNORE INTO finding_inputs(id,reference_date) VALUES (?,?)',
                                    (item.id, item.reference_date.isoformat() if item.reference_date else None))
        return result

    @staticmethod
    def envelope(record):
        return {key: value for key, value in record.items() if key not in {'text', 'created_at', 'reference_date'}}

    @staticmethod
    def _decode(row):
        return {'contract': CONTRACT, 'id': row['id'], 'source': row['source'],
                'status': row['status'], 'route': row['route'],
                **{key: json.loads(row[key + '_json']) for key in ('finding', 'evidence', 'checks', 'meta')},
                'text': row['text'], 'created_at': row['created_at'], 'reference_date': row['reference_date']}

"""Serialized document extraction, persisted failures, and source retrieval."""
import json
import os
import time
from collections import Counter
from threading import RLock

from .extraction_contract import CONTRACT, MAX_TEXT, ExtractInput, BatchInput, validate_envelope
from .extraction_engine import LocalEngine
from .extraction_repository import FindingRepository

# One shared process boundary covers different services and single/batch routes.
# Run the local API with one worker, matching the single model server.
MODEL_LOCK = RLock()


class ExtractionService:
    def __init__(self, db_path, engine=None, max_input_chars=None):
        self.max_input_chars = int(max_input_chars if max_input_chars is not None else os.environ.get('AFTERWORD_EXTRACT_MAX_CHARS', '32000'))
        if not 1 <= self.max_input_chars <= MAX_TEXT:
            raise ValueError('AFTERWORD_EXTRACT_MAX_CHARS must be between 1 and 2000000.')
        self.engine = engine if engine is not None else LocalEngine()
        self.repo = FindingRepository(db_path)

    def extract(self, item, retry=False):
        parsed = item if isinstance(item, ExtractInput) else ExtractInput.model_validate(item)
        with MODEL_LOCK:
            return self._extract(parsed, retry)

    def extract_batch(self, items, retry=False):
        batch = BatchInput(items=items)
        with MODEL_LOCK:
            # Source conflicts are detected before starting any expensive work.
            for item in batch.items:
                self.repo.assert_same_source(item)
            return [self._extract(item, retry) for item in batch.items]

    def _extract(self, item, retry):
        existing = self.repo.assert_same_source(item)
        if existing and not retry:
            return self.repo.envelope(existing)
        started = time.perf_counter()
        if len(item.text) > self.max_input_chars:
            result = self._failure(item, started,
                'This document contains ' + str(len(item.text)) + ' characters, exceeding the local inference limit of '
                + str(self.max_input_chars) + '. No model request was made. The complete source was saved unchanged. '
                + 'An operator must confirm the model context capacity before raising AFTERWORD_EXTRACT_MAX_CHARS and retrying.')
            return self.repo.save(item, result)
        try:
            function = getattr(self.engine, 'extract', self.engine)
            result = function(item.text, source=item.source, doc_id=item.id, reference_date=item.reference_date)
            validate_envelope(result, item)
            json.dumps(result, allow_nan=False)
        except Exception as exc:
            # This contains adapter/engine defects too; one bad document must not
            # abort the batch or become a fabricated accepted finding.
            result = self._failure(item, started, 'Local extraction failed (' + type(exc).__name__ + '). Retry this document after checking the model service.')
        return self.repo.save(item, result)

    def _failure(self, item, started, message):
        return {'contract': CONTRACT, 'id': item.id, 'source': item.source,
                'status': 'failed', 'route': None, 'finding': None, 'evidence': [],
                'checks': {'error': message},
                'meta': {'engine': getattr(getattr(self.engine, 'module', None), 'ENGINE_VERSION', None),
                         'model': None, 'tier': 'L1', 'latency_ms': round((time.perf_counter() - started) * 1000),
                         'output_tokens': None, 'raw': None}}

    def get(self, identifier):
        return self.repo.get(identifier)

    def collection(self):
        rows = self.repo.all()
        route = Counter(row['route'] for row in rows)
        status = Counter(row['status'] for row in rows)
        counts = {key: route[key] for key in ('extract', 'memory', 'drop')}
        counts.update({key: status[key] for key in ('accepted', 'needs_review', 'failed')})
        return {'contract': CONTRACT, 'findings': rows, 'total': len(rows), 'counts': counts}

    def health(self):
        if hasattr(self.engine, 'health'):
            return {**self.engine.health(), 'max_input_chars': self.max_input_chars}
        return {'contract': CONTRACT, 'model': None, 'models': [], 'available': False,
                'local_only': True, 'max_input_chars': self.max_input_chars,
                'error': 'Injected engine has no live model identity probe.'}

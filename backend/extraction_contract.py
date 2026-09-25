"""HTTP input and envelope validation, not model extraction semantics."""
from datetime import date
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

CONTRACT = 'afterword.finding/v1'
MAX_ITEMS = 100
MAX_TEXT = 2_000_000
MAX_BATCH_BYTES = 20_000_000


class ExtractInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    id: str = Field(min_length=1, max_length=200, pattern=r'^[A-Za-z0-9][A-Za-z0-9_.:-]*$')
    source: Literal['email', 'sms', 'letter']
    text: str = Field(min_length=1, max_length=MAX_TEXT)
    reference_date: Optional[date] = None

    @field_validator('text')
    @classmethod
    def meaningful_text(cls, value):
        if not value.strip():
            raise ValueError('The document must contain readable text.')
        return value  # Never normalize evidence line breaks or source whitespace.


class BatchInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    items: list[ExtractInput] = Field(min_length=1, max_length=MAX_ITEMS)

    @model_validator(mode='after')
    def bounded_batch(self):
        if sum(len(item.text.encode('utf-8')) for item in self.items) > MAX_BATCH_BYTES:
            raise ValueError('Batch text must not exceed 20 MB.')
        if len({item.id for item in self.items}) != len(self.items):
            raise ValueError('Each document in a batch needs a distinct id.')
        return self


def validate_envelope(result, item):
    """Reject an unusable adapter envelope without rewriting model judgements."""
    if not isinstance(result, dict) or result.get('contract') != CONTRACT:
        raise ValueError('The engine returned an unsupported contract.')
    if result.get('id') != item.id or result.get('source') != item.source:
        raise ValueError('The engine result does not belong to this document.')
    if result.get('status') not in {'accepted', 'needs_review', 'failed'}:
        raise ValueError('The engine returned an invalid status.')
    if result.get('route') not in {'extract', 'memory', 'drop', None}:
        raise ValueError('The engine returned an invalid route.')
    if result.get('finding') is not None and not isinstance(result['finding'], dict):
        raise ValueError('The engine returned an invalid finding.')
    if not isinstance(result.get('evidence'), list) or not isinstance(result.get('checks'), dict) or not isinstance(result.get('meta'), dict):
        raise ValueError('The engine returned an incomplete envelope.')
    # Python's splitlines is the authoritative engine line convention.
    lines = item.text.splitlines()
    for evidence in result['evidence']:
        if not isinstance(evidence, dict):
            raise ValueError('The engine returned invalid evidence.')
        line = evidence.get('line')
        if isinstance(line, bool) or not isinstance(line, int) or not 1 <= line <= len(lines) or evidence.get('text') != lines[line - 1]:
            raise ValueError('The engine evidence does not match the stored document.')
    return result

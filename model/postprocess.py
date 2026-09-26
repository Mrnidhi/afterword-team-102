"""Deterministic clean-up of a model finding, applied after the model and before the gate.

Code, not model. Every rule is either grounding (a value must physically appear in the
document) or a convention the training labels already follow. No rule looks at gold labels.

    from postprocess import clean
    finding = clean(parsed_model_output, document_text)
"""
from __future__ import annotations

import re

from engine import clean_finding


def clean(pred: dict | None, text: str) -> dict | None:
    """Same function the engine runs in production (engine.clean_finding) - one copy only."""
    return clean_finding(pred, text)


def ref_last4(v) -> str | None:
    """What the product actually shows and inserts into letters: the masked ending."""
    if v is None:
        return None
    a = re.sub(r"[^0-9A-Za-z]", "", str(v))
    return a[-4:] if a else None

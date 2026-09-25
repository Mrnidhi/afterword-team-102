"""Afterword extraction schema — the single source of truth.

Every other file (data generation, training, rewards, evaluation, serving)
imports from here. Change a category or field here, nowhere else.

Design rules, each one a decision we can defend to judges:
  * The model outputs compact keys and omits null fields: on bandwidth-bound
    hardware every generated token costs a full read of the model weights.
  * Evidence is line numbers, not quoted text: ~3 tokens instead of ~25, and
    verification is stronger (we check the extracted VALUES appear on those lines).
  * The model never does arithmetic. It extracts facts; money_at_stake,
    deadline dates and priority are computed here by auditable rules.
"""
from __future__ import annotations

import datetime as dt
import json
import re

# ---------------------------------------------------------------- vocabularies

CATEGORIES = [
    "irrelevant",    # newsletters, promotions, chatter         -> dropped by triage
    "personal",      # letters, notes, family messages          -> Memories tab
    "bank", "credit_card", "insurance", "retirement", "investment",
    "loan", "utility", "subscription", "medical", "government",
    "legal", "property",
]

# L0 triage collapses the 14 categories into 3 routing decisions.
TRIAGE_OF = {c: "extract" for c in CATEGORIES}
TRIAGE_OF["irrelevant"] = "drop"
TRIAGE_OF["personal"] = "memory"
TRIAGE_LABELS = ["drop", "memory", "extract"]

AMOUNT_KINDS = ["balance", "charge", "benefit", "due", "face_value"]
RECURRENCE = ["none", "monthly", "quarterly", "annual"]
ACTIONS = ["notify", "claim", "cancel", "stop_payment",
           "verify_debt", "transfer", "close", "review"]

SOURCES = ["email", "sms", "letter"]          # no voice, by decision

# ---------------------------------------------------------------- fields

# key -> (python type, allowed values or None, human meaning)
FIELDS = {
    "cat":  (str,   CATEGORIES,   "category"),
    "inst": (str,   None,         "institution"),
    "ref":  (str,   None,         "account or policy reference"),
    "amt":  (float, None,         "amount printed on the document"),
    "kind": (str,   AMOUNT_KINDS, "what the amount represents"),
    "rec":  (str,   RECURRENCE,   "recurrence"),
    "due":  (int,   None,         "days to act, if stated"),
    "act":  (str,   ACTIONS,      "what the family should do"),
    "ev":   (list,  None,         "supporting input line numbers"),
}
KEY_ORDER = list(FIELDS)                       # deterministic serialisation
REQUIRED = ["cat"]                             # everything else may be absent
CRITICAL_FIELDS = ["amt", "ref", "due"]        # missing these costs families money

# ---------------------------------------------------------------- input format

def number_lines(text: str) -> str:
    """Prefix each line with its number so the model can cite evidence by line."""
    lines = text.splitlines() or [""]
    return "\n".join(f"{i}| {ln}" for i, ln in enumerate(lines, start=1))


def line_count(text: str) -> int:
    return max(1, len(text.splitlines()))


SYSTEM_PROMPT = (
    "You read one document from a deceased person's records and return ONE compact "
    "JSON object, nothing else.\n"
    "Keys (omit any that are absent): "
    "cat=category, inst=institution, ref=account/policy reference (last 4 or id), "
    "amt=amount as a number, kind=what the amount is, rec=recurrence, "
    "due=days to act if stated, act=recommended action, ev=list of supporting line numbers.\n"
    f"cat is one of: {', '.join(CATEGORIES)}.\n"
    f"kind is one of: {', '.join(AMOUNT_KINDS)}.\n"
    f"rec is one of: {', '.join(RECURRENCE)}.\n"
    f"act is one of: {', '.join(ACTIONS)}.\n"
    "For irrelevant or personal documents return only cat."
)

# ---------------------------------------------------------------- serialisation

def to_target(obj: dict) -> str:
    """Canonical compact JSON: fixed key order, nulls dropped, no spaces."""
    clean = {}
    for k in KEY_ORDER:
        v = obj.get(k)
        if v is None or v == [] or v == "":
            continue
        if k == "amt":
            v = round(float(v), 2)
            v = int(v) if v == int(v) else v
        if k == "ev":
            v = sorted({int(x) for x in v})
        clean[k] = v
    return json.dumps(clean, separators=(",", ":"), ensure_ascii=False)


def parse_output(text: str) -> dict | None:
    """Pull the first JSON object out of model output. None if unparseable."""
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return None
    try:
        obj = json.loads(m.group(0))
    except json.JSONDecodeError:
        return None
    return obj if isinstance(obj, dict) else None

# ---------------------------------------------------------------- validation

def validate(obj: dict | None, n_lines: int | None = None) -> list[str]:
    """Return a list of problems. Empty list means schema-valid."""
    if obj is None:
        return ["unparseable"]
    errs = []
    for k in REQUIRED:
        if k not in obj:
            errs.append(f"missing required '{k}'")
    for k, v in obj.items():
        if k not in FIELDS:
            errs.append(f"unknown key '{k}'")
            continue
        typ, allowed, _ = FIELDS[k]
        if typ is float:
            if not isinstance(v, (int, float)) or isinstance(v, bool):
                errs.append(f"'{k}' not a number")
        elif typ is int:
            if not isinstance(v, int) or isinstance(v, bool):
                errs.append(f"'{k}' not an integer")
        elif typ is list:
            if not isinstance(v, list) or not all(isinstance(x, int) for x in v):
                errs.append(f"'{k}' not a list of ints")
            elif n_lines is not None and any(x < 1 or x > n_lines for x in v):
                errs.append(f"'{k}' cites a line outside 1..{n_lines}")
        elif not isinstance(v, typ):
            errs.append(f"'{k}' wrong type")
        if allowed is not None and isinstance(v, str) and v not in allowed:
            errs.append(f"'{k}'={v!r} not an allowed value")
    return errs

# ---------------------------------------------------------------- derived fields (code, not model)

# Documented assumptions. Every number here is a policy choice we can explain.
MONTHS_PER = {"none": None, "monthly": 12, "quarterly": 4, "annual": 1}
PENSION_EXPOSURE_MONTHS = 6   # overpaid benefits typically discovered within ~6 months


def money_at_stake(f: dict) -> float:
    """The family's real financial exposure, which is often NOT the printed amount."""
    amt, kind, rec, act = f.get("amt"), f.get("kind"), f.get("rec", "none"), f.get("act")
    if amt is None:
        return 0.0
    amt = float(amt)
    if kind == "charge":                       # a subscription keeps charging
        per_year = MONTHS_PER.get(rec)
        return round(amt * per_year, 2) if per_year else amt
    if kind == "benefit" and act == "stop_payment":
        n = PENSION_EXPOSURE_MONTHS if rec == "monthly" else 1
        return round(amt * n, 2)               # money that must be paid back
    if kind == "face_value":
        return amt if act == "claim" else 0.0  # not claimable as stated -> 0
    return amt                                 # balance / due / benefit


def deadline_date(f: dict, reference: dt.date) -> dt.date | None:
    """Convert 'due in N days' into a calendar date from a reference date."""
    return reference + dt.timedelta(days=f["due"]) if f.get("due") is not None else None


def priority(f: dict) -> tuple:
    """Sort key: stated deadlines first (soonest first), then largest exposure."""
    due = f.get("due")
    return (0 if due is not None else 1, due if due is not None else 0, -money_at_stake(f))


def enrich(f: dict, reference: dt.date | None = None) -> dict:
    """Model output + code-computed fields, ready for the UI."""
    out = dict(f)
    out["money_at_stake"] = money_at_stake(f)
    out["triage"] = TRIAGE_OF.get(f.get("cat"), "extract")
    if reference is not None:
        d = deadline_date(f, reference)
        out["deadline_date"] = d.isoformat() if d else None
    return out

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
import math
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
    """Sort key for one finding: highest priority_score first, then largest exposure.
    Same order as rank(); see assess() for how the score is built."""
    return (-assess(f)["priority_score"], -money_at_stake(f))


def enrich(f: dict, reference: dt.date | None = None, evidence_text: str = "",
           as_of: dt.date | None = None, provisional: bool = False) -> dict:
    """Model output + code-computed fields, ready for the UI."""
    out = dict(f)
    out["money_at_stake"] = money_at_stake(f)
    out["triage"] = TRIAGE_OF.get(f.get("cat"), "extract")
    if reference is not None:
        d = deadline_date(f, reference)
        out["deadline_date"] = d.isoformat() if d else None
    out.update(assess(f, reference, evidence_text, as_of, provisional))
    return out

# ---------------------------------------------------------------- tags and ranking (code, not model)
#
# The model reads facts; these rules turn facts into tags and a 0-100 priority score.
# Zero extra tokens, identical output on every run, and every point has a written reason.
# The weights are policy choices, documented here, not learned. Change them here only.

URGENCY_POINTS = [(0, 40, "overdue"), (7, 35, "due within 7 days"),
                  (30, 25, "due within 30 days"), (90, 10, "due within 90 days")]
MONEY_POINTS_MAX = 30          # log-scaled: $100 ~ 12 pts, $10k ~ 24, $100k+ = 30
MONEY_POINTS_CAP = 100_000
DRAIN_POINTS = 12              # money keeps leaving every period until someone acts
CLAWBACK_POINTS = 10           # payments after death must be paid back
ACCOUNT_POINTS = 8             # an account number makes the task actionable today
TIERS = [(60, "P1"), (35, "P2"), (0, "P3")]

TAG_LABELS = {
    "account_identified": "Account number found",
    "funds_to_claim":     "Funds the family can claim",
    "recurring_drain":    "Recurring charge still running",
    "scheduled_payment":  "Scheduled payment / EMI",
    "clawback_risk":      "Payments after death may be clawed back",
    "debt_to_verify":     "Debt to verify before paying",
    "deadline":           "Has a deadline",
    "deadline_soon":      "Deadline within 30 days",
    "overdue":            "Deadline has passed",
    "high_value":         "Over $10,000 at stake",
    "official":           "Court or government",
    "provisional":        "Some facts not confirmed in the document",
    "memory":             "Personal - kept in Memories",
    "ignore":             "Not relevant - hidden",
}

_MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}
_DATE_PATTERNS = [
    (re.compile(r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b"), ("y", "m", "d")),
    (re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b"), ("m", "d", "y")),            # US style
    (re.compile(r"\b([A-Za-z]{3,9})\.? (\d{1,2})(?:st|nd|rd|th)?,? (\d{4})\b"), ("mon", "d", "y")),
    (re.compile(r"\b(\d{1,2})(?:st|nd|rd|th)? ([A-Za-z]{3,9})\.?,? (\d{4})\b"), ("d", "mon", "y")),
]


def dates_in(text: str) -> list[dt.date]:
    """Calendar dates printed in text. Read by code from the lines the model cited."""
    found = []
    for rx, order in _DATE_PATTERNS:
        for m in rx.finditer(text):
            parts = dict(zip(order, m.groups()))
            try:
                month = _MONTHS[parts["mon"][:3].lower()] if "mon" in parts else int(parts["m"])
                found.append(dt.date(int(parts["y"]), month, int(parts["d"])))
            except (KeyError, ValueError):
                continue
    return sorted(set(found))


def next_date(evidence_text: str, as_of: dt.date) -> dt.date | None:
    """Earliest printed date on the cited lines that is today or later."""
    upcoming = [d for d in dates_in(evidence_text) if d >= as_of]
    return upcoming[0] if upcoming else None


_URL = re.compile(r"\b(?:https?://|www\.)[^\s<>\"')\]]+", re.I)
_BARE_DOMAIN = re.compile(r"\b[a-z0-9][a-z0-9-]{1,62}\.(?:com|org|net|gov|edu|us|co|io|info|bank)(?:/[^\s<>\"')\]]*)?\b", re.I)
_EMAIL = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.I)
_PHONE = re.compile(r"(?<!\d)(?:\+?1[\s.-]?)?\(?\d{3}\)?[\s.-]\d{3}[\s.-]\d{4}(?!\d)")


def contacts_in(text: str) -> dict:
    """Where the family can act: web links, email addresses and phone numbers printed in the
    document. Read by code from the full text, not generated by the model (zero tokens)."""
    emails = list(dict.fromkeys(m.group(0).rstrip(".") for m in _EMAIL.finditer(text)))
    email_domains = {e.split("@", 1)[1].lower() for e in emails}
    urls = [m.group(0).rstrip(".,;:") for m in _URL.finditer(text)]
    covered = " ".join(urls).lower()
    for m in _BARE_DOMAIN.finditer(text):
        d = m.group(0).rstrip(".,;:")
        if d.lower() not in covered and d.lower() not in email_domains \
                and not text[max(0, m.start() - 1):m.start()] in ("@", "."):
            urls.append(d)
    phones = list(dict.fromkeys(re.sub(r"\s+", " ", m.group(0)).strip() for m in _PHONE.finditer(text)))
    return {"urls": list(dict.fromkeys(urls))[:5], "emails": emails[:5], "phones": phones[:5]}


def account_key(f: dict) -> str | None:
    """Same institution + same reference ending = same account, across documents."""
    inst, ref = f.get("inst"), f.get("ref")
    if not inst or not ref:
        return None
    ending = re.sub(r"[^0-9A-Za-z]", "", str(ref))[-4:]
    return f"{re.sub(r'[^0-9a-z]', '', inst.casefold())}:{ending.casefold()}" if ending else None


def assess(f: dict, reference: dt.date | None = None, evidence_text: str = "",
           as_of: dt.date | None = None, provisional: bool = False) -> dict:
    """Tags, 0-100 priority score, P1/P2/P3 tier and the reasons behind every point."""
    route = TRIAGE_OF.get(f.get("cat"), "extract")
    if route != "extract":
        tag = "memory" if route == "memory" else "ignore"
        return {"tags": [tag], "priority_score": 0, "priority": "P3",
                "priority_reasons": [TAG_LABELS[tag]], "account_key": None, "next_date": None}

    as_of = as_of or dt.date.today()
    kind, act, rec = f.get("kind"), f.get("act"), f.get("rec", "none")
    stake = money_at_stake(f)
    tags, reasons, score = [], [], 0

    # When must something happen? A stated "within N days" (from the date of death)
    # or a printed date on the cited lines (e.g. the next EMI), whichever is sooner.
    when = []
    if f.get("due") is not None:               # "within N days" of the date of death,
        when.append(deadline_date(f, reference or as_of))   # or of today if not entered
    nd = next_date(evidence_text, as_of) if evidence_text else None
    if nd:
        when.append(nd)
    if f.get("due") is not None or nd:
        tags.append("deadline")
    if when:
        days = (min(when) - as_of).days
        for limit, pts, why in URGENCY_POINTS:
            if days <= limit:
                score += pts; reasons.append(f"+{pts} {why} ({min(when).isoformat()})")
                tags.append("overdue" if days < 0 else "deadline_soon" if days <= 30 else "deadline")
                break

    if stake > 0:
        pts = round(MONEY_POINTS_MAX * min(1.0, math.log10(1 + stake) / math.log10(1 + MONEY_POINTS_CAP)))
        score += pts; reasons.append(f"+{pts} ${stake:,.2f} at stake")
        if stake >= 10_000:
            tags.append("high_value")

    if kind == "charge" and MONTHS_PER.get(rec):
        score += DRAIN_POINTS; tags.append("recurring_drain")
        reasons.append(f"+{DRAIN_POINTS} {rec} charge keeps running until cancelled")
    if kind == "due" and MONTHS_PER.get(rec):
        score += DRAIN_POINTS; tags.append("scheduled_payment")
        reasons.append(f"+{DRAIN_POINTS} {rec} payment scheduled")
    if kind == "benefit" and act == "stop_payment":
        score += CLAWBACK_POINTS; tags.append("clawback_risk")
        reasons.append(f"+{CLAWBACK_POINTS} benefit paid after death must be returned")
    if act == "claim" and stake > 0:
        tags.append("funds_to_claim")
    if act == "verify_debt":
        tags.append("debt_to_verify")
    if f.get("ref"):
        score += ACCOUNT_POINTS; tags.append("account_identified")
        reasons.append(f"+{ACCOUNT_POINTS} account reference found - actionable now")
    if f.get("cat") in ("government", "legal"):
        tags.append("official")
    if provisional:
        tags.append("provisional")

    score = min(100, score)
    tier = next(t for cut, t in TIERS if score >= cut)
    return {"tags": list(dict.fromkeys(tags)), "priority_score": score, "priority": tier,
            "priority_reasons": reasons, "account_key": account_key(f),
            "next_date": nd.isoformat() if nd else None}


def rank(results: list[dict]) -> list[dict]:
    """Order contract results for the action plan and merge documents about one account.

    Highest priority_score first; ties broken by money at stake. Documents that share an
    account_key collapse into the highest-scoring one, which lists the others in
    `related_ids`. Non-extract routes keep rank None."""
    items = [r for r in results if r.get("route") == "extract" and r.get("finding")]
    items.sort(key=lambda r: (-r["finding"]["priority_score"], -r["finding"]["money_at_stake"]))
    seen, n = {}, 0
    for r in items:
        key = r["finding"].get("account_key")
        if key and key in seen:
            lead = seen[key]
            lead["finding"].setdefault("related_ids", []).append(r.get("id"))
            r["finding"]["rank"], r["finding"]["merged_into"] = None, lead.get("id")
            continue
        n += 1
        r["finding"]["rank"] = n
        if key:
            seen[key] = r
    for r in results:
        if r.get("finding") is not None:
            r["finding"].setdefault("rank", None)
    return results

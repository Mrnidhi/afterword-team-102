"""Afterword evaluation metrics.

The Metrics deliverable asks for metrics "including how and why they were chosen".
The why is written next to each function. The headline numbers are:

  field F1            standard for key-information extraction; partial credit per field
  critical recall     amt / ref / due - the fields that cost a family money when missed
  schema validity     unusable output is worse than a wrong answer
  grounding rate      extracted values actually appear on the lines the model cited
  output tokens       the cost driver on bandwidth-bound hardware (measured elsewhere, averaged here)
"""
from __future__ import annotations

import re
from collections import Counter, defaultdict

from schema import FIELDS, CRITICAL_FIELDS, validate

SCORED_FIELDS = [k for k in FIELDS if k != "ev"]   # evidence is scored separately
CHECKABLE_FOR_GROUNDING = ["amt", "ref", "inst", "due"]

# ---------------------------------------------------------------- normalisation

def _norm_text(s) -> str:
    s = str(s).casefold()
    s = re.sub(r"[^\w\s]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _norm_ref(s) -> str:
    return re.sub(r"[^0-9a-z]", "", str(s).casefold())


def normalise(key: str, v):
    """Canonical form used for comparison. Choices are deliberately strict."""
    if v is None:
        return None
    if key == "amt":
        try:
            return round(float(v), 2)
        except (TypeError, ValueError):
            return str(v)
    if key == "due":
        try:
            return int(v)
        except (TypeError, ValueError):
            return str(v)
    if key == "ref":
        return _norm_ref(v)
    if key == "inst":
        return _norm_text(v)
    return str(v).strip().casefold()           # enums


def same(key: str, pred, gold) -> bool:
    return normalise(key, pred) == normalise(key, gold)

# ---------------------------------------------------------------- numbers inside text

_NUM = re.compile(r"\d[\d.,]*\d|\d")


def numbers_in(text: str) -> list[float]:
    """Parse every number in text, tolerating 1,234.56 and 1.234,56 styles."""
    out = []
    for tok in _NUM.findall(text):
        cands = {tok.replace(",", ""), tok.replace(".", "").replace(",", ".")}
        for c in cands:
            try:
                out.append(round(float(c), 2))
            except ValueError:
                pass
    return out

# ---------------------------------------------------------------- per-document scoring

def score_document(pred: dict | None, gold: dict, source_text: str | None = None) -> dict:
    """Counts for one document. Wrong value = one FP and one FN (standard KIE convention)."""
    tp = fp = fn = 0
    per_field = defaultdict(lambda: Counter())
    lines = source_text.splitlines() if source_text is not None else None
    valid = not validate(pred, len(lines) if lines is not None else None)

    for k in SCORED_FIELDS:
        g = gold.get(k)
        p = pred.get(k) if pred else None
        if g is None and p is None:
            continue
        if g is not None and p is not None and same(k, p, g):
            tp += 1; per_field[k]["tp"] += 1
        else:
            if p is not None:
                fp += 1; per_field[k]["fp"] += 1
            if g is not None:
                fn += 1; per_field[k]["fn"] += 1

    # Evidence: did the model cite the lines a human would?
    gev, pev = set(gold.get("ev") or []), set((pred or {}).get("ev") or [])
    ev_recall = (len(gev & pev) / len(gev)) if gev else None

    # Grounding: is each extracted value physically present on the cited lines?
    grounded = checked = 0
    if pred and lines is not None:
        cited = "\n".join(lines[i - 1] for i in pev if 1 <= i <= len(lines))
        for k in CHECKABLE_FOR_GROUNDING:
            if k not in pred:
                continue
            checked += 1
            if not cited:
                continue
            if k in ("amt", "due"):
                ok = normalise("amt", pred[k]) in numbers_in(cited)
            elif k == "ref":
                ok = _norm_ref(pred[k]) != "" and _norm_ref(pred[k]) in _norm_ref(cited)
            else:
                ok = _norm_text(pred[k]) != "" and _norm_text(pred[k]) in _norm_text(cited)
            grounded += int(ok)

    exact = pred is not None and fp == 0 and fn == 0
    return dict(tp=tp, fp=fp, fn=fn, valid=valid, exact=exact, per_field=per_field,
                ev_recall=ev_recall, grounded=grounded, checked=checked)


def _prf(tp, fp, fn):
    p = tp / (tp + fp) if tp + fp else 0.0
    r = tp / (tp + fn) if tp + fn else 0.0
    f = 2 * p * r / (p + r) if p + r else 0.0
    return p, r, f

# ---------------------------------------------------------------- aggregate report

def evaluate(preds: list, golds: list, sources: list | None = None,
             categories: list | None = None, output_tokens: list | None = None) -> dict:
    """Micro-averaged report over a whole test set."""
    assert len(preds) == len(golds)
    sources = sources or [None] * len(golds)
    categories = categories or [g.get("cat", "?") for g in golds]

    T = F = N = valid = exact = 0
    grounded = checked = 0
    ev_scores = []
    field_tot = defaultdict(Counter)
    cat_tot = defaultdict(Counter)

    for pred, gold, src, cat in zip(preds, golds, sources, categories):
        s = score_document(pred, gold, src)
        T += s["tp"]; F += s["fp"]; N += s["fn"]
        valid += s["valid"]; exact += s["exact"]
        grounded += s["grounded"]; checked += s["checked"]
        if s["ev_recall"] is not None:
            ev_scores.append(s["ev_recall"])
        for k, c in s["per_field"].items():
            field_tot[k].update(c)
        cat_tot[cat].update(tp=s["tp"], fp=s["fp"], fn=s["fn"])

    p, r, f = _prf(T, F, N)
    crit_tp = sum(field_tot[k]["tp"] for k in CRITICAL_FIELDS)
    crit_gold = sum(field_tot[k]["tp"] + field_tot[k]["fn"] for k in CRITICAL_FIELDS)
    n = len(golds)

    report = {
        "documents": n,
        "field_precision": p, "field_recall": r, "field_f1": f,
        "critical_recall": crit_tp / crit_gold if crit_gold else None,
        "schema_validity": valid / n if n else 0.0,
        "exact_match": exact / n if n else 0.0,
        "grounding_rate": grounded / checked if checked else None,
        "evidence_recall": sum(ev_scores) / len(ev_scores) if ev_scores else None,
        "per_field_f1": {k: _prf(c["tp"], c["fp"], c["fn"])[2] for k, c in sorted(field_tot.items())},
        "per_category_f1": {k: _prf(c["tp"], c["fp"], c["fn"])[2] for k, c in sorted(cat_tot.items())},
    }
    if output_tokens:
        report["mean_output_tokens"] = sum(output_tokens) / len(output_tokens)
    return report

# ---------------------------------------------------------------- native schemas (CORD, invoices)

def flatten(obj, prefix="") -> list[tuple[str, str]]:
    """Nested JSON -> (path, value) pairs. List positions are dropped so item order
    does not matter; this mirrors the field-level F1 commonly used for CORD."""
    out = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            out += flatten(v, f"{prefix}.{k}" if prefix else k)
    elif isinstance(obj, list):
        for v in obj:
            out += flatten(v, prefix)
    elif obj is not None and str(obj).strip() != "":
        out.append((prefix, _norm_text(obj)))
    return out


def flat_f1(preds: list, golds: list) -> dict:
    """Multiset F1 over flattened (path, value) pairs. For benchmark datasets."""
    T = F = N = valid = 0
    for p, g in zip(preds, golds):
        gp = Counter(flatten(g))
        if p is None:
            N += sum(gp.values()); continue
        valid += 1
        pp = Counter(flatten(p))
        tp = sum((gp & pp).values())
        T += tp; F += sum(pp.values()) - tp; N += sum(gp.values()) - tp
    pr, rc, f1 = _prf(T, F, N)
    return {"documents": len(golds), "field_precision": pr, "field_recall": rc,
            "field_f1": f1, "parse_rate": valid / len(golds) if golds else 0.0}


def format_report(rep: dict, title: str = "") -> str:
    """Human-readable block for logs and the notebook."""
    def pct(x):
        return "  n/a" if x is None else f"{x:6.1%}"
    lines = [f"=== {title} ===" if title else "", f"documents         {rep['documents']}"]
    for k in ["field_f1", "field_precision", "field_recall", "critical_recall",
              "schema_validity", "exact_match", "grounding_rate", "evidence_recall",
              "parse_rate"]:
        if k in rep:
            lines.append(f"{k:<18}{pct(rep[k])}")
    if "mean_output_tokens" in rep:
        lines.append(f"{'mean_output_tokens':<18}{rep['mean_output_tokens']:6.1f}")
    for block in ["per_field_f1", "per_category_f1"]:
        if rep.get(block):
            lines.append(f"-- {block} (worst first)")
            for k, v in sorted(rep[block].items(), key=lambda kv: kv[1]):
                lines.append(f"   {k:<16}{pct(v)}")
    return "\n".join(l for l in lines if l != "")

"""Afterword extraction engine — the ONE function the backend calls.

    from engine import extract
    result = extract(text, source="email", doc_id="mail-0042")

Talks to any OpenAI-compatible server. Today that is the team's model server on :8000
running the BASE Qwen3-4B. When training finishes, the same port serves the fine-tuned
model and nothing in the backend or UI changes - only accuracy improves.

The return shape is a fixed contract (CONTRACT below). Build the backend and UI against it now.
"""
from __future__ import annotations

import datetime as dt
import math
import os
import time

import requests

import schema as S
from metrics import _norm_ref, _norm_text, normalise, numbers_in

CONTRACT = "afterword.finding/v1"
ENGINE_VERSION = "0.3"   # 0.2: clean-up, confidence gate, tags + rank; 0.3: contacts from the document
LLM_URL = os.environ.get("AFTERWORD_LLM_URL", "http://127.0.0.1:8000/v1")


def _grounding(pred: dict, lines: list[str]) -> dict:
    """For each checkable field: does the value really appear on the lines the model cited?"""
    cited = "\n".join(lines[i - 1] for i in pred.get("ev", []) if 1 <= i <= len(lines))
    out = {}
    for k in ("amt", "ref", "inst", "due"):
        if k not in pred:
            continue
        if not cited:
            out[k] = False
        elif k in ("amt", "due"):                  # a stated number must literally be there
            out[k] = normalise("amt", pred[k]) in numbers_in(cited)
        elif k == "ref":
            out[k] = bool(_norm_ref(pred[k])) and _norm_ref(pred[k]) in _norm_ref(cited)
        else:
            out[k] = bool(_norm_text(pred[k])) and _norm_text(pred[k]) in _norm_text(cited)
    return out


# ---------------------------------------------------------------- L1 clean-up (code, not model)

def clean_finding(pred: dict | None, text: str) -> dict | None:
    """Drop values the document does not contain. Never mutates the input; no gold labels used.
    Amounts and day counts must be printed numbers (catches `amt: 0` invented for a document
    that states none; kind/rec go with a dropped amount); a reference must be printed."""
    if not isinstance(pred, dict):
        return pred
    out, nums, rtext = dict(pred), numbers_in(text), _norm_ref(text)
    if "amt" in out and normalise("amt", out["amt"]) not in nums:
        for k in ("amt", "kind", "rec"):
            out.pop(k, None)
    if "due" in out and normalise("amt", out["due"]) not in nums:
        out.pop("due")
    if "ref" in out and (not _norm_ref(out["ref"]) or _norm_ref(out["ref"]) not in rtext):
        out.pop("ref")
    return out

# ---------------------------------------------------------------- L2 confidence gate

# Per-field thresholds on the LOWEST token probability inside the field's value. Fitted on
# data/estate/cal.jsonl (264 docs, never trained or tested on) for the sft3 model so that the
# finite-sample-corrected error among accepted values is <= 5%: (errors+1)/(accepted+1) <= 0.05.
# Reproduce: python cascade.py (results/cascade_verify.json). Re-fit if the served model changes.
GATE_MODEL = "sft3"
GATE_THRESHOLDS = {"cat": 0.9812, "inst": 0.851, "ref": 0.9241, "amt": 0.9914, "kind": 0.9933,
                   "rec": 0.924, "due": 0.9999, "act": 0.9466}


def field_confidence(raw: str, tokens: list[dict]) -> dict:
    """{field: lowest token probability inside its value}, located by character offsets."""
    spans, pos = [], 0
    for t in tokens:
        spans.append((pos, pos + len(t["t"]), t["lp"])); pos += len(t["t"])
    out = {}
    for k in GATE_THRESHOLDS:
        i = raw.find(f'"{k}":')
        if i < 0:
            continue
        a = b = i + len(k) + 3
        depth = 0
        while b < len(raw) and not (depth == 0 and raw[b] in ",}"):
            depth += raw[b] == "["; depth -= raw[b] == "]"; b += 1
        lps = [lp for s, e, lp in spans if s < b and e > a]
        if lps:
            out[k] = round(math.exp(min(lps)), 4)
    return out


def extract(text: str, source: str = "email", doc_id: str | None = None,
            reference_date: dt.date | None = None, llm_url: str | None = None,
            timeout: float = 120, as_of: dt.date | None = None) -> dict:
    """One document in, one contract-shaped result out. Never raises on model errors."""
    lines = text.splitlines() or [""]
    url = (llm_url or LLM_URL).rstrip("/")
    t0 = time.perf_counter()
    raw, usage, model = "", {}, None
    try:
        r = requests.post(f"{url}/chat/completions", timeout=timeout, json={
            "messages": [{"role": "system", "content": S.SYSTEM_PROMPT},
                         {"role": "user", "content": S.number_lines(text)}],
            "temperature": 0, "max_tokens": 200, "logprobs": True, "top_logprobs": 1})
        r.raise_for_status()
        j = r.json()
        ch = j["choices"][0]
        raw, usage, model = ch["message"]["content"], j.get("usage", {}), j.get("model")
        tokens = [{"t": c["token"], "lp": c["logprob"]} for c in (ch.get("logprobs") or {}).get("content") or []]
    except Exception as e:                                    # model down / timeout
        return _result(doc_id, source, "failed", None, [], {"error": f"{type(e).__name__}: {e}"},
                       model, t0, usage, raw)

    parsed = S.parse_output(raw)
    errors = S.validate(parsed, len(lines))       # judged on the model's own output, before clean-up
    pred = clean_finding(parsed, text)
    if pred is None:
        return _result(doc_id, source, "failed", None, [], {"schema_errors": errors}, model, t0, usage, raw)

    grounded = _grounding(parsed, lines)          # what the model claimed, so inventions stay visible
    removed = [k for k in parsed if k not in pred]    # values clean-up took out of the finding
    route = S.TRIAGE_OF.get(pred.get("cat"), "extract")
    # The gate runs only when the server returned token probabilities (vLLM does; stand-ins may not).
    confidence = field_confidence(raw, tokens) if tokens else {}
    uncertain = [k for k, p in confidence.items() if k in pred and p < GATE_THRESHOLDS[k]]
    ok = not errors and all(grounded.values()) and not uncertain
    status = "accepted" if ok or route != "extract" else "needs_review"
    evidence = [{"line": i, "text": lines[i - 1]} for i in pred.get("ev", []) if 1 <= i <= len(lines)]
    finding = S.enrich(pred, reference_date, evidence_text="\n".join(e["text"] for e in evidence),
                       as_of=as_of, provisional=status == "needs_review")
    if route == "extract":
        finding["contacts"] = S.contacts_in(text)
    return _result(doc_id, source, status, finding, evidence,
                   {"schema_errors": errors, "grounded": grounded, "removed_ungrounded": removed,
                    "confidence": confidence,
                    "uncertain": uncertain, "gate": "on" if confidence else "off (no token probabilities)"},
                   model, t0, usage, raw)


def _result(doc_id, source, status, finding, evidence, checks, model, t0, usage, raw):
    return {
        "contract": CONTRACT,
        "id": doc_id,
        "source": source,                 # email | sms | letter
        "status": status,                 # accepted | needs_review | failed
        "route": (finding or {}).get("triage"),   # drop | memory | extract
        "finding": finding,               # model fields + money_at_stake, triage, deadline_date
        "evidence": evidence,             # [{line, text}] - highlight these in the Evidence view
        "checks": checks,                 # schema errors + per-field grounding
        "meta": {"engine": ENGINE_VERSION, "model": model, "tier": "L1",
                 "latency_ms": round((time.perf_counter() - t0) * 1000),
                 "output_tokens": usage.get("completion_tokens"),
                 "raw": raw if status != "accepted" else None},
    }


def extract_many(items: list[dict], **kw) -> list[dict]:
    """items: [{"id", "text", "source"}]. Sequential - the model server handles one at a time.
    Returns every result with finding.rank set (1 = most urgent); see schema.rank()."""
    return S.rank([extract(it["text"], it.get("source", "email"), it.get("id"), **kw) for it in items])


if __name__ == "__main__":
    import json, sys
    print(json.dumps(extract(sys.stdin.read(), source=sys.argv[1] if len(sys.argv) > 1 else "email"),
                     indent=2, ensure_ascii=False))

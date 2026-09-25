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
import os
import time

import requests

import schema as S
from metrics import _norm_ref, _norm_text, normalise, numbers_in

CONTRACT = "afterword.finding/v1"
ENGINE_VERSION = "0.1"
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


def extract(text: str, source: str = "email", doc_id: str | None = None,
            reference_date: dt.date | None = None, llm_url: str | None = None,
            timeout: float = 120) -> dict:
    """One document in, one contract-shaped result out. Never raises on model errors."""
    lines = text.splitlines() or [""]
    url = (llm_url or LLM_URL).rstrip("/")
    t0 = time.perf_counter()
    raw, usage, model = "", {}, None
    try:
        r = requests.post(f"{url}/chat/completions", timeout=timeout, json={
            "messages": [{"role": "system", "content": S.SYSTEM_PROMPT},
                         {"role": "user", "content": S.number_lines(text)}],
            "temperature": 0, "max_tokens": 200})
        r.raise_for_status()
        j = r.json()
        raw, usage, model = j["choices"][0]["message"]["content"], j.get("usage", {}), j.get("model")
    except Exception as e:                                    # model down / timeout
        return _result(doc_id, source, "failed", None, [], {"error": f"{type(e).__name__}: {e}"},
                       model, t0, usage, raw)

    pred = S.parse_output(raw)
    errors = S.validate(pred, len(lines))
    if pred is None:
        return _result(doc_id, source, "failed", None, [], {"schema_errors": errors}, model, t0, usage, raw)

    grounded = _grounding(pred, lines)
    route = S.TRIAGE_OF.get(pred.get("cat"), "extract")
    ok = not errors and all(grounded.values())
    status = "accepted" if ok or route != "extract" else "needs_review"
    evidence = [{"line": i, "text": lines[i - 1]} for i in pred.get("ev", []) if 1 <= i <= len(lines)]
    finding = S.enrich(pred, reference_date)
    return _result(doc_id, source, status, finding, evidence,
                   {"schema_errors": errors, "grounded": grounded}, model, t0, usage, raw)


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
    """items: [{"id", "text", "source"}]. Sequential - the model server handles one at a time."""
    return [extract(it["text"], it.get("source", "email"), it.get("id"), **kw) for it in items]


if __name__ == "__main__":
    import json, sys
    print(json.dumps(extract(sys.stdin.read(), source=sys.argv[1] if len(sys.argv) > 1 else "email"),
                     indent=2, ensure_ascii=False))

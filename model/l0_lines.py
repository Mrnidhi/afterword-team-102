"""L0 line selection: send the 4B only the lines that can carry a fact.

Lines keep their ORIGINAL numbers ("7| ..."), so evidence citations still point at the
stored document and the evidence view lines up. The model was trained on whole documents,
so whether it still extracts correctly from a gapped document is measured, not assumed:

    python l0_lines.py                  # offline: lines kept, gold evidence lines kept
    python l0_lines.py --live           # + re-run sft3 on :8091 with selected lines, score vs full input
Writes results/l0_lines.json.
"""
from __future__ import annotations

import argparse
import json
import re
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import requests

import metrics as M
import schema as S
from evaluate import load, unnumber
from postprocess import clean

HERE = Path(__file__).resolve().parent
HEAD_LINES = 3            # subject / sender / greeting usually name the institution
_FACT = re.compile(
    r"\d|\$|€|£|"
    r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\b|"
    r"\b(account|acct|policy|member|loan|claim|balance|due|payment|pymt|benefit|pension|premium|"
    r"estate|deceased|death|passed|cancel|renew|subscription|refund|owed|debt|invoice|bill|"
    r"insurance|bank|fund|trust|court|probate|office|department|hospital|clinic|services?|"
    r"association|authority|company|co\.|inc\.?|llc|llp|ltd)\b", re.I)


def select(text: str) -> tuple[str, list[int]]:
    """Numbered text of the kept lines (original numbering) and the kept line numbers."""
    lines = text.splitlines() or [""]
    keep = [i for i, l in enumerate(lines, 1) if i <= HEAD_LINES or _FACT.search(l)]
    return "\n".join(f"{i}| {lines[i - 1]}" for i in keep), keep


def offline(rows):
    kept = total = ev_hit = ev_all = chars_kept = chars_all = 0
    for r in rows:
        src = unnumber(r["input"])
        sel, keep = select(src)
        kept += len(keep); total += len(src.splitlines())
        chars_kept += len(sel); chars_all += len(r["input"])
        ev = set(r["label"].get("ev") or [])
        ev_hit += len(ev & set(keep)); ev_all += len(ev)
    return {"lines_kept_share": round(kept / total, 4), "prompt_chars_kept_share": round(chars_kept / chars_all, 4),
            "gold_evidence_lines_kept": round(ev_hit / ev_all, 4) if ev_all else None}


def _call(ep, model, rec, user):
    r = requests.post(f"{ep}/chat/completions", timeout=300, json={
        "model": model, "temperature": 0, "max_tokens": 200,
        "messages": [{"role": "system", "content": rec["system"]}, {"role": "user", "content": user}]})
    r.raise_for_status()
    j = r.json()
    return j["choices"][0]["message"]["content"], j["usage"]["prompt_tokens"], j["usage"]["completion_tokens"]


def live(rows, ep):
    model = requests.get(f"{ep}/models", timeout=10).json()["data"][0]["id"]
    res = {}
    for mode in ("full", "selected"):
        users = [r["input"] if mode == "full" else select(unnumber(r["input"]))[0] for r in rows]
        t0 = time.time()
        with ThreadPoolExecutor(64) as pool:
            outs = list(pool.map(lambda a: _call(ep, model, *a), zip(rows, users)))
        srcs = [unnumber(r["input"]) for r in rows]
        preds = [clean(S.parse_output(o[0]), s) for o, s in zip(outs, srcs)]
        rep = M.evaluate(preds, [r["label"] for r in rows], sources=srcs)
        res[mode] = {"field_f1": round(rep["field_f1"], 4), "critical_recall": round(rep["critical_recall"], 4),
                     "exact_match": round(rep["exact_match"], 4), "grounding_rate": round(rep["grounding_rate"], 4),
                     "prompt_tokens": sum(o[1] for o in outs), "output_tokens": sum(o[2] for o in outs),
                     "wall_s": round(time.time() - t0, 1)}
    f, s = res["full"], res["selected"]
    res["prompt_token_saving"] = round(1 - s["prompt_tokens"] / f["prompt_tokens"], 4)
    res["model"] = model
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--live", action="store_true")
    ap.add_argument("--endpoint", default="http://127.0.0.1:8091/v1")
    a = ap.parse_args()
    out = {}
    for name, task in (("estate test", "estate"), ("hard v1", "estate_hard"), ("hard v2 (fresh)", "estate_hard2")):
        rows = [r for r in load(task, "test") if S.TRIAGE_OF[r["label"]["cat"]] == "extract"]  # what L0 passes on
        out[name] = {"documents": len(rows), "offline": offline(rows)}
        if a.live:
            out[name]["live"] = live(rows, a.endpoint.rstrip("/"))
        print(f"\n[{name}] {len(rows)} extract docs | {out[name]['offline']}")
        if a.live:
            lv = out[name]["live"]
            for m in ("full", "selected"):
                print(f"  {m:9} F1 {lv[m]['field_f1']:.3f}  crit {lv[m]['critical_recall']:.3f}  "
                      f"exact {lv[m]['exact_match']:.3f}  prompt tok {lv[m]['prompt_tokens']:,}  out tok {lv[m]['output_tokens']:,}")
            print(f"  prompt tokens saved: {lv['prompt_token_saving']:.1%}")
    (HERE / "results" / "l0_lines.json").write_text(json.dumps(out, indent=1))
    print("\nsaved results/l0_lines.json")


if __name__ == "__main__":
    main()

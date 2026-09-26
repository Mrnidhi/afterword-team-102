"""Run a served model over a split and keep each output token's log-probability.

The L2 gate is calibrated on these: a per-field confidence = the lowest token
probability inside that field's value. Offline, so the gate can be fitted on CPU later.

    python collect_logprobs.py --name sft3 --task estate --split cal
    python collect_logprobs.py --name sft3 --task estate_hard2
Writes results/logprobs_<name>_<task>_<split>.jsonl  (one line per document)
"""
from __future__ import annotations

import argparse
import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests

from evaluate import MAX_TOKENS, load

HERE = Path(__file__).resolve().parent


def call(ep, model, rec):
    t0 = time.perf_counter()
    try:
        r = requests.post(f"{ep}/chat/completions", timeout=300, json={
            "model": model, "temperature": 0, "max_tokens": MAX_TOKENS[rec["task"]],
            "logprobs": True, "top_logprobs": 2,
            "messages": [{"role": "system", "content": rec["system"]},
                         {"role": "user", "content": rec["input"]}]})
        r.raise_for_status()
        j = r.json()
        ch = j["choices"][0]
        toks = [{"t": c["token"], "lp": round(c["logprob"], 5),
                 "alt": round(c["top_logprobs"][1]["logprob"], 5) if len(c.get("top_logprobs") or []) > 1 else None}
                for c in (ch.get("logprobs") or {}).get("content") or []]
        return {"id": rec["id"], "raw": ch["message"]["content"], "tokens": toks,
                "in_tok": j["usage"]["prompt_tokens"], "out_tok": j["usage"]["completion_tokens"],
                "ms": round((time.perf_counter() - t0) * 1000)}
    except Exception as e:
        return {"id": rec["id"], "error": f"{type(e).__name__}: {str(e)[:200]}"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", required=True, help="label for the output file, e.g. sft3")
    ap.add_argument("--endpoint", default="http://127.0.0.1:8091/v1")
    ap.add_argument("--task", default="estate")
    ap.add_argument("--split", default="test")
    ap.add_argument("--concurrency", type=int, default=64)
    ap.add_argument("--limit", type=int, default=0)
    a = ap.parse_args()
    ep = a.endpoint.rstrip("/")
    model = requests.get(f"{ep}/models", timeout=10).json()["data"][0]["id"]
    recs = load(a.task, a.split)
    recs = recs[: a.limit] if a.limit else recs
    out = HERE / "results" / f"logprobs_{a.name}_{a.task}_{a.split}.jsonl"
    t0, n_err = time.time(), 0
    with open(out, "w") as fh, ThreadPoolExecutor(a.concurrency) as pool:
        for f in as_completed([pool.submit(call, ep, model, r) for r in recs]):
            o = f.result(); n_err += "error" in o
            fh.write(json.dumps(o, ensure_ascii=False) + "\n")
    print(f"{model}: {len(recs)} docs, {n_err} errors, {time.time() - t0:.0f}s -> {out.name}", flush=True)


if __name__ == "__main__":
    main()

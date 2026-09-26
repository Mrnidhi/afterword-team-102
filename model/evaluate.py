"""Evaluate any model served behind an OpenAI-compatible endpoint (ZRT / vLLM).

The same code scores every model in the results table - base 4B, base 32B, fine-tuned 4B -
so the numbers are directly comparable.

    python evaluate.py --name base32b_0shot --endpoint http://127.0.0.1:8090/v1 --shots 0
    python evaluate.py --name base4b_0shot  --endpoint http://127.0.0.1:8090/v1 --shots 0

Writes results/<name>.json (report + every prediction, for error analysis and for Step 8).
Watch with: python monitor.py eval_<name>   Stop safely: python monitor.py eval_<name> --stop
"""
from __future__ import annotations

import argparse
import json
import random
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests

import metrics as M
import schema as S
from trainlog import RunLogger

HERE = Path(__file__).resolve().parent
RESULTS = HERE / "results"
MAX_TOKENS = {"estate": 200, "estate_hard": 200, "estate_hard2": 200, "invoice": 400, "cord": 900}
_NUM_PREFIX = re.compile(r"^\d+\| ", re.M)


def unnumber(numbered: str) -> str:
    """'3| text' -> 'text'. Grounding must not see our own line numbers as document numbers."""
    return _NUM_PREFIX.sub("", numbered)


def load(task: str, split: str) -> list[dict]:
    if task in ("estate_hard", "estate_hard2"):    # generalisation sets: one split only
        rows = [json.loads(l) for l in open(HERE / "data" / task / "test.jsonl")]
        for r in rows:
            r["task"] = task
        return rows
    if task == "estate":
        path = HERE / "data" / "estate" / f"{split}.jsonl"
        return [json.loads(l) for l in open(path)]
    path = HERE / "data" / "public" / f"{split}.jsonl"
    return [r for r in (json.loads(l) for l in open(path)) if r["task"] == task]


def pick_shots(task: str, k: int, seed: int = 0) -> list[dict]:
    """k short, diverse training examples (short keeps the prompt inside the context window)."""
    if k == 0:
        return []
    pool = load("estate" if task.startswith("estate_hard") else task, "train")
    pool.sort(key=lambda r: len(r["input"]) + len(r["target"]))
    pool = pool[: max(k * 20, 60)]
    rnd = random.Random(seed)
    if task in ("estate", "estate_hard", "estate_hard2"):                    # prefer different categories
        rnd.shuffle(pool)
        out, cats = [], set()
        for r in pool:
            c = r["label"]["cat"]
            if c not in cats:
                out.append(r); cats.add(c)
            if len(out) == k:
                return out
    return rnd.sample(pool, k)


def messages_for(rec: dict, shots: list[dict]) -> list[dict]:
    m = [{"role": "system", "content": rec["system"]}]
    for s in shots:
        m += [{"role": "user", "content": s["input"]}, {"role": "assistant", "content": s["target"]}]
    m.append({"role": "user", "content": rec["input"]})
    return m


def call(endpoint: str, model: str, rec: dict, shots: list[dict]) -> dict:
    t0 = time.perf_counter()
    try:
        r = requests.post(f"{endpoint}/chat/completions", timeout=600, json={
            "model": model, "messages": messages_for(rec, shots), "temperature": 0,
            "max_tokens": MAX_TOKENS[rec["task"]],
            "chat_template_kwargs": {"enable_thinking": False}})
        r.raise_for_status()
        j = r.json()
        text = j["choices"][0]["message"]["content"]
        u = j.get("usage", {})
        return {"id": rec["id"], "raw": text, "out_tok": u.get("completion_tokens", 0),
                "in_tok": u.get("prompt_tokens", 0), "ms": round((time.perf_counter() - t0) * 1000)}
    except Exception as e:
        return {"id": rec["id"], "raw": "", "out_tok": 0, "in_tok": 0, "error": f"{type(e).__name__}: {e}"[:300],
                "ms": round((time.perf_counter() - t0) * 1000)}


def score(task: str, recs: list[dict], outs: dict) -> dict:
    preds = [S.parse_output(outs[r["id"]]["raw"]) for r in recs]
    toks = [outs[r["id"]]["out_tok"] for r in recs]
    if task in ("estate", "estate_hard", "estate_hard2"):
        rep = M.evaluate(preds, [r["label"] for r in recs],
                         sources=[unnumber(r["input"]) for r in recs], output_tokens=toks)
    else:
        rep = M.flat_f1(preds, [json.loads(r["target"]) for r in recs])
        rep["mean_output_tokens"] = sum(toks) / max(1, len(toks))
    lat = sorted(outs[r["id"]]["ms"] for r in recs)
    rep["median_latency_ms"] = lat[len(lat) // 2] if lat else None
    rep["errors"] = sum(1 for r in recs if "error" in outs[r["id"]])
    return rep


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", required=True)
    ap.add_argument("--endpoint", default="http://127.0.0.1:8090/v1")
    ap.add_argument("--model", default=None, help="model id; default = first served")
    ap.add_argument("--tasks", default="estate,invoice,cord")
    ap.add_argument("--split", default="test")
    ap.add_argument("--shots", type=int, default=0)
    ap.add_argument("--concurrency", type=int, default=64)
    ap.add_argument("--limit", type=int, default=0)
    a = ap.parse_args()

    ep = a.endpoint.rstrip("/")
    model = a.model or requests.get(f"{ep}/models", timeout=10).json()["data"][0]["id"]
    tasks = a.tasks.split(",")
    work = []
    for t in tasks:
        recs = load(t, a.split)
        recs = recs[: a.limit] if a.limit else recs
        work += [(t, r) for r in recs]
    shots = {t: pick_shots(t, a.shots) for t in tasks}
    print(f"model {model} | {len(work)} documents | {a.shots}-shot | concurrency {a.concurrency}", flush=True)

    log = RunLogger(HERE / "runs" / f"eval_{a.name}", total_steps=len(work),
                    config={"kind": "evaluation", "model": model, "shots": a.shots, "split": a.split,
                            "tasks": tasks}, alerts={"collapse_loss": -1})
    outs, t0, done, out_tok = {}, time.time(), 0, 0
    with ThreadPoolExecutor(a.concurrency) as pool:
        futs = [pool.submit(call, ep, model, r, shots[t]) for t, r in work]
        for f in as_completed(futs):
            o = f.result(); outs[o["id"]] = o
            done += 1; out_tok += o["out_tok"]
            if "error" in o:
                log.alert("WARN", f"{o['id']}: {o['error'][:150]}")
            if done % 25 == 0 or done == len(work):
                log.log(done, tokens_per_sec=out_tok / (time.time() - t0), errors=sum("error" in x for x in outs.values()))
            if log.should_stop():
                for x in futs:
                    x.cancel()
                break
    wall = time.time() - t0

    report = {"name": a.name, "model": model, "shots": a.shots, "split": a.split,
              "wall_seconds": round(wall, 1), "output_tokens_per_sec": round(out_tok / wall, 1),
              "tasks": {}}
    for t in tasks:
        recs = [r for tt, r in work if tt == t and r["id"] in outs]
        if recs:
            report["tasks"][t] = score(t, recs, outs)
    RESULTS.mkdir(exist_ok=True)
    (RESULTS / f"{a.name}.json").write_text(json.dumps(
        {"report": report, "predictions": outs}, indent=1, ensure_ascii=False))

    for t, rep in report["tasks"].items():
        print("\n" + M.format_report(rep, f"{a.name} :: {t}"))
        print(f"{'median latency':<18}{rep['median_latency_ms']} ms   errors {rep['errors']}")
    print(f"\nwall {wall:.0f}s | {report['output_tokens_per_sec']} output tok/s aggregate")
    print(f"saved results/{a.name}.json")
    log.close()


if __name__ == "__main__":
    main()

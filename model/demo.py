"""Afterword end to end on a folder of documents, on this box only.

    python demo.py data/demo_docs                       # 4B on :8091
    python demo.py ~/our_docs --dod 2026-09-10          # date of death drives "within N days"
    python demo.py ~/our_docs --verify                  # + 32B verification of uncertain facts (needs :8090)

Reads .txt/.md (letters; "sms" in the name = SMS), .eml (email), .pdf (pdftotext), .png/.jpg
(RapidOCR on the Arm CPU) and .csv (SMS export: date,sender,body - one message per row).

  L0  triage          bge-small on CPU: drop / memory never reach an LLM (safety rule keeps money docs)
  L1  extraction      fine-tuned 4B, compact JSON with cited line numbers; ungrounded values removed
  L2  gate            per-field confidence vs thresholds calibrated on cal.jsonl;
                      uncertain facts -> 32B verifies (--verify) or the value is marked provisional
  L3  results         tags, 0-100 priority with reasons, same-account merging, ranked action list

Prints the ranked list and a per-layer ledger (tokens, prefix-cache reuse, GPU energy, external
connections observed), and writes out/demo_results.json in the afterword.finding/v1 shape.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import email
import email.policy
import json
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import requests

import engine as E
import schema as S
from cascade import FACTS, field_confidence
from l0_triage import Triage
from postprocess import clean

HERE = Path(__file__).resolve().parent
L1_URL, L2_URL = "http://127.0.0.1:8091/v1", "http://127.0.0.1:8090/v1"

# ---------------------------------------------------------------- reading documents


def read_folder(folder: Path) -> list[dict]:
    docs = []
    for p in sorted(folder.iterdir()):
        suf = p.suffix.lower()
        try:
            if suf in (".txt", ".md"):
                docs.append({"id": p.stem, "source": "sms" if "sms" in p.stem.lower() else "letter",
                             "text": p.read_text(errors="replace").strip()})
            elif suf == ".eml":
                m = email.message_from_bytes(p.read_bytes(), policy=email.policy.default)
                body = m.get_body(preferencelist=("plain",))
                text = (f"Subject: {m['subject'] or ''}\nFrom: {m['from'] or ''}\nDate: {m['date'] or ''}\n\n"
                        + (body.get_content() if body else ""))
                docs.append({"id": p.stem, "source": "email", "text": text.strip()})
            elif suf == ".pdf":
                text = subprocess.run(["pdftotext", "-layout", str(p), "-"], capture_output=True,
                                      text=True, timeout=60).stdout
                docs.append({"id": p.stem, "source": "letter", "text": "\n".join(
                    l.strip() for l in text.splitlines() if l.strip())})
            elif suf in (".png", ".jpg", ".jpeg"):
                from prep_public import _ocr_engine, group_lines
                result, _ = _ocr_engine()(str(p))
                docs.append({"id": p.stem, "source": "letter", "text": "\n".join(group_lines(result))})
            elif suf == ".csv":
                for i, row in enumerate(csv.DictReader(p.open())):
                    docs.append({"id": f"{p.stem}-{i + 1}", "source": "sms",
                                 "text": f"From: {row.get('sender', '')}\nDate: {row.get('date', '')}\n{row.get('body', '')}"})
        except Exception as e:
            print(f"  ! could not read {p.name}: {type(e).__name__}: {e}")
    return [d for d in docs if d["text"]]

# ---------------------------------------------------------------- measurement helpers


class Meter:
    """GPU power samples + any non-loopback TCP connection held by the pipeline's processes."""

    def __init__(self, pids: set[int]):
        self.pids, self.samples, self.external, self._stop = pids, [], set(), threading.Event()

    def _conns(self):
        out = subprocess.run(["ss", "-tnpH", "state", "established"], capture_output=True, text=True).stdout
        for line in out.splitlines():
            parts = line.split()
            if len(parts) < 4 or not any(f"pid={p}," in line for p in self.pids):
                continue
            peer = parts[3]
            if not (peer.startswith("127.") or peer.startswith("[::1]") or peer.startswith("[::ffff:127.")):
                self.external.add(peer)

    def _run(self):
        while not self._stop.is_set():
            try:
                w = subprocess.run(["nvidia-smi", "--query-gpu=power.draw", "--format=csv,noheader,nounits"],
                                   capture_output=True, text=True, timeout=5).stdout.strip()
                self.samples.append(float(w.splitlines()[0]))
            except Exception:
                pass
            self._conns()
            self._stop.wait(0.5)

    def __enter__(self):
        self.t0 = time.time(); self.th = threading.Thread(target=self._run, daemon=True); self.th.start()
        return self

    def __exit__(self, *a):
        self._stop.set(); self.th.join(); self.seconds = time.time() - self.t0
        self.mean_w = sum(self.samples) / len(self.samples) if self.samples else 0.0
        self.joules = self.mean_w * self.seconds


def vllm_counters(url):
    try:
        text = requests.get(url.replace("/v1", "/metrics"), timeout=5).text
    except Exception:
        return {}
    out = {}
    for line in text.splitlines():
        for k in ("vllm:prompt_tokens_total", "vllm:prompt_tokens_cached_total", "vllm:generation_tokens_total"):
            if line.startswith(k + "{"):
                out[k] = out.get(k, 0) + float(line.rsplit(" ", 1)[1])
    return out


def server_pids(port):
    out = subprocess.run(["ss", "-tlnpH", f"sport = :{port}"], capture_output=True, text=True).stdout
    return {int(x.split(",")[0]) for x in out.split("pid=")[1:]}

# ---------------------------------------------------------------- model calls


def call(url, text, logprobs):
    r = requests.post(f"{url}/chat/completions", timeout=300, json={
        "temperature": 0, "max_tokens": 200, "logprobs": logprobs, **({"top_logprobs": 1} if logprobs else {}),
        "messages": [{"role": "system", "content": S.SYSTEM_PROMPT},
                     {"role": "user", "content": S.number_lines(text)}],
        "chat_template_kwargs": {"enable_thinking": False}})
    r.raise_for_status()
    j = r.json(); ch = j["choices"][0]
    toks = [{"t": c["token"], "lp": c["logprob"]} for c in (ch.get("logprobs") or {}).get("content") or []]
    return ch["message"]["content"], toks, j.get("usage", {}), j.get("model")


def load_thresholds():
    for name in ("cascade_verify.json", "cascade_replace.json"):
        p = HERE / "results" / name
        if p.exists():
            return {k: v["threshold"] for k, v in json.loads(p.read_text())["thresholds"].items()}
    return {}

# ---------------------------------------------------------------- pipeline


def run(docs, dod, as_of, verify):
    th = load_thresholds()
    led = {"documents": len(docs)}
    t_all = time.time()

    t0 = time.time()
    routes = Triage().route_many([d["text"] for d in docs])
    led["L0_seconds_cpu"] = round(time.time() - t0, 2)
    for d, (route, why) in zip(docs, routes):
        d["route"], d["route_reason"] = route, why

    todo = [d for d in docs if d["route"] == "extract"]
    before = vllm_counters(L1_URL)
    pids = server_pids(8091) | {__import__("os").getpid()} | (server_pids(8090) if verify else set())
    results = []
    with Meter(pids) as meter:
        with ThreadPoolExecutor(16) as pool:
            outs = list(pool.map(lambda d: (d, *call(L1_URL, d["text"], True)), todo))
        for d, raw, toks, usage, model in outs:
            lines = d["text"].splitlines() or [""]
            t = time.perf_counter()
            pred = clean(S.parse_output(raw), d["text"])
            errors = S.validate(pred, len(lines))
            if pred is None:
                results.append(E._result(d["id"], d["source"], "failed", None, [], {"schema_errors": errors},
                                         model, t, usage, raw)); continue
            conf = field_confidence(raw, toks)
            uncertain = [k for k in S.KEY_ORDER if k in pred and k in conf and k in th and conf[k] < th[k]]
            d["_pred"], d["_raw"], d["_usage"], d["_model"], d["_uncertain"] = pred, raw, usage, model, uncertain
            d["_conf"] = {k: round(v, 4) for k, v in conf.items()}
        gated = [d for d in todo if d.get("_uncertain")]
        verdicts = {}
        if verify and gated:
            with ThreadPoolExecutor(8) as pool:
                big = list(pool.map(lambda d: call(L2_URL, d["text"], False), gated))
            for d, (raw32, _, u32, _) in zip(gated, big):
                p32 = clean(S.parse_output(raw32), d["text"]) or {}
                verdicts[d["id"]] = ({k: E.normalise(k, p32.get(k)) == E.normalise(k, d["_pred"].get(k))
                                      for k in d["_uncertain"] if k in FACTS}, u32)
    led["L1_L2_seconds_gpu"] = round(meter.seconds, 2)
    after = vllm_counters(L1_URL)

    out_tok = in_tok = esc_fields = prov = 0
    tok32 = 0
    for d in todo:
        if "_pred" not in d:
            continue
        pred, lines = d["_pred"], d["text"].splitlines() or [""]
        grounded = E._grounding(pred, lines)
        agree, u32 = verdicts.get(d["id"], ({}, {}))
        tok32 += u32.get("prompt_tokens", 0) + u32.get("completion_tokens", 0)
        esc_fields += len([k for k in d["_uncertain"] if k in FACTS])
        disputed = [k for k in d["_uncertain"] if not agree.get(k, False)]   # no 32B verdict = unconfirmed
        provisional = bool(disputed) or not all(grounded.values())
        prov += provisional
        evidence = [{"line": i, "text": lines[i - 1]} for i in pred.get("ev", []) if 1 <= i <= len(lines)]
        finding = S.enrich(pred, dod, "\n".join(e["text"] for e in evidence), as_of, provisional)
        res = E._result(d["id"], d["source"], "needs_review" if provisional else "accepted", finding, evidence,
                        {"schema_errors": S.validate(pred, len(lines)), "grounded": grounded,
                         "confidence": d["_conf"], "uncertain": d["_uncertain"],
                         "verified_by_32B": {k: v for k, v in agree.items()}},
                        d["_model"], time.perf_counter(), d["_usage"], d["_raw"])
        res["meta"]["tier"] = "L2" if d["id"] in verdicts else "L1"
        results.append(res)
        in_tok += d["_usage"].get("prompt_tokens", 0); out_tok += d["_usage"].get("completion_tokens", 0)
    for d in docs:
        if d["route"] != "extract":
            cat = "irrelevant" if d["route"] == "drop" else "personal"
            f = S.enrich({"cat": cat}); f["triage"] = d["route"]
            results.append(E._result(d["id"], d["source"], "accepted", f, [], {"l0": d["route_reason"]},
                                     "L0 bge-small", time.perf_counter(), {}, None))
    S.rank(results)

    cached = after.get("vllm:prompt_tokens_cached_total", 0) - before.get("vllm:prompt_tokens_cached_total", 0)
    prompt = after.get("vllm:prompt_tokens_total", 0) - before.get("vllm:prompt_tokens_total", 0)
    led.update({
        "L0_skipped_no_llm": sum(d["route"] != "extract" for d in docs),
        "L0_kept_by_safety_rule": sum("safety rule" in d["route_reason"] for d in docs),
        "L1_docs_to_4B": len(todo), "L1_prompt_tokens": in_tok, "L1_output_tokens": out_tok,
        "L1_output_tokens_per_doc": round(out_tok / max(1, len(todo)), 1),
        "L1_prompt_tokens_from_prefix_cache": int(cached), "L1_prefix_cache_share": round(cached / prompt, 3) if prompt else None,
        "L2_uncertain_fact_fields": esc_fields, "L2_docs_verified_by_32B": len(verdicts), "L2_32B_tokens": tok32,
        "results_provisional_docs": prov,
        "gpu_mean_w": round(meter.mean_w, 1), "gpu_joules": round(meter.joules),
        "gpu_joules_per_llm_doc": round(meter.joules / max(1, len(todo)), 2),
        "external_connections_seen": sorted(meter.external),
        "wall_seconds": round(time.time() - t_all, 2),
    })
    return results, led


def show(results, led):
    tasks = sorted((r for r in results if r["finding"] and r["finding"].get("rank")), key=lambda r: r["finding"]["rank"])
    print(f"\n{'=' * 100}\n RANKED ACTION LIST  ({len(tasks)} tasks from {led['documents']} documents)\n{'=' * 100}")
    for r in tasks:
        f = r["finding"]
        amt = f"${f['money_at_stake']:,.2f}" if f.get("money_at_stake") else ""
        print(f"\n#{f['rank']:<2} {f['priority']} {f['priority_score']:>3}  {f.get('inst') or f['cat']}"
              f"  [{f.get('act', '')}] {amt}  ({r['id']}, {r['status']})")
        print(f"      tags: {', '.join(f['tags'])}")
        for why in f["priority_reasons"]:
            print(f"      {why}")
        if f.get("related_ids"):
            print(f"      same account: {', '.join(f['related_ids'])}")
        if r["checks"].get("uncertain"):
            print(f"      uncertain -> {r['checks']['uncertain']}  32B: {r['checks'].get('verified_by_32B') or 'not run'}")
    other = [r for r in results if r["route"] in ("memory", "drop")]
    print(f"\n memories: {sum(r['route'] == 'memory' for r in other)}   ignored: {sum(r['route'] == 'drop' for r in other)}")
    print(f"\n{'=' * 100}\n LEDGER\n{'=' * 100}")
    for k, v in led.items():
        print(f"  {k:36} {v}")
    ext = led["external_connections_seen"]
    print(f"\n  PRIVACY: {'no connection left this machine' if not ext else 'EXTERNAL CONNECTIONS: ' + ', '.join(ext)}"
          " (pipeline + model-server processes, sampled every 0.5 s)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("folder", type=Path)
    ap.add_argument("--dod", type=dt.date.fromisoformat, default=None, help="date of death (YYYY-MM-DD)")
    ap.add_argument("--as-of", type=dt.date.fromisoformat, default=dt.date.today())
    ap.add_argument("--verify", action="store_true", help="32B verifies uncertain facts (needs :8090)")
    a = ap.parse_args()
    docs = read_folder(a.folder)
    print(f"read {len(docs)} documents from {a.folder}")
    results, led = run(docs, a.dod, a.as_of, a.verify)
    show(results, led)
    (HERE / "out").mkdir(exist_ok=True)
    (HERE / "out" / "demo_results.json").write_text(json.dumps({"ledger": led, "results": results}, indent=1, default=str))
    print("\nsaved out/demo_results.json")


if __name__ == "__main__":
    main()

"""Measure GPU energy for any command: samples nvidia-smi power while it runs.

    python powerlog.py <label> -- python evaluate.py --name sft3_0shot ...
Appends {label, seconds, mean_w, peak_w, idle_w, joules, joules_above_idle} to results/energy.jsonl.
Divide by documents processed for joules per document. `idle_w` is sampled before the
command starts, so `joules_above_idle` is the energy the work itself cost.
"""
from __future__ import annotations

import json
import subprocess
import sys
import threading
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent


def read_w() -> float | None:
    try:
        out = subprocess.run(["nvidia-smi", "--query-gpu=power.draw", "--format=csv,noheader,nounits"],
                             capture_output=True, text=True, timeout=5).stdout.strip().splitlines()
        return float(out[0])
    except Exception:
        return None


def main():
    if "--" not in sys.argv or sys.argv.index("--") < 2:
        sys.exit("usage: python powerlog.py <label> -- <command ...>")
    label, cmd = sys.argv[1], sys.argv[sys.argv.index("--") + 1:]
    idle = []
    for _ in range(6):                     # baseline before the work starts
        w = read_w()
        if w is not None:
            idle.append(w)
        time.sleep(0.5)
    samples, stop = [], threading.Event()

    def sampler():
        while not stop.is_set():
            w = read_w()
            if w is not None:
                samples.append((time.time(), w))
            stop.wait(0.5)

    th = threading.Thread(target=sampler, daemon=True); th.start()
    t0 = time.time()
    rc = subprocess.call(cmd)
    secs = time.time() - t0
    stop.set(); th.join()
    ws = [w for _, w in samples] or [0.0]
    mean_w, idle_w = sum(ws) / len(ws), (sum(idle) / len(idle) if idle else 0.0)
    rec = {"label": label, "cmd": " ".join(cmd), "rc": rc, "seconds": round(secs, 1),
           "mean_w": round(mean_w, 1), "peak_w": round(max(ws), 1), "idle_w": round(idle_w, 1),
           "joules": round(mean_w * secs), "joules_above_idle": round(max(0.0, mean_w - idle_w) * secs),
           "samples": len(samples)}
    (HERE / "results").mkdir(exist_ok=True)
    with open(HERE / "results" / "energy.jsonl", "a") as fh:
        fh.write(json.dumps(rec) + "\n")
    print(f"[powerlog] {label}: {secs:.0f}s, mean {mean_w:.1f} W (idle {idle_w:.1f}), {rec['joules']} J", flush=True)
    sys.exit(rc)


if __name__ == "__main__":
    main()

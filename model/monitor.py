"""Watch and control training runs.

    python monitor.py --list                  every run and its state
    python monitor.py runs/<name>             live dashboard, refreshes every 5s (Ctrl-C to leave;
                                              leaving does NOT stop training)
    python monitor.py runs/<name> --once      print one snapshot and exit
    python monitor.py runs/<name> --stop      stop safely: checkpoint, then exit

In a notebook:
    from monitor import snapshot, plot_run, stop
    print(snapshot("runs/<name>")); plot_run("runs/<name>")
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
RUNS = HERE / "runs"
BARS = "▁▂▃▄▅▆▇█"


def _read_status(run: Path) -> dict:
    try:
        return json.loads((run / "status.json").read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _read_metrics(run: Path) -> list[dict]:
    out = []
    try:
        for line in (run / "metrics.jsonl").read_text().splitlines():
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    except FileNotFoundError:
        pass
    return out


def _alive(pid) -> bool:
    from trainlog import pid_alive
    return pid_alive(pid)


def _gpu() -> str:
    try:
        r = subprocess.run(["nvidia-smi", "--query-gpu=utilization.gpu",
                            "--format=csv,noheader"], capture_output=True, text=True, timeout=5)
        return r.stdout.strip() or "?"
    except Exception:
        return "?"


def _spark(vals, width=40) -> str:
    import math
    vals = [v for v in vals if isinstance(v, (int, float)) and math.isfinite(v)]  # skip NaN/inf
    if len(vals) < 2:
        return ""
    if len(vals) > width:
        step = len(vals) / width
        vals = [vals[int(i * step)] for i in range(width)]
    lo, hi = min(vals), max(vals)
    span = (hi - lo) or 1
    return "".join(BARS[min(len(BARS) - 1, int((v - lo) / span * (len(BARS) - 1)))] for v in vals)


def _fmt_s(s) -> str:
    if s is None:
        return "?"
    s = int(s)
    return f"{s // 3600}h{s % 3600 // 60:02d}m" if s >= 3600 else f"{s // 60}m{s % 60:02d}s"


def state_of(run: Path) -> str:
    """RUNNING / DONE / STOPPED / FAILED, plus STALLED and DIED detection."""
    st = _read_status(run)
    state = st.get("state", "UNKNOWN")
    if state == "RUNNING":
        if not _alive(st.get("pid")):
            return "DIED (process gone without closing - check train.log)"
        age = time.time() - st.get("updated_at", 0)
        if age > 300:
            return f"STALLED (no update for {_fmt_s(age)})"
    return state


def snapshot(run) -> str:
    run = Path(run)
    st = _read_status(run)
    rows = [r for r in _read_metrics(run) if not r.get("eval")]
    evals = [r for r in _read_metrics(run) if r.get("eval")]
    last = st.get("last", {})
    step, total = st.get("step", 0), st.get("total") or 1
    pct = step / total
    bar = "█" * int(pct * 30) + "·" * (30 - int(pct * 30))

    out = [
        f"{'run':<16}{run.name}",
        f"{'state':<16}{state_of(run)}    pid {st.get('pid')}    GPU {_gpu()}",
        f"{'progress':<16}{bar} {step}/{total} ({pct:.0%})",
        f"{'elapsed':<16}{_fmt_s(st.get('elapsed_s'))}    ETA {_fmt_s(st.get('eta_s'))}",
    ]
    for k, v in last.items():
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            out.append(f"{k:<16}{v:,.4g}")
    if st.get("best_val") is not None:
        out.append(f"{'best val loss':<16}{st['best_val']:.4f}")
    losses = [r.get("loss") for r in rows]
    if any(l is not None for l in losses):
        out.append(f"{'loss trend':<16}{_spark(losses)}")
    vls = [e.get("val_loss", e.get("loss")) for e in evals]
    if any(v is not None for v in vls):
        out.append(f"{'val trend':<16}{_spark(vls)}")
    if st.get("stop_reason"):
        out.append(f"{'stopped':<16}{st['stop_reason']}")
    try:
        alerts = (run / "alerts.log").read_text().splitlines()[-6:]
    except FileNotFoundError:
        alerts = []
    out.append(f"{'alerts':<16}" + ("none" if not alerts else ""))
    out += [f"   {a}" for a in alerts]
    ck = sorted((run / "ckpt").glob("step-*")) if (run / "ckpt").exists() else []
    out.append(f"{'checkpoints':<16}{', '.join(p.name for p in ck) or 'none yet'}"
               + ("  + best" if (run / "ckpt" / "best").exists() else ""))
    return "\n".join(out)


def stop(run) -> str:
    run = Path(run)
    (run / "STOP").touch()
    return (f"STOP requested for {run.name}. It will save a checkpoint and exit at the end "
            f"of the current step. Resume later from {run / 'ckpt'}.")


def list_runs() -> str:
    if not RUNS.exists():
        return "no runs yet"
    rows = []
    for r in sorted(RUNS.iterdir()):
        if r.is_dir() and (r / "status.json").exists():
            st = _read_status(r)
            rows.append(f"{r.name:<32}{state_of(r):<24}{st.get('step', 0)}/{st.get('total', '?')}")
    return "\n".join(rows) or "no runs yet"


def plot_run(run):
    """Loss, validation loss and throughput charts, for the notebook."""
    import matplotlib.pyplot as plt
    run = Path(run)
    rows = [r for r in _read_metrics(run) if not r.get("eval")]
    evals = [r for r in _read_metrics(run) if r.get("eval")]
    fig, ax = plt.subplots(1, 2, figsize=(12, 3.5))
    if rows:
        ax[0].plot([r["step"] for r in rows if "loss" in r],
                   [r["loss"] for r in rows if "loss" in r], label="train loss")
    if evals:
        ax[0].plot([e["step"] for e in evals],
                   [e.get("val_loss", e.get("loss")) for e in evals], "o-", label="val loss")
    ax[0].set_xlabel("step"); ax[0].legend(); ax[0].set_title(run.name)
    tps = [(r["step"], r["tokens_per_sec"]) for r in rows if r.get("tokens_per_sec")]
    if tps:
        ax[1].plot(*zip(*tps)); ax[1].set_title("tokens / sec"); ax[1].set_xlabel("step")
    plt.tight_layout()
    plt.show()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("run", nargs="?")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--stop", action="store_true")
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--every", type=float, default=5.0)
    a = ap.parse_args()

    if a.list or not a.run:
        print(list_runs()); return
    run = Path(a.run)
    if not run.is_absolute() and not run.exists():
        run = RUNS / a.run
    if a.stop:
        print(stop(run)); return
    if a.once:
        print(snapshot(run)); return
    try:
        while True:
            os.system("clear")
            print(snapshot(run))
            print("\n(Ctrl-C leaves the monitor; training keeps running.  --stop to stop it.)")
            s = state_of(run)
            if s in ("DONE", "STOPPED", "FAILED") or s.startswith("DIED"):
                break
            time.sleep(a.every)
    except KeyboardInterrupt:
        print("\nleft monitor - training untouched")


if __name__ == "__main__":
    main()

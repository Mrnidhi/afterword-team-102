"""Run logging, alerts, checkpoints and safe stopping for every Afterword training job.

Every training script uses RunLogger. It gives you, for each run directory:

  runs/<name>/config.json     hyperparameters and start time
  runs/<name>/metrics.jsonl   one line per logged step (machine readable)
  runs/<name>/status.json     latest state, step, ETA, losses - what monitor.py reads
  runs/<name>/alerts.log      anything that looks wrong, with a timestamp
  runs/<name>/ckpt/           rolling checkpoints + the best one by validation loss

Stopping safely - three ways, all of them save a checkpoint first:
  python monitor.py runs/<name> --stop      (creates a STOP file)
  touch runs/<name>/STOP
  kill <pid>                                (SIGTERM / Ctrl-C are caught)

Then fix the parameter and resume from the last checkpoint instead of starting over.
Only `kill -9` loses work - never use it on a training run.
"""
from __future__ import annotations

import json
import math
import os
import shutil
import signal
import statistics
import time
from collections import deque
from pathlib import Path

DEFAULT_ALERTS = {
    "auto_stop_on_nan": True,      # a NaN loss never recovers - stop immediately
    "spike_factor": 3.0,           # loss > 3x its moving average -> warn
    "collapse_loss": 0.01,         # train loss this low usually means memorisation
    "overfit_patience": 2,         # val loss rising this many evals in a row -> warn
    "early_stop_on_overfit": False,
    "slowdown_factor": 0.6,        # throughput below 60% of its median -> warn
    "mem_warn_gb": 100.0,          # the box has ~121 GB and is shared with teammates
    "grad_norm_warn": 50.0,
    "warmup_logs": 5,              # don't judge spikes before this many logs
}


def pid_alive(pid) -> bool:
    """True if the process exists (even if another user owns it)."""
    try:
        os.kill(int(pid), 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except (TypeError, ValueError, OSError):
        return False


class RunAlreadyActive(RuntimeError):
    pass


def _atomic_write(path: Path, text: str):
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text)
    os.replace(tmp, path)          # a crash mid-write never leaves a half file


class RunLogger:
    def __init__(self, run_dir, total_steps: int, config: dict | None = None,
                 alerts: dict | None = None, keep_checkpoints: int = 2, start_step: int = 0):
        self.dir = Path(run_dir)
        # Shared box: refuse to start if someone else's copy of this run is still alive.
        # Without this, a second launch would delete their STOP file and overwrite their status.
        try:
            prev = json.loads((self.dir / "status.json").read_text())
        except (FileNotFoundError, json.JSONDecodeError):
            prev = {}
        if (prev.get("state") == "RUNNING" and prev.get("pid") not in (None, os.getpid())
                and pid_alive(prev["pid"])):
            raise RunAlreadyActive(
                f"{self.dir.name} is already running (pid {prev['pid']}). "
                f"Watch it: python monitor.py {self.dir.name}   "
                f"Stop it safely: python monitor.py {self.dir.name} --stop")
        self.dir.mkdir(parents=True, exist_ok=True)
        (self.dir / "ckpt").mkdir(exist_ok=True)
        self.total = total_steps
        self.cfg = {**DEFAULT_ALERTS, **(alerts or {})}
        self.keep = keep_checkpoints
        self.t0 = time.time()
        self.stop_requested = False
        self.stop_reason = None
        self._ema = None
        self._n_logs = 0
        self._tps = deque(maxlen=30)
        self._val_hist = []
        self._warned = set()
        self.best_val = math.inf
        self.last = {}
        self.start_step = start_step           # steps already done before a resume
        self.cur_step = start_step
        self._slow = False

        stale = self.dir / "STOP"
        if stale.exists():
            stale.unlink()                         # a leftover STOP from last time
        _atomic_write(self.dir / "config.json", json.dumps(
            {"started": time.strftime("%Y-%m-%d %H:%M:%S"), "pid": os.getpid(),
             "total_steps": total_steps, "alerts": self.cfg, **(config or {})}, indent=2))
        self._metrics = open(self.dir / "metrics.jsonl", "a", buffering=1)

        for sig in (signal.SIGTERM, signal.SIGINT):
            signal.signal(sig, self._on_signal)
        self._status("RUNNING", step=0)
        print(f"[run] logging to {self.dir}  (stop safely: touch {self.dir}/STOP)", flush=True)

    # ------------------------------------------------------------ control

    def _on_signal(self, signum, _frame):
        self.request_stop(f"signal {signal.Signals(signum).name}")

    def request_stop(self, reason: str):
        if not self.stop_requested:
            self.stop_requested, self.stop_reason = True, reason
            self.alert("STOP", f"stop requested: {reason} - will checkpoint and exit")

    def should_stop(self) -> bool:
        """Call once per step. True means: save a checkpoint and leave the loop."""
        if (self.dir / "STOP").exists():
            self.request_stop("STOP file")
        return self.stop_requested

    # ------------------------------------------------------------ alerts

    def alert(self, level: str, msg: str, once_key: str | None = None):
        if once_key:
            if once_key in self._warned:
                return
            self._warned.add(once_key)
        line = f"{time.strftime('%H:%M:%S')} [{level}] {msg}"
        with open(self.dir / "alerts.log", "a") as f:
            f.write(line + "\n")
        print(f"!! {line}", flush=True)

    def _check(self, step, m):
        c = self.cfg
        loss = m.get("loss")
        if loss is not None:
            if not math.isfinite(loss):
                self.alert("ALERT", f"step {step}: loss is {loss}")
                if c["auto_stop_on_nan"]:
                    self.request_stop("non-finite loss")
                return
            prior = self._ema                      # compare against the average BEFORE this step
            if (prior is not None and self._n_logs > c["warmup_logs"]
                    and loss > c["spike_factor"] * prior):
                self.alert("WARN", f"step {step}: loss spike {loss:.4f} vs avg {prior:.4f}")
            self._ema = loss if prior is None else 0.9 * prior + 0.1 * loss
            if loss < c["collapse_loss"]:
                self.alert("WARN", f"step {step}: train loss {loss:.5f} is near zero - "
                           "likely memorisation. Watch val_loss; consider stopping.",
                           once_key="collapse")
        tps = m.get("tokens_per_sec")
        if tps:
            if len(self._tps) >= 5:
                med = statistics.median(self._tps)
                slow = tps < c["slowdown_factor"] * med
                if slow and not self._slow:        # warn once per slowdown, not every step
                    self.alert("WARN", f"step {step}: throughput {tps:,.0f} tok/s, "
                               f"median {med:,.0f} - is something else using the GPU?")
                elif not slow and self._slow:
                    self.alert("INFO", f"step {step}: throughput recovered ({tps:,.0f} tok/s)")
                self._slow = slow
            if not self._slow:
                self._tps.append(tps)              # keep slow steps out of the baseline
        mem = max(m.get("peak_gpu_gb") or 0, m.get("reserved_gb") or 0)
        if mem and mem > c["mem_warn_gb"]:
            self.alert("WARN", f"peak memory {mem:.1f} GB > {c['mem_warn_gb']} GB",
                       once_key="mem")
        gn = m.get("grad_norm")
        if gn is not None and math.isfinite(gn) and gn > c["grad_norm_warn"]:
            self.alert("WARN", f"step {step}: grad norm {gn:.1f}")

    # ------------------------------------------------------------ logging

    def log(self, step: int, **metrics):
        """Log training metrics for a step. Checks alerts and updates status."""
        self._n_logs += 1
        self.cur_step = step
        rec = {"step": step, "t": round(time.time() - self.t0, 1), **metrics}
        self._metrics.write(json.dumps(rec) + "\n")
        self.last.update(metrics)
        self._check(step, metrics)
        parts = [f"step {step}/{self.total}"]
        for k, v in metrics.items():
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                parts.append(f"{k} {v:.2e}" if k == "lr" else
                             f"{k} {v:,.0f}" if k == "tokens_per_sec" else f"{k} {v:.4f}")
        print("  ".join(parts), flush=True)
        self._status("RUNNING", step=step)

    def log_eval(self, step: int, **metrics):
        """Log validation metrics. Tracks best val loss and overfitting."""
        rec = {"step": step, "t": round(time.time() - self.t0, 1), "eval": True, **metrics}
        self._metrics.write(json.dumps(rec) + "\n")
        self.last.update({f"val_{k}" if not k.startswith("val_") else k: v
                          for k, v in metrics.items()})
        vl = metrics.get("val_loss", metrics.get("loss"))
        improved = False
        if vl is not None:
            self._val_hist.append(vl)
            if vl < self.best_val:
                self.best_val, improved = vl, True
            p = self.cfg["overfit_patience"]
            h = self._val_hist
            if len(h) > p and all(h[-i] > h[-i - 1] for i in range(1, p + 1)):
                self.alert("WARN", f"step {step}: val loss rose {p} evals in a row "
                           f"({h[-p-1]:.4f} -> {h[-1]:.4f}) - overfitting")
                if self.cfg["early_stop_on_overfit"]:
                    self.request_stop("overfitting")
        print(f"  [eval] step {step}  " + "  ".join(
            f"{k} {v:.4f}" for k, v in metrics.items() if isinstance(v, (int, float))) +
            ("  (best)" if improved else ""), flush=True)
        self._status("RUNNING", step=step)
        return improved

    def _status(self, state: str, step: int):
        elapsed = time.time() - self.t0
        done = step - self.start_step              # only steps done in THIS session
        rate = done / elapsed if done > 0 and elapsed > 0 else None
        eta = (self.total - step) / rate if rate else None
        _atomic_write(self.dir / "status.json", json.dumps({
            "state": state, "step": step, "total": self.total, "pid": os.getpid(),
            "elapsed_s": round(elapsed), "eta_s": round(eta) if eta else None,
            "updated_at": time.time(), "best_val": None if self.best_val == math.inf
            else self.best_val, "stop_reason": self.stop_reason, "last": self.last,
        }, indent=2))

    # ------------------------------------------------------------ checkpoints

    def checkpoint(self, step: int, save_fn, best: bool = False) -> Path:
        """save_fn(path) writes the model/optimizer. Keeps the last N + the best."""
        ck = self.dir / "ckpt"
        target = ck / f"step-{step:06d}"
        tmp = ck / f".tmp-{step:06d}"
        if tmp.exists():
            shutil.rmtree(tmp)
        save_fn(tmp)
        (tmp / "step.json").write_text(json.dumps({"step": step, "saved": time.time()}))
        if target.exists():
            shutil.rmtree(target)
        os.replace(tmp, target)                    # atomic: no half-written checkpoints
        if best:
            b = ck / "best"
            if b.exists():
                shutil.rmtree(b)
            shutil.copytree(target, b)
        olds = sorted(p for p in ck.glob("step-*"))
        for p in olds[:-self.keep]:
            shutil.rmtree(p)
        print(f"  [ckpt] saved {target.name}" + (" (best)" if best else ""), flush=True)
        return target

    def mark_best(self, step: int):
        """Copy an existing checkpoint to ckpt/best."""
        src = self.dir / "ckpt" / f"step-{step:06d}"
        b = self.dir / "ckpt" / "best"
        if src.exists():
            if b.exists():
                shutil.rmtree(b)
            shutil.copytree(src, b)
            print(f"  [ckpt] step-{step:06d} is the new best", flush=True)

    def latest_checkpoint(self) -> Path | None:
        c = sorted((self.dir / "ckpt").glob("step-*"))
        return c[-1] if c else None

    def close(self, state: str | None = None):
        final = state or ("STOPPED" if self.stop_requested else "DONE")
        self._status(final, step=self.cur_step)
        self._metrics.close()
        print(f"[run] {final}" + (f" ({self.stop_reason})" if self.stop_reason else ""), flush=True)


def latest_checkpoint(run_dir) -> Path | None:
    c = sorted((Path(run_dir) / "ckpt").glob("step-*"))
    return c[-1] if c else None


# ---------------------------------------------------------------- torch helpers

def save_training_state(path, model, optimizer=None, scheduler=None, step=0, extra=None):
    """Adapter weights + optimizer + scheduler + RNG, so resume is exact."""
    import torch
    path = Path(path)
    path.mkdir(parents=True, exist_ok=True)
    model.save_pretrained(path)
    state = {"step": step, "extra": extra or {},
             "torch_rng": torch.get_rng_state(),
             "cuda_rng": torch.cuda.get_rng_state_all() if torch.cuda.is_available() else None}
    if optimizer is not None:
        state["optimizer"] = optimizer.state_dict()
    if scheduler is not None:
        state["scheduler"] = scheduler.state_dict()
    torch.save(state, path / "trainer_state.pt")


def load_training_state(path, optimizer=None, scheduler=None) -> int:
    """Restore optimizer/scheduler/RNG. Load adapter weights separately with PEFT."""
    import torch
    state = torch.load(Path(path) / "trainer_state.pt", weights_only=False)
    if optimizer is not None and "optimizer" in state:
        optimizer.load_state_dict(state["optimizer"])
    if scheduler is not None and "scheduler" in state:
        scheduler.load_state_dict(state["scheduler"])
    torch.set_rng_state(state["torch_rng"])
    if state.get("cuda_rng") is not None and torch.cuda.is_available():
        torch.cuda.set_rng_state_all(state["cuda_rng"])
    return int(state["step"])

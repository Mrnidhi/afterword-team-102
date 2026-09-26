"""Fire drill: a fake training run that exercises every alert and the stop/resume path.

No GPU, no model. ~30 seconds. It deliberately misbehaves so you can see each alert fire
and practise stopping a run safely before real GPU time is at stake.

    python fire_drill.py                 run it; in another terminal: python monitor.py drill
    python fire_drill.py --resume        continue from the last checkpoint after a stop
    python fire_drill.py --nan           inject a NaN loss to watch the automatic stop
"""
import argparse
import json
import math
import random
import time
from pathlib import Path

from trainlog import RunLogger, latest_checkpoint

RUN = Path(__file__).resolve().parent / "runs" / "drill"


def fake_save(path: Path, step: int):
    path.mkdir(parents=True, exist_ok=True)
    (path / "adapter_model.safetensors").write_text(f"fake weights at step {step}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--resume", action="store_true")
    ap.add_argument("--nan", action="store_true")
    ap.add_argument("--steps", type=int, default=60)
    ap.add_argument("--sleep", type=float, default=0.5)
    a = ap.parse_args()

    start = 0
    if a.resume:
        ck = latest_checkpoint(RUN)
        if ck is None:
            print("nothing to resume - run without --resume first")
            return
        start = json.loads((ck / "step.json").read_text())["step"]
        print(f"resuming from {ck.name} (step {start})")

    log = RunLogger(RUN, total_steps=a.steps, start_step=start,
                    config={"kind": "fire_drill", "resumed_from": start or None})
    random.seed(0)
    for step in range(start + 1, a.steps + 1):
        loss = 1.6 * math.exp(-step / 12) + 0.02 * random.random()
        tps = 690 + random.uniform(-15, 15)
        if step == 22:
            loss = 3.0                         # -> loss spike warning
        if step >= 42:
            loss = 0.004                       # -> memorisation warning
        if 28 <= step <= 31:
            tps = 250                          # -> throughput warning
        if a.nan and step == 15:
            loss = float("nan")                # -> automatic stop

        log.log(step, loss=loss, lr=1e-4, tokens_per_sec=tps, peak_gpu_gb=10.5)

        if step % 10 == 0:
            val = 0.30 + 0.004 * max(0, step - 30) ** 1.2   # rises late -> overfitting warning
            best = log.log_eval(step, val_loss=val)
            log.checkpoint(step, lambda p, s=step: fake_save(p, s), best=best)

        if log.should_stop():
            log.checkpoint(step, lambda p, s=step: fake_save(p, s))
            break
        time.sleep(a.sleep)

    log.close()


if __name__ == "__main__":
    main()

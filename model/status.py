"""What is happening on hp24 right now? Run this BEFORE starting anything.

    python status.py

Shows GPU memory and who holds it, the 32B teacher service, every run and its state,
which data exists, and the next step in the plan.
"""
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
KNOWN = {  # command fragments -> what they are, so teammates recognise each process
    "model_server.py chat": "teammate backend: chat model (port 8000)",
    "model_server.py embed": "teammate backend: embedding model (port 8003)",
    "vllm serve": "32B teacher via ZRT (port 8090)",
    "VLLM::EngineCore": "32B teacher via ZRT (port 8090)",
    "fire_drill.py": "fire drill (no GPU)",
    "gen_estate.py": "Step 3 generation",
    "ipykernel": "a Jupyter notebook kernel",
}


def sh(cmd):
    try:
        return subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=15).stdout.strip()
    except Exception:
        return ""


def describe(pid):
    args = sh(f"ps -o args= -p {pid}")
    for frag, name in KNOWN.items():
        if frag in args:
            return name
    return args[:70] or "?"


def main():
    print("=" * 64); print(" hp24 status"); print("=" * 64)

    mem = sh("free -g | awk 'NR==2{print $3\" used / \"$2\" GB, \"$7\" GB available\"}'")
    print(f"\nmemory      {mem}")
    print("\nGPU processes")
    rows = sh("nvidia-smi --query-compute-apps=pid,used_memory --format=csv,noheader,nounits")
    for line in filter(None, rows.splitlines()):
        pid, mb = [x.strip() for x in line.split(",")]
        print(f"  {int(mb) / 1024:6.1f} GB  pid {pid:<8} {describe(pid)}")
    if not rows:
        print("  none")

    print("\nservices")
    up = '"id"' in sh("curl -s --max-time 3 http://127.0.0.1:8090/v1/models")
    print(f"  32B teacher on :8090   {'UP' if up else 'down'}")
    for port, what in ((8000, "teammate chat"), (8003, "teammate embed"), (8080, "teammate http.server")):
        taken = sh(f"ss -ltn | grep -c ':{port} '") not in ("", "0")
        print(f"  port {port} ({what})   {'in use - do not reuse' if taken else 'free'}")

    print("\nruns")
    out = sh(f"cd {HERE} && {sys.executable} monitor.py --list")
    print("  " + (out.replace("\n", "\n  ") if out else "none"))

    print("\ndata")
    steps = [("Step 2 public", "data/public", ["train", "val", "test"]),
             ("Step 3 estate", "data/estate", ["train", "cal", "test"])]
    next_step = None
    for name, d, splits in steps:
        counts = []
        for s in splits:
            p = HERE / d / f"{s}.jsonl"
            counts.append(f"{s} {sum(1 for _ in open(p))}" if p.exists() else f"{s} -")
        done = all((HERE / d / f"{s}.jsonl").exists() for s in splits)
        print(f"  {name:<15} {'done ' if done else 'NOT BUILT'}  " + "  ".join(counts))
        if not done and next_step is None:
            next_step = name
    print(f"\nnext step   {next_step or 'Step 4 - baselines'}")
    print("\nrules: check this before starting a job | never kill -9 | stop runs with "
          "`python monitor.py <run> --stop` | stop ZRT with `zrt service stop <label>`")


if __name__ == "__main__":
    main()

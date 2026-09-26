"""Side-by-side comparison of every evaluated model.

    python compare.py                      # all results/*.json
    python compare.py base4b_0shot sft_0shot base32b_0shot
"""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
RESULTS = HERE / "results"

LABEL = {"base4b_0shot": "4B base", "sft_0shot": "4B TUNED", "base32b_0shot": "32B base",
         "grpo_0shot": "4B GRPO"}
ORDER = ["base4b_0shot", "sft_0shot", "grpo_0shot", "base32b_0shot"]
ROWS = [("field_f1", "%"), ("critical_recall", "%"), ("schema_validity", "%"),
        ("grounding_rate", "%"), ("evidence_recall", "%"), ("parse_rate", "%"),
        ("mean_output_tokens", "n"), ("median_latency_ms", "n")]


def fmt(v, kind):
    if v is None:
        return "n/a"
    return f"{v:.3f}" if kind == "%" else f"{v:,.0f}"


def main():
    names = sys.argv[1:]
    if not names:
        have = {p.stem for p in RESULTS.glob("*.json")}
        names = [n for n in ORDER if n in have] + sorted(have - set(ORDER))
    reps = {}
    for n in names:
        p = RESULTS / f"{n}.json"
        if p.exists():
            reps[n] = json.loads(p.read_text())["report"]
    if not reps:
        print("no results found"); return
    cols = list(reps)
    head = f"{'':30}" + "".join(f"{LABEL.get(c, c):>12}" for c in cols)
    print(head); print("=" * len(head))

    for task in ("estate", "invoice", "cord"):
        if not any(task in r["tasks"] for r in reps.values()):
            continue
        print(f"\n[{task}]")
        for k, kind in ROWS:
            vals = [reps[c]["tasks"].get(task, {}).get(k) for c in cols]
            if all(v is None for v in vals):
                continue
            print(f"  {k:28}" + "".join(f"{fmt(v, kind):>12}" for v in vals))

    print("\n[speed]")
    for k, kind in (("wall_seconds", "n"), ("output_tokens_per_sec", "n")):
        print(f"  {k:28}" + "".join(f"{fmt(reps[c].get(k), kind):>12}" for c in cols))

    if all("estate" in r["tasks"] for r in reps.values()):
        print("\n[estate per-field F1]")
        pf = {c: reps[c]["tasks"]["estate"]["per_field_f1"] for c in cols}
        keys = sorted({k for d in pf.values() for k in d}, key=lambda k: pf[cols[-1]].get(k, 0))
        for k in keys:
            print(f"  {k:28}" + "".join(f"{pf[c].get(k, 0):>12.2f}" for c in cols))


if __name__ == "__main__":
    main()

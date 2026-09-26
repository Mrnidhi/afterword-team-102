"""Re-score stored predictions three ways, identically for every model. No model calls.

  strict      the frozen metric, exactly as evaluate.py reported it
  +clean      after postprocess.clean() (deployable code, runs in the engine)
  +clean,ref4 also compare `ref` by its last four characters on BOTH sides, because
              the product only ever shows and sends the masked ending

    python rescore.py                      # every results/*.json with estate predictions
    python rescore.py base32b_0shot sft2_hard
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import metrics as M
import schema as S
from evaluate import load, unnumber
from postprocess import clean, ref_last4

HERE = Path(__file__).resolve().parent
RESULTS = HERE / "results"
TASKS = ("estate", "estate_hard", "estate_hard2")
SHOW = ("field_f1", "critical_recall", "exact_match", "grounding_rate", "schema_validity")


def _ref4(d):
    if d and "ref" in d:
        d = dict(d); d["ref"] = ref_last4(d["ref"])
    return d


def rescore(name: str) -> dict:
    blob = json.loads((RESULTS / f"{name}.json").read_text())
    outs, rep = blob["predictions"], blob["report"]["tasks"]
    res = {}
    for task in TASKS:
        if task not in rep:
            continue
        recs = [r for r in load(task, blob["report"].get("split", "test")) if r["id"] in outs]
        srcs = [unnumber(r["input"]) for r in recs]
        golds = [r["label"] for r in recs]
        raw = [S.parse_output(outs[r["id"]]["raw"]) for r in recs]
        cleaned = [clean(p, s) for p, s in zip(raw, srcs)]
        res[task] = {
            "strict": M.evaluate(raw, golds, sources=srcs),
            "+clean": M.evaluate(cleaned, golds, sources=srcs),
            "+clean,ref4": M.evaluate([_ref4(p) for p in cleaned], [_ref4(g) for g in golds], sources=srcs),
        }
    return res


def main():
    names = sys.argv[1:] or sorted(p.stem for p in RESULTS.glob("*.json")
                                   if p.stem not in ("rescore", "loss_analysis"))
    all_res = {}
    for n in names:
        try:
            r = rescore(n)
        except (KeyError, json.JSONDecodeError):
            continue
        if not r:
            continue
        all_res[n] = r
        for task, modes in r.items():
            print(f"\n{n}  [{task}]")
            print(f"  {'':14}" + "".join(f"{k:>17}" for k in SHOW))
            for mode, rep in modes.items():
                print(f"  {mode:14}" + "".join(f"{(rep[k] if rep[k] is not None else float('nan')):>17.3f}" for k in SHOW))
            pf = {m: modes[m]["per_field_f1"] for m in modes}
            print("  per-field F1 strict -> +clean,ref4: " + ", ".join(
                f"{k} {pf['strict'][k]:.2f}->{pf['+clean,ref4'].get(k, 0):.2f}" for k in pf["strict"]))
    (RESULTS / "rescore.json").write_text(json.dumps(all_res, indent=1, default=str))
    print("\nsaved results/rescore.json")


if __name__ == "__main__":
    main()

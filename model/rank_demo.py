"""Show the ranked action list for stored predictions: clean -> enrich (tags, score) -> rank.

    python rank_demo.py                       # hard held-out set, sft2 predictions
    python rank_demo.py sft2_0shot estate 15  # results file, task, how many to print
"""
from __future__ import annotations

import datetime as dt
import json
import sys
from collections import Counter
from pathlib import Path

import schema as S
from evaluate import load, unnumber
from postprocess import clean

HERE = Path(__file__).resolve().parent


def ranked(results_name: str, task: str, as_of: dt.date, reference: dt.date) -> list[dict]:
    preds = json.loads((HERE / "results" / f"{results_name}.json").read_text())["predictions"]
    res = []
    for r in load(task, "test"):
        src = unnumber(r["input"]); lines = src.splitlines()
        p = clean(S.parse_output(preds[r["id"]]["raw"]), src)
        if not p:
            continue
        ev = "\n".join(lines[i - 1] for i in p.get("ev", []) if 1 <= i <= len(lines))
        f = S.enrich(p, reference, ev, as_of)
        res.append({"id": r["id"], "route": f["triage"], "finding": f})
    return S.rank(res)


def main():
    name = sys.argv[1] if len(sys.argv) > 1 else "sft2_hard"
    task = sys.argv[2] if len(sys.argv) > 2 else "estate_hard"
    top = int(sys.argv[3]) if len(sys.argv) > 3 else 10
    res = ranked(name, task, as_of=dt.date(2026, 9, 25), reference=dt.date(2026, 9, 10))
    tasks = sorted((x for x in res if x["finding"]["rank"]), key=lambda x: x["finding"]["rank"])
    print(f"{len(res)} documents -> {len(tasks)} ranked tasks "
          f"({sum(1 for x in res if x['finding'].get('merged_into'))} merged into the same account)")
    print("tiers:", dict(Counter(x["finding"]["priority"] for x in tasks)))
    print("tags: ", dict(Counter(t for x in res for t in x["finding"]["tags"]).most_common()))
    print(f"docs with a printed date on cited lines: {sum(1 for x in res if x['finding']['next_date'])}\n")
    for x in tasks[:top]:
        f = x["finding"]
        print(f"#{f['rank']:<3} {f['priority']} {f['priority_score']:>3}  {f['cat']:<12} "
              f"{(f.get('inst') or '')[:30]:<30} {', '.join(f['tags'])}")
        for why in f["priority_reasons"]:
            print(f"{'':10}{why}")
        if f.get("related_ids"):
            print(f"{'':10}also covers: {', '.join(f['related_ids'])}")


if __name__ == "__main__":
    main()

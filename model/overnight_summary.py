"""Pick the model to keep serving and write results/overnight_summary.md. No model calls.

sft3 wins only if it is better on the FRESH hard set (hard2, never trained on) and does
not regress on the ordinary test set by more than 0.01 field F1. Otherwise sft2 stays.
Scores use rescore.py's "+clean,ref4" mode (identical for every model) and strict mode.

    python overnight_summary.py            # prints the winner name on the last line
"""
from __future__ import annotations

import json
from pathlib import Path

from rescore import rescore

HERE = Path(__file__).resolve().parent
R = HERE / "results"
MODE = "+clean,ref4"


def f1(name, task, mode=MODE):
    try:
        return rescore(name)[task][mode]
    except (FileNotFoundError, KeyError):
        return None


def row(label, rep):
    if not rep:
        return f"| {label} | – | – | – | – |"
    return (f"| {label} | {rep['field_f1']:.3f} | {rep['critical_recall']:.3f} | "
            f"{rep['exact_match']:.3f} | {rep['grounding_rate'] or 0:.3f} |")


def energy():
    p = R / "energy.jsonl"
    return [json.loads(l) for l in p.read_text().splitlines()] if p.exists() else []


def main():
    s3_h2, s2_h2 = f1("sft3_hard2", "estate_hard2"), f1("sft2_hard2", "estate_hard2")
    s3_t, s2_t = f1("sft3_0shot", "estate"), f1("sft2_0shot", "estate")
    winner = "sft2"
    why = "sft3 results missing"
    if s3_h2 and s2_h2 and s3_t and s2_t:
        gain = s3_h2["field_f1"] - s2_h2["field_f1"]
        drop = s2_t["field_f1"] - s3_t["field_f1"]
        if gain > 0 and drop <= 0.01:
            winner, why = "sft3", f"hard2 F1 +{gain:.3f}, test F1 change {-drop:+.3f}"
        else:
            why = f"hard2 F1 change {gain:+.3f}, test F1 change {-drop:+.3f} - kept sft2"

    L = ["# Overnight run summary", "", f"**Serving on :8091: `{winner}`** ({why}).", "",
         f"Scores below: `{MODE}` mode from rescore.py (same code for every model). "
         "`hard2` is the fresh held-out set - disjoint names, senders, forms and seeds from all training data.", ""]
    for task, title in (("estate", "Estate test (same generator as v1 training)"),
                        ("estate_hard", "Hard v1 (held out; v3 data shares nothing with it)"),
                        ("estate_hard2", "Hard v2 - FRESH, the unbiased number")):
        L += [f"## {title}", "", "| model | field F1 | critical recall | exact match | grounding |",
              "|---|---|---|---|---|"]
        names = {"estate": ["base4b_0shot", "base32b_0shot", "sft2_0shot", "sft3_0shot"],
                 "estate_hard": ["sft2_hard", "sft3_hard"],
                 "estate_hard2": ["base32b_hard2", "sft2_hard2", "sft3_hard2"]}[task]
        for n in names:
            L.append(row(n, f1(n, task)))
        L.append("")
    L += ["## Energy (results/energy.jsonl)", "", "| run | seconds | mean W | joules |", "|---|---|---|---|"]
    for e in energy():
        L.append(f"| {e['label']} | {e['seconds']} | {e['mean_w']} | {e['joules']} |")
    L += ["", "Joules per document = joules / documents in that run (see the run's report in results/)."]
    (R / "overnight_summary.md").write_text("\n".join(L) + "\n")
    print("\n".join(L))
    print(winner)


if __name__ == "__main__":
    main()

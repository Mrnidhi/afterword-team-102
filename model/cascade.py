"""L2 gate + the full cascade, simulated from measured runs (no model calls).

  L0  bge-small triage on CPU           drop / memory never reach an LLM
  L1  fine-tuned 4B (sft3)              every remaining document
      postprocess.clean                 ungrounded values removed
  L2  per-field confidence gate         field confidence = lowest token probability in its value
      -> uncertain FACT fields          the 32B reads the document; agree = confirmed, disagree = provisional
                                        (policy "verify", the default; "replace" let the 32B overwrite
                                        and measured worse: on hard2 it fixed 5 fields and broke 7)
      -> uncertain ACTION               kept from the 4B (the 32B is worse at judgement), flagged provisional

Gate thresholds are fitted on data/estate/cal.jsonl only (never used for training or testing).
Per field we pick the most permissive threshold whose finite-sample-corrected error among
accepted values on cal is <= ALPHA: (errors + 1) / (accepted + 1) <= ALPHA  (conformal risk control
for a bounded 0/1 loss). The guarantee holds for documents exchangeable with cal (same generator);
on the hard sets it is an empirical result, reported as such.

The 32B re-read here is a WHOLE-document call (its stored predictions); tokens and energy are
counted that way. A cited-lines re-read would be cheaper; that is measured live, not here.

    python cascade.py [--alpha 0.05] [--model sft3]
Writes results/cascade_<policy>.json.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import metrics as M
import schema as S
from evaluate import load, unnumber
from postprocess import clean, ref_last4

HERE = Path(__file__).resolve().parent
R = HERE / "results"
FACTS = ["cat", "inst", "ref", "amt", "kind", "rec", "due"]
GATED = FACTS + ["act"]
POLICY = "verify"          # "verify": 32B confirms or flags; "replace": 32B value wins (measured worse)

# (task, split, 4B eval file, 32B eval file, energy labels for 4B and 32B runs)
SETS = {
    "cal":             ("estate", "cal", None, "base32b_cal", None, "base32b_cal"),
    "estate test":     ("estate", "test", "{m}_0shot", "base32b_energy_test", "{m}_test", "base32b_energy_test"),
    "hard v2 (fresh)": ("estate_hard2", "test", "{m}_hard2", "base32b_hard2", "{m}_hard2", "base32b_hard2"),
}


def _canon(k, v):
    return M.normalise(k, ref_last4(v) if k == "ref" else v)


def correct(k, pred, gold) -> bool:
    return _canon(k, pred.get(k)) == _canon(k, gold.get(k))


def field_confidence(raw: str, tokens: list[dict]) -> dict:
    """Lowest token probability inside each field's value, located by character offsets."""
    spans, pos = [], 0
    for t in tokens:
        spans.append((pos, pos + len(t["t"]), t["lp"])); pos += len(t["t"])
    out = {}
    for k in GATED:
        i = raw.find(f'"{k}":')
        if i < 0:
            continue
        a = i + len(k) + 3
        b = a
        depth = 0
        while b < len(raw) and not (depth == 0 and raw[b] in ",}"):
            depth += raw[b] == "["; depth -= raw[b] == "]"; b += 1
        lps = [lp for s, e, lp in spans if s < b and e > a]
        if lps:
            out[k] = math.exp(min(lps))
    return out


def load_logprobs(model, task, split):
    p = R / f"logprobs_{model}_{task}_{split}.jsonl"
    return {o["id"]: o for o in (json.loads(l) for l in p.read_text().splitlines()) if "error" not in o}


def preds_of(name):
    p = R / f"{name}.json"
    return json.loads(p.read_text())["predictions"] if name and p.exists() else {}


def energy_per_doc(label, n_docs):
    p = R / "energy.jsonl"
    if not label or not p.exists():
        return None
    runs = [json.loads(l) for l in p.read_text().splitlines() if json.loads(l)["label"] == label]
    return runs[-1]["joules"] / n_docs if runs else None


def fit_thresholds(cal_rows, lp, alpha):
    th = {}
    for k in GATED:
        pairs = []
        for r in cal_rows:
            o = lp.get(r["id"])
            if not o:
                continue
            pred = clean(S.parse_output(o["raw"]), unnumber(r["input"])) or {}
            conf = field_confidence(o["raw"], o["tokens"])
            if k in pred and k in conf:
                pairs.append((conf[k], correct(k, pred, r["label"])))
        pairs.sort(key=lambda x: x[0])
        best = 1.0                                   # default: accept nothing unless proven safe
        for i in range(len(pairs)):                  # accept pairs[i:] (confidence >= pairs[i][0])
            acc = pairs[i:]
            err = sum(1 for _, ok in acc if not ok)
            if (err + 1) / (len(acc) + 1) <= alpha:
                best = pairs[i][0]
                break
        th[k] = {"threshold": best, "cal_values": len(pairs), "cal_errors": sum(1 for _, ok in pairs if not ok)}
    return th


def run_set(name, rows, lp, p32, th, triage):
    ext = S.TRIAGE_LABELS.index("extract")
    golds, p4_all, p32_all, pc_all, srcs = [], [], [], [], []
    esc_fields = esc_docs = llm_docs = prov_docs = 0
    tok4 = tok32 = 0
    accepted = accepted_err = 0
    ver_agree = ver_agree_ok = ver_dis = ver_dis_wrong = 0
    for r, route in zip(rows, triage):
        src = unnumber(r["input"]); srcs.append(src); golds.append(r["label"])
        o = lp.get(r["id"])
        if route != "extract" or not o:
            stub = {"cat": "irrelevant" if route == "drop" else "personal"}
            p4_all.append(stub); pc_all.append(stub)
            p32_all.append(S.parse_output(p32.get(r["id"], {}).get("raw", "")) or stub)
            continue
        llm_docs += 1
        tok4 += o["in_tok"] + o["out_tok"]
        p4 = clean(S.parse_output(o["raw"]), src) or {"cat": "irrelevant"}
        big = clean(S.parse_output(p32.get(r["id"], {}).get("raw", "")), src) or {}
        p32_all.append(big or p4); p4_all.append(p4)
        conf = field_confidence(o["raw"], o["tokens"])
        final, escalated, provisional = dict(p4), False, False
        for k in GATED:
            if k not in p4 or k not in conf:
                continue
            if conf[k] >= th[k]["threshold"]:
                accepted += 1; accepted_err += not correct(k, p4, r["label"])
                continue
            if k == "act":
                provisional = True
                continue
            escalated = True; esc_fields += 1
            if POLICY == "verify":                   # 32B checks, never overwrites
                agree = _canon(k, big.get(k)) == _canon(k, p4.get(k))
                ver_agree += agree; ver_agree_ok += agree and correct(k, p4, r["label"])
                ver_dis += not agree; ver_dis_wrong += (not agree) and not correct(k, p4, r["label"])
                provisional |= not agree
            elif k in big:
                final[k] = big[k]
            else:
                final.pop(k, None)
        if escalated:
            esc_docs += 1
            p = p32.get(r["id"], {})
            tok32 += p.get("in_tok", 0) + p.get("out_tok", 0)
        prov_docs += provisional
        pc_all.append(final)

    rep = {}
    for label, preds in (("4B only (L1)", p4_all), ("32B only", p32_all), ("cascade L0+L1+L2", pc_all)):
        e = M.evaluate([dict(p) for p in preds], golds, sources=srcs)
        rep[label] = {k: round(e[k], 4) for k in ("field_f1", "critical_recall", "exact_match", "grounding_rate")}
    n = len(rows)
    all32 = sum(p32.get(r["id"], {}).get("in_tok", 0) + p32.get(r["id"], {}).get("out_tok", 0) for r in rows)
    all4 = sum(lp[r["id"]]["in_tok"] + lp[r["id"]]["out_tok"] for r in rows if r["id"] in lp)
    rep["routing"] = {"documents": n, "skipped_by_L0": n - llm_docs, "sent_to_4B": llm_docs,
                      "escalated_docs": esc_docs, "escalated_fields": esc_fields,
                      "escalation_rate_docs": round(esc_docs / max(1, llm_docs), 4),
                      "action_provisional_docs": prov_docs,
                      "gate_accepted_fields": accepted,
                      "error_rate_among_accepted": round(accepted_err / max(1, accepted), 4),
                      "policy": POLICY}
    if POLICY == "verify":
        rep["routing"].update({"escalated_32B_agrees": ver_agree,
                               "agreed_values_correct": round(ver_agree_ok / max(1, ver_agree), 4),
                               "escalated_32B_disagrees_flagged": ver_dis,
                               "flagged_values_actually_wrong": round(ver_dis_wrong / max(1, ver_dis), 4)})
    rep["tokens_per_doc"] = {"32B only": round(all32 / n, 1), "4B only": round(all4 / n, 1),
                             "cascade (4B + 32B on escalations)": round((tok4 + tok32) / n, 1),
                             "32B tokens in cascade": round(tok32 / n, 1)}
    return rep


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--alpha", type=float, default=0.05)
    ap.add_argument("--model", default="sft3")
    ap.add_argument("--policy", choices=["verify", "replace"], default="verify")
    a = ap.parse_args()
    global POLICY
    POLICY = a.policy
    from l0_triage import Triage
    tri = Triage()

    task, split = SETS["cal"][:2]
    cal_rows = load(task, split)
    th = fit_thresholds(cal_rows, load_logprobs(a.model, task, split), a.alpha)
    out = {"alpha": a.alpha, "model": a.model, "thresholds": th, "sets": {}}
    print(f"gate fitted on cal ({len(cal_rows)} docs), alpha={a.alpha}")
    for k, v in th.items():
        print(f"  {k:5} threshold p>={v['threshold']:.4f}  (cal: {v['cal_values']} values, {v['cal_errors']} wrong)")

    for name, (task, split, _, f32, e4, e32) in SETS.items():
        if name == "cal":
            continue
        try:
            rows = load(task, split)
            lp = load_logprobs(a.model, task, split)
        except FileNotFoundError:
            continue
        triage = [route for route, _ in tri.route_many([unnumber(r["input"]) for r in rows])]
        rep = run_set(name, rows, lp, preds_of(f32), th, triage)
        n = len(rows)
        j4, j32 = energy_per_doc(e4.format(m=a.model), n), energy_per_doc(e32, n)
        if j4 and j32:
            ro = rep["routing"]
            rep["gpu_joules_per_doc_estimate"] = {
                "32B only": round(j32, 2), "4B only": round(j4, 2),
                "cascade": round((ro["sent_to_4B"] * j4 + ro["escalated_docs"] * j32) / n, 2),
                "note": "measured per-document averages from results/energy.jsonl, combined by routing counts"}
        out["sets"][name] = rep
        print(f"\n[{name}] {json.dumps(rep['routing'])}")
        for k in ("32B only", "4B only (L1)", "cascade L0+L1+L2"):
            print(f"  {k:18} {rep[k]}")
        print(f"  tokens/doc {rep['tokens_per_doc']}")
        if "gpu_joules_per_doc_estimate" in rep:
            print(f"  GPU J/doc  {rep['gpu_joules_per_doc_estimate']}")
    out["policy"] = POLICY
    (R / f"cascade_{POLICY}.json").write_text(json.dumps(out, indent=1))
    print(f"\nsaved results/cascade_{POLICY}.json")


if __name__ == "__main__":
    main()

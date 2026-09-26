"""L0 - the retrieval/intake layer. Decides, before any LLM call, what a document is worth.

  drop     irrelevant (newsletters, adverts)  -> never reaches the LLM
  memory   personal writing                   -> Memories tab, never reaches the LLM
  extract  everything else                    -> the 4B

A 33M-parameter embedding model (bge-small-en-v1.5) on the Arm CPU + a logistic-regression head.
Safety rule on top, because a false drop costs a family money and a false keep costs one LLM
call: any document showing a money amount, an account/policy reference or "within N days" is
always sent to the 4B, whatever the classifier says.

    python l0_triage.py            # train on estate v1+v3 train, evaluate on test / hard / hard2
Writes out/l0_triage.joblib and results/l0_triage.json.
"""
from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path

import numpy as np

# Offline by construction: the embedding model is read from the local cache only. Without these
# the Hugging Face libraries contact huggingface.co to check for updates (caught by demo.py's check).
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

import schema as S
from evaluate import load, unnumber

HERE = Path(__file__).resolve().parent
EMBED = "BAAI/bge-small-en-v1.5"
LABELS = S.TRIAGE_LABELS                              # drop, memory, extract

_MONEY = re.compile(r"(\$|USD|EUR|£|€)\s?\d|\d[\d,]*\.\d{2}\b")
_REF = re.compile(r"\b(account|acct|policy|member|loan|case|claim|card|reference|ref)\b[^\n]{0,30}\d{3,}", re.I)
_DAYS = re.compile(r"\bwithin\s+\d+\s+days?\b|\b\d+\s+days?\b", re.I)


def must_extract(text: str) -> bool:
    """The safety rule: documents that show money, a reference or a deadline always go to the LLM."""
    return bool(_MONEY.search(text) or _REF.search(text) or _DAYS.search(text))


class Embedder:
    def __init__(self, device="cpu"):
        import torch
        from transformers import AutoModel, AutoTokenizer
        torch.set_num_threads(os.cpu_count() or 8)
        self.torch, self.device = torch, device
        self.tok = AutoTokenizer.from_pretrained(EMBED)
        self.model = AutoModel.from_pretrained(EMBED).to(device).eval()

    def __call__(self, texts: list[str], bs: int = 64) -> np.ndarray:
        out = []
        with self.torch.no_grad():
            for i in range(0, len(texts), bs):
                b = self.tok(texts[i:i + bs], padding=True, truncation=True, max_length=512,
                             return_tensors="pt").to(self.device)
                cls = self.model(**b).last_hidden_state[:, 0]
                out.append(self.torch.nn.functional.normalize(cls, dim=-1).cpu().numpy())
        return np.concatenate(out)


class Triage:
    """Load once, route many. `route(text)` -> ("drop"|"memory"|"extract", reason)."""

    def __init__(self, path=HERE / "out" / "l0_triage.joblib"):
        import joblib
        self.clf = joblib.load(path)
        self.embed = Embedder()

    def route_many(self, texts: list[str]) -> list[tuple[str, str]]:
        pred = self.clf.predict(self.embed(texts))
        out = []
        for t, p in zip(texts, pred):
            p = LABELS[p]
            if p != "extract" and must_extract(t):
                out.append(("extract", f"classifier said {p}; kept by safety rule"))
            else:
                out.append((p, "classifier"))
        return out


def _rows(task, split):
    rows = load(task, split)
    return [unnumber(r["input"]) for r in rows], [LABELS.index(S.TRIAGE_OF[r["label"]["cat"]]) for r in rows], rows


def _llm_tokens(results_name):
    """Measured prompt+output tokens per document from an evaluation run, by id."""
    p = HERE / "results" / f"{results_name}.json"
    if not p.exists():
        return {}
    return {k: v.get("in_tok", 0) + v.get("out_tok", 0) for k, v in json.loads(p.read_text())["predictions"].items()}


def evaluate_set(clf, emb, name, task, split, tokens_from):
    texts, y, rows = _rows(task, split)
    t0 = time.time()
    X = emb(texts)
    embed_ms = (time.time() - t0) * 1000 / max(1, len(texts))
    raw = clf.predict(X)
    final = [LABELS.index("extract") if LABELS[p] != "extract" and must_extract(t) else p
             for p, t in zip(raw, texts)]
    ext = LABELS.index("extract")
    rep = {"documents": len(y), "embed_ms_per_doc_cpu": round(embed_ms, 1)}
    for tag, pred in (("classifier_only", raw), ("with_safety_rule", final)):
        pred = list(pred)
        per = {}
        for c, lab in enumerate(LABELS):
            tp = sum(1 for p, g in zip(pred, y) if p == c and g == c)
            npred, ngold = sum(1 for p in pred if p == c), sum(1 for g in y if g == c)
            per[lab] = {"precision": round(tp / npred, 4) if npred else None,
                        "recall": round(tp / ngold, 4) if ngold else None, "gold": ngold}
        false_drops = [r["id"] for p, g, r in zip(pred, y, rows) if g == ext and p != ext]
        rep[tag] = {"per_class": per, "accuracy": round(sum(p == g for p, g in zip(pred, y)) / len(y), 4),
                    "skip_llm_share": round(sum(p != ext for p in pred) / len(y), 4),
                    "money_docs_wrongly_skipped": len(false_drops), "false_drop_ids": false_drops[:10]}
    toks = _llm_tokens(tokens_from)
    if toks:
        skipped = [r["id"] for p, r in zip(final, rows) if p != ext]
        total = sum(toks.get(r["id"], 0) for r in rows)
        saved = sum(toks.get(i, 0) for i in skipped)
        rep["llm_tokens_measured"] = {"from": tokens_from, "total_without_L0": total, "saved_by_L0": saved,
                                      "saved_share": round(saved / total, 4) if total else None}
    print(f"\n[{name}] {len(y)} docs | embed {embed_ms:.1f} ms/doc on CPU")
    for tag in ("classifier_only", "with_safety_rule"):
        r = rep[tag]
        print(f"  {tag:17} acc {r['accuracy']:.3f} | skip LLM {r['skip_llm_share']:.1%} | "
              f"money docs wrongly skipped {r['money_docs_wrongly_skipped']} | "
              + "  ".join(f"{k}: P {v['precision']} R {v['recall']}" for k, v in r["per_class"].items()))
    if toks:
        m = rep["llm_tokens_measured"]
        print(f"  LLM tokens saved {m['saved_by_L0']:,} of {m['total_without_L0']:,} ({m['saved_share']:.1%})")
    return rep


def main():
    import joblib
    from sklearn.linear_model import LogisticRegression

    emb = Embedder()
    tr_texts, tr_y = [], []
    for task, split in (("estate", "train"),):
        t, y, _ = _rows(task, split); tr_texts += t; tr_y += y
    v3 = HERE / "data" / "estate_v3" / "train.jsonl"
    if v3.exists():
        for r in (json.loads(l) for l in v3.read_text().splitlines()):
            tr_texts.append(unnumber(r["input"])); tr_y.append(LABELS.index(S.TRIAGE_OF[r["label"]["cat"]]))
    t0 = time.time()
    Xtr = emb(tr_texts)
    clf = LogisticRegression(max_iter=2000, C=4.0, class_weight="balanced").fit(Xtr, tr_y)
    print(f"trained on {len(tr_y)} docs in {time.time() - t0:.0f}s (embedding on CPU included)")
    (HERE / "out").mkdir(exist_ok=True)
    joblib.dump(clf, HERE / "out" / "l0_triage.joblib")

    report = {"embedder": EMBED, "head": "logistic regression", "train_docs": len(tr_y), "sets": {}}
    for name, task, split, tok in (("estate test", "estate", "test", "sft3_0shot"),
                                   ("hard v1", "estate_hard", "test", "sft3_hard"),
                                   ("hard v2 (fresh)", "estate_hard2", "test", "sft3_hard2")):
        try:
            report["sets"][name] = evaluate_set(clf, emb, name, task, split, tok)
        except FileNotFoundError:
            continue
    (HERE / "results" / "l0_triage.json").write_text(json.dumps(report, indent=1))
    print("\nsaved out/l0_triage.joblib, results/l0_triage.json")


if __name__ == "__main__":
    main()

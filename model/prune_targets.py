"""Remove label values that are not present in the input text.

Why: on the public invoice set only 77% of ground-truth values actually appear in the OCR we
produced (annotations come from the source PDFs, our input is OCR of the rendered page). Asking a
model to copy values it cannot see teaches it to give up - our first fine-tune learned to answer
`{}` for every invoice. We keep only what is answerable, and drop documents left with nothing.

    python prune_targets.py --dry-run
    python prune_targets.py

Rewrites data/public/*.jsonl in place (originals saved to *.raw.jsonl once).
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
from pathlib import Path

HERE = Path(__file__).resolve().parent
PUB = HERE / "data" / "public"
_NUM_PREFIX = re.compile(r"^\d+\| ", re.M)


def squash(s) -> str:
    return "".join(c for c in str(s).casefold() if c.isalnum())


def prune(obj, hay: str):
    """Keep only leaves whose value appears in hay. Returns None if nothing survives."""
    if isinstance(obj, dict):
        out = {k: v for k, v in ((k, prune(v, hay)) for k, v in obj.items()) if v is not None}
        return out or None
    if isinstance(obj, list):
        out = [v for v in (prune(v, hay) for v in obj) if v is not None]
        return out or None
    s = squash(obj)
    return obj if s and s in hay else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    for split in ("train", "val", "test"):
        path = PUB / f"{split}.jsonl"
        raw = PUB / f"{split}.raw.jsonl"
        if not raw.exists() and not a.dry_run:
            shutil.copy(path, raw)                       # keep the originals, once
        src = raw if raw.exists() else path
        rows = [json.loads(l) for l in open(src)]

        kept, dropped, before, after = [], 0, 0, 0
        for r in rows:
            hay = squash(_NUM_PREFIX.sub("", r["input"]))
            tgt = json.loads(r["target"])
            new = prune(tgt, hay) if r["task"] != "estate" else tgt
            before += len(json.dumps(tgt))
            if not new:
                dropped += 1
                continue
            after += len(json.dumps(new))
            r["target"] = json.dumps(new, separators=(",", ":"), ensure_ascii=False)
            kept.append(r)

        print(f"{split:<6} {len(rows):>5} -> {len(kept):>5} docs  "
              f"({dropped} left with no answerable value)   target chars {before:,} -> {after:,}")
        if not a.dry_run:
            with open(path, "w") as f:
                for r in kept:
                    f.write(json.dumps(r, ensure_ascii=False) + "\n")

    if not a.dry_run:
        card = PUB / "card.json"
        c = json.loads(card.read_text())
        c["pruning"] = ("Targets reduced to values present in our OCR text. Originals kept as "
                        "*.raw.jsonl. Reason: 23% of invoice ground-truth values are absent from "
                        "the OCR, and training on them taught the model to answer {}.")
        card.write_text(json.dumps(c, indent=2, ensure_ascii=False))
        print("\nupdated data/public/card.json")


if __name__ == "__main__":
    main()

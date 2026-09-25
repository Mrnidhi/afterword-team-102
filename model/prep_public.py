"""Step 2: build the public training/benchmark data, with OCR done on hp24.

Sources (licences checked on the dataset cards):
  CORD-v2 receipts        naver-clova-ix/cord-v2               CC-BY-4.0
  invoices                katanaml-org/invoices-donut-data-v1  MIT
                          (from Kozłowski & Weichbroth 2021, "Samples of electronic invoices",
                           Mendeley Data, doi:10.17632/tnj49gpmtz.2)

We deliberately do NOT use mychen76/invoices-and-receipts_ocr_v1: it declares no licence.
Instead we take the MIT images and run our own OCR (RapidOCR, Apache-2.0) on the Arm CPU
cores, in parallel, while the GPU stays free.

    python prep_public.py --limit 10     # quick check
    python prep_public.py                # full build (~2-3 min)
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import time
from multiprocessing import Pool
from pathlib import Path

os.environ.setdefault("OMP_NUM_THREADS", "1")            # one core per OCR worker

HERE = Path(__file__).resolve().parent
OUT = HERE / "data" / "public"

INVOICE_DS = "katanaml-org/invoices-donut-data-v1"
CORD_DS = "naver-clova-ix/cord-v2"
SPLITS = {INVOICE_DS: {"train": "train", "validation": "val", "test": "test"},
          CORD_DS: {"train": "train", "validation": "val", "test": "test"}}

SYSTEM = {
    "invoice": (
        "You read the OCR text of one invoice (numbered lines) and return ONE compact JSON "
        "object, nothing else, with this shape: "
        '{"header":{"invoice_no","invoice_date","seller","client","seller_tax_id",'
        '"client_tax_id","iban"},"summary":{"total_net_worth","total_vat","total_gross_worth"}}. '
        "Copy values as printed, correcting obvious OCR spacing. Omit keys that are absent."),
    "cord": (
        "You read the OCR text of one shop receipt (numbered lines) and return ONE compact JSON "
        "object, nothing else, in the CORD format: "
        '"menu" (list of items with nm, cnt, price, and optional unitprice, discountprice, sub), '
        '"sub_total" (subtotal_price, discount_price, service_price, tax_price, etc) and '
        '"total" (total_price, cashprice, changeprice, creditcardprice, menuqty_cnt, etc). '
        "Copy values as printed. Omit keys that are absent."),
}

_OCR = None


def _ocr_engine():
    global _OCR
    if _OCR is None:
        from rapidocr_onnxruntime import RapidOCR
        try:
            _OCR = RapidOCR(intra_op_num_threads=1, inter_op_num_threads=1)
        except TypeError:
            _OCR = RapidOCR()
    return _OCR


def group_lines(result) -> list[str]:
    """RapidOCR boxes -> reading-order text lines. Boxes whose vertical centres are
    within half a line height share a line, and are joined left to right."""
    if not result:
        return []
    boxes = []
    for pts, text, _score in result:
        ys = [p[1] for p in pts]; xs = [p[0] for p in pts]
        boxes.append(((min(ys) + max(ys)) / 2, max(ys) - min(ys), min(xs), text))
    boxes.sort(key=lambda b: b[0])
    h = statistics.median(b[1] for b in boxes) or 10
    lines, cur = [], [boxes[0]]
    for b in boxes[1:]:
        if abs(b[0] - cur[-1][0]) <= 0.5 * h:
            cur.append(b)
        else:
            lines.append(cur); cur = [b]
    lines.append(cur)
    return [" ".join(t for *_, t in sorted(l, key=lambda b: b[2])) for l in lines]


def _ocr_job(args):
    ds_name, split, idx = args
    from datasets import load_dataset
    ds = _ocr_job.cache.get((ds_name, split))
    if ds is None:
        ds = load_dataset(ds_name, split=split)
        _ocr_job.cache[(ds_name, split)] = ds
    row = ds[idx]
    t0 = time.time()
    res, _ = _ocr_engine()(row["image"].convert("RGB"))
    return ds_name, split, idx, group_lines(res), time.time() - t0, row["ground_truth"]
_ocr_job.cache = {}


def compact(obj) -> str:
    return json.dumps(obj, separators=(",", ":"), ensure_ascii=False)


def build_target(ds_name: str, gt_json: str) -> tuple[str, dict]:
    gt = json.loads(gt_json)["gt_parse"]
    if ds_name == INVOICE_DS:
        keep = {k: gt[k] for k in ("header", "summary") if k in gt}   # line items dropped: see card
        return "invoice", keep
    return "cord", gt


def answerability(target: dict, text: str) -> tuple[int, int]:
    """How many ground-truth values appear in our OCR text (spacing-insensitive).
    This is the ceiling a text-only model can reach on this data."""
    from metrics import flatten
    squash = lambda s: "".join(ch for ch in str(s).casefold() if ch.isalnum())
    hay = squash(text)
    vals = [v for _, v in flatten(target)]
    return sum(1 for v in vals if squash(v) and squash(v) in hay), len(vals)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="per split, for a quick check")
    ap.add_argument("--workers", type=int, default=18)
    a = ap.parse_args()

    import schema as S
    from datasets import load_dataset
    from transformers import AutoTokenizer

    jobs = []
    for ds_name, splits in SPLITS.items():
        for src_split in splits:
            n = len(load_dataset(ds_name, split=src_split))
            n = min(n, a.limit) if a.limit else n
            jobs += [(ds_name, src_split, i) for i in range(n)]
    print(f"OCR on {len(jobs)} pages with {a.workers} Arm-core workers ...", flush=True)

    t0 = time.time()
    results = []
    with Pool(a.workers) as pool:
        for k, r in enumerate(pool.imap_unordered(_ocr_job, jobs, chunksize=4), 1):
            results.append(r)
            if k % 50 == 0 or k == len(jobs):
                print(f"  {k}/{len(jobs)} pages  ({time.time() - t0:.0f}s)", flush=True)
    wall = time.time() - t0

    tok = AutoTokenizer.from_pretrained("Qwen/Qwen3-4B-Instruct-2507")
    OUT.mkdir(parents=True, exist_ok=True)
    by_split = {"train": [], "val": [], "test": []}
    stats = {}
    for ds_name, src_split, idx, lines, secs, gt in sorted(results, key=lambda r: (r[0], r[1], r[2])):
        task, target = build_target(ds_name, gt)
        text = "\n".join(lines)
        if not text.strip():
            continue
        found, total = answerability(target, text)
        rec = {"id": f"{task}-{src_split}-{idx:04d}", "task": task,
               "split": SPLITS[ds_name][src_split], "system": SYSTEM[task],
               "input": S.number_lines(text), "n_lines": len(lines),
               "target": compact(target), "ocr_seconds": round(secs, 2),
               "answerable": [found, total]}
        by_split[rec["split"]].append(rec)
        st = stats.setdefault(task, {"docs": Counter_(), "in_tok": [], "out_tok": [],
                                     "found": 0, "total": 0})
        st["docs"][rec["split"]] += 1
        st["in_tok"].append(len(tok(rec["input"])["input_ids"]))
        st["out_tok"].append(len(tok(rec["target"])["input_ids"]))
        st["found"] += found; st["total"] += total

    for split, recs in by_split.items():
        with open(OUT / f"{split}.jsonl", "w") as f:
            for r in recs:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")

    def dist(v):
        v = sorted(v)
        return {"mean": round(statistics.mean(v)), "p95": v[int(0.95 * (len(v) - 1))], "max": v[-1]}

    card = {
        "built": time.strftime("%Y-%m-%d %H:%M:%S"),
        "sources": {
            "cord": {"dataset": CORD_DS, "license": "CC-BY-4.0"},
            "invoice": {"dataset": INVOICE_DS, "license": "MIT",
                        "origin": "Kozłowski & Weichbroth (2021), Samples of electronic invoices, "
                                  "Mendeley Data, doi:10.17632/tnj49gpmtz.2"},
            "excluded": {"mychen76/invoices-and-receipts_ocr_v1": "no licence declared"},
        },
        "ocr": {"engine": "RapidOCR (Apache-2.0), ONNX Runtime on CPU", "pages": len(results),
                "workers": a.workers, "wall_seconds": round(wall, 1),
                "pages_per_second": round(len(results) / wall, 2),
                "mean_seconds_per_page": round(statistics.mean(r[4] for r in results), 2)},
        "decisions": ["invoice line items dropped: header + summary only, to keep outputs short",
                      "CORD kept in full native gt_parse format"],
        "tasks": {t: {"docs": dict(s["docs"]), "input_tokens": dist(s["in_tok"]),
                      "target_tokens": dist(s["out_tok"]),
                      "answerable_values": f"{s['found']}/{s['total']} "
                                           f"({s['found'] / max(1, s['total']):.1%})"}
                  for t, s in stats.items()},
    }
    (OUT / "card.json").write_text(json.dumps(card, indent=2, ensure_ascii=False))
    print(json.dumps(card, indent=2, ensure_ascii=False))


from collections import Counter as Counter_

if __name__ == "__main__":
    main()

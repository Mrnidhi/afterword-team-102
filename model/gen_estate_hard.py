"""A deliberately DIFFERENT estate test set, to answer "did you just memorise your own data?"

Everything that could let a model match on surface form is changed from gen_estate.py:

  institutions   a different name pool entirely (no Summit/Harbor/... prefixes)
  people         different first and last names
  wording        the teacher is told to write like a specific real-world sender, not
                 "a {category} organisation", and is given no layout/tone vocabulary in common
  structure      forwarded email threads, quoted replies, letters with page furniture
                 (page numbers, reference footers), SMS with shortlinks and typos
  noise          heavier OCR corruption, applied to letters AND scanned-email lines
  absence        ~25% of documents deliberately omit a field the model usually sees,
                 so "not stated" has to be learned rather than guessed
  labels         still correct by construction: code picks the facts, code verifies them

Run this only AFTER training, against the same served model as the normal test set.

    python gen_estate_hard.py --n 400
    python gen_estate_hard.py --finalize
"""
from __future__ import annotations

import argparse
import json
import random
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests

import schema as S
from gen_estate import REF_LABEL, money_str, squash, verify, OCR_SWAPS
from trainlog import RunLogger

HERE = Path(__file__).resolve().parent
OUT = HERE / "data" / "estate_hard"
RUN = HERE / "runs" / "gen_estate_hard"
ENDPOINT = "http://127.0.0.1:8090/v1/chat/completions"

# ---------------------------------------------------------------- disjoint name pools

FIRST = ["Yusuf", "Bridget", "Hiroshi", "Camila", "Otto", "Nadia", "Emeka", "Sylvie",
         "Arjun", "Greta", "Tomas", "Leilani", "Magnus", "Farida", "Dmitri", "Aroha"]
LAST = ["Brennan-Ito", "Vasquez", "Oyelaran", "Petrakis", "Lindgren", "Abubakar", "Costa e Silva",
        "Mbeki", "Ferraro", "Haugen", "Sandoval", "Kirchner", "Thorne", "Bakshi"]

BANKS = ["First Meridian Trust Co.", "Ironbridge Savings", "Coastal Federal Bank",
         "Tri-County Mutual", "Halcyon National Bank"]
CARDS = ["Vantage Card Services", "BlueLine Card Center", "Apex Cardmember Services"]
INSURERS = ["Old Dominion Life", "Provident Assurance Co.", "Kestrel Life & Legacy",
            "United Heritage Insurance"]
PENSIONS = ["Bricklayers & Allied Craftworkers Local 88 Annuity Plan",
            "Municipal Employees' Retirement System", "Longshore Workers Welfare Trust"]
BROKERS = ["Ashford Wealth Partners", "Sentinel Asset Management", "Blue Harbor Investments"]
LENDERS = ["Anchor Point Mortgage", "Clearwater Auto Finance", "Fairline Lending Group"]
UTILS = ["Municipal Light & Power", "Regional Water Authority", "Northstar Energy Co-op"]
SUBS = ["Bramble Box", "Verso Reader", "TrailKit", "Nocturne Audio", "Sprig Meal Plan",
        "Atlas Maps Pro", "Bellwether Wine Club"]
CLINICS = ["Mercy Sisters Hospital", "Lakeshore Orthopedics", "Piedmont Family Practice"]
GOVS = ["Bureau of Vital Statistics", "Office of the State Treasurer", "County Probate Registry"]
LEGAL = ["Whitcombe, Serrano & Ng LLP", "Office of the Public Administrator",
         "Probate Division, Third Judicial Circuit"]
PROPERTY = ["Cedar Point Self Storage", "Harbourview HOA", "Township Assessor's Office"]

POOL = {"bank": BANKS, "credit_card": CARDS, "insurance": INSURERS, "retirement": PENSIONS,
        "investment": BROKERS, "loan": LENDERS, "utility": UTILS, "subscription": SUBS,
        "medical": CLINICS, "government": GOVS, "legal": LEGAL, "property": PROPERTY}

# Senders described concretely, so the teacher writes in a different register than in training.
SENDER = {
    "bank": "a bank's estate services team", "credit_card": "a card issuer's account closure unit",
    "insurance": "a life insurer's claims department", "retirement": "a union pension fund administrator",
    "investment": "a brokerage transfer-on-death desk", "loan": "a lender's collections and estates group",
    "utility": "a utility company's billing office", "subscription": "an automated subscription billing system",
    "medical": "a hospital patient-accounts office", "government": "a state benefits agency",
    "legal": "a probate court clerk or estate attorney", "property": "a storage facility or assessor's office",
}

FORMS = {
    "email": ["a forwarded email thread where the original message is quoted below with > marks",
              "an automated no-reply email with a footer of legal boilerplate",
              "a short email reply in an ongoing thread, starting mid-conversation"],
    "sms": ["a text message with a shortened link and no punctuation",
            "a two-part text message split across a line break",
            "a terse automated alert with abbreviations"],
    "letter": ["a scanned letter with a page number and a reference code in the footer",
               "a letter on a form template with field labels in capitals and dotted lines",
               "a second-notice letter that refers to an earlier unanswered letter"],
}

CATEGORY_WEIGHTS = {"irrelevant": 14, "personal": 8, "bank": 8, "credit_card": 7, "insurance": 8,
                    "retirement": 8, "investment": 6, "loan": 6, "utility": 7, "subscription": 8,
                    "medical": 7, "government": 5, "legal": 4, "property": 4}
OMIT_RATE = 0.25          # documents that deliberately leave a usual field unstated


def _amt(lo, hi, rnd):
    v = rnd.uniform(lo, hi)
    return round(v, 2) if rnd.random() < 0.75 else float(int(v))


def sample_facts(cat: str, rnd: random.Random):
    """Same label semantics as training, different value ranges and reference formats."""
    f = {"cat": cat}
    extra = []
    if cat in ("irrelevant", "personal"):
        return f, extra
    f["inst"] = rnd.choice(POOL[cat])
    if cat == "insurance":
        f["ref"] = rnd.choice([f"{rnd.randint(10,99)}-{rnd.randint(100000,999999)}",
                               f"WL{rnd.randint(1000000,9999999)}"])
    elif cat == "legal":
        f["ref"] = f"{rnd.randint(2024,2026)}-PR-{rnd.randint(1000,9999)}"
    else:
        f["ref"] = str(rnd.randint(1000, 9999))

    if cat == "bank":
        f.update(amt=_amt(15, 120000, rnd), kind="balance", act="claim")
    elif cat == "credit_card":
        f.update(amt=_amt(12, 14000, rnd), kind="due", act="close")
        if rnd.random() < 0.6: f["due"] = rnd.choice([20, 28, 45])
    elif cat == "insurance":
        lapsed = rnd.random() < 0.25
        f.update(amt=float(rnd.choice([5000, 15000, 75000, 150000, 300000, 750000])),
                 kind="face_value", act="review" if lapsed else "claim")
        if lapsed: extra.append("lapsed")
        elif rnd.random() < 0.6: f["due"] = rnd.choice([60, 120, 730])
    elif cat == "retirement":
        f.update(amt=_amt(250, 7000, rnd), kind="benefit", rec="monthly", act="stop_payment",
                 due=rnd.choice([14, 45, 90]))
    elif cat == "investment":
        f.update(amt=_amt(500, 1500000, rnd), kind="balance", act="transfer")
    elif cat == "loan":
        f.update(amt=_amt(90, 6500, rnd), kind="due", rec="monthly", act="notify",
                 due=rnd.choice([10, 20, 60]))
    elif cat == "utility":
        f.update(amt=_amt(8, 900, rnd), kind="due", act="transfer", due=rnd.choice([7, 28, 45]))
    elif cat == "subscription":
        f.update(amt=round(rnd.choice([1.99, 3.49, 7.99, 11.50, 24.00, 39.99, 129.0]), 2),
                 kind="charge", rec=rnd.choice(["monthly", "annual", "quarterly"]), act="cancel")
    elif cat == "medical":
        f.update(amt=_amt(15, 48000, rnd), kind="due", act="verify_debt", due=rnd.choice([21, 45, 120]))
    elif cat == "government":
        if rnd.random() < 0.5:
            f.update(amt=_amt(150, 5200, rnd), kind="benefit", rec="monthly", act="notify", due=30)
        else:
            f.update(amt=_amt(25, 12000, rnd), kind="balance", act="claim")
    elif cat == "legal":
        f.update(act="review")
        if rnd.random() < 0.6: f["due"] = rnd.choice([21, 35, 90])
    elif cat == "property":
        f.update(amt=_amt(20, 15000, rnd), kind="due", act="review", due=rnd.choice([10, 28, 60]))

    # Deliberately omit a field that is usually present: the model must not hallucinate it.
    if rnd.random() < OMIT_RATE:
        for k in ("due", "amt", "ref"):
            if k in f and not (k == "amt" and f.get("kind") == "face_value"):
                if k == "amt":
                    f.pop("kind", None); f.pop("rec", None)
                f.pop(k)
                break
    return f, extra


def build_prompt(f, extra, channel, decedent, rnd):
    must = {}
    form = rnd.choice(FORMS[channel])
    if f["cat"] == "irrelevant":
        topic = rnd.choice(["a conference registration reminder", "a charity appeal",
                            "a software update notice", "a book club schedule",
                            "a parking permit renewal advert", "a garden centre voucher"])
        return (f"Write {form}, about {topic}, addressed to {decedent}. "
                f"It must not mention money owed, accounts, policies or a death. "
                f"Output only the message."), must
    if f["cat"] == "personal":
        topic = rnd.choice(["a condolence note from a former colleague",
                            "a handwritten-style note about a shared holiday",
                            "a grandchild's thank-you letter", "a note enclosing a photograph"])
        return (f"Write {form}, which is {topic}, addressed to or about {decedent}. "
                f"Warm, personal, no money or accounts. Output only the message."), must

    must["inst"] = f["inst"]
    parts = [f"the sender is {f['inst']} (write the name exactly)"]
    if "ref" in f:
        must["ref"] = f["ref"]
        parts.append(f"quote the {REF_LABEL[f['cat']]} {f['ref']} exactly")
    if "amt" in f:
        must["amt"] = money_str(f["amt"])
        rec = f.get("rec")
        per = f"{rec} " if rec and rec != "none" else ""
        role = {"balance": "the balance held", "due": f"the {per}amount outstanding",
                "charge": f"the {per}charge", "benefit": f"the {per}payment issued",
                "face_value": "the sum assured"}[f["kind"]]
        parts.append(f"state {role} as exactly {must['amt']}")
    if "due" in f:
        must["due"] = f"{f['due']} days"
        parts.append(f"state that a response is needed within exactly {must['due']}")
    for e in extra:
        must[e] = e
        parts.append(f"state plainly that the policy has {e}")
    if f["cat"] == "retirement":
        parts.append("mention that payments issued after the date of death are recoverable")
    if f["cat"] == "subscription":
        parts.append("mention that it renews automatically until cancelled")

    return (f"Write {form}, from {SENDER[f['cat']]}, concerning the estate of {decedent}. "
            f"Include these facts, worded naturally, with names and numbers exactly as given: "
            + "; ".join(parts) + ". Mention no other monetary amounts and no other time periods "
            "in days. Do not restate these instructions. Output only the message itself."), must


def heavy_noise(line: str, rnd: random.Random) -> str:
    """More aggressive than training: joins, splits and character confusions."""
    if rnd.random() < 0.35:
        line = line.replace(" ", "", 1)
    if rnd.random() < 0.2 and len(line) > 12:
        i = rnd.randrange(6, len(line) - 4)
        line = line[:i] + " " + line[i:]
    for a, b in rnd.sample(OCR_SWAPS, 3):
        if a in line and rnd.random() < 0.6:
            i = line.index(a)
            line = line[:i] + b + line[i + len(a):]
    return line


def finalise(text, f, must, channel, rnd):
    text = text.replace("**", "").replace("__", "")
    lines = [re.sub(r"^#+\s*", "", l.rstrip()) for l in text.strip().splitlines() if l.strip()]
    fact_idx = {i for i, l in enumerate(lines)
                if any(squash(v) and squash(v) in squash(l) for v in must.values())}
    if channel in ("letter", "email") and rnd.random() < 0.7:
        lines = [l if i in fact_idx else heavy_noise(l, rnd) for i, l in enumerate(lines)]
    label = dict(f)
    if fact_idx:
        label["ev"] = sorted(i + 1 for i in fact_idx)
    return "\n".join(lines), label


def plan_item(i: int) -> dict:
    rnd = random.Random(900000 + i)              # disjoint from the training seeds
    cat = rnd.choices(list(CATEGORY_WEIGHTS), weights=list(CATEGORY_WEIGHTS.values()))[0]
    channel = rnd.choices(["email", "sms", "letter"], weights=[0.4, 0.25, 0.35])[0]
    decedent = f"{rnd.choice(FIRST)} {rnd.choice(LAST)}"
    f, extra = sample_facts(cat, rnd)
    prompt, must = build_prompt(f, extra, channel, decedent, rnd)
    return {"i": i, "f": f, "channel": channel, "prompt": prompt, "must": must}


def call(prompt, model, seed):
    r = requests.post(ENDPOINT, timeout=600, json={
        "model": model, "messages": [{"role": "user", "content": prompt}],
        "temperature": 1.0, "top_p": 0.97, "max_tokens": 340, "seed": seed,
        "chat_template_kwargs": {"enable_thinking": False}})
    r.raise_for_status()
    j = r.json()
    return j["choices"][0]["message"]["content"], j.get("usage", {}).get("completion_tokens", 0)


def make_item(plan, model):
    i, f, must = plan["i"], plan["f"], plan["must"]
    text, ntok = call(plan["prompt"], model, 900000 + i)
    missing = verify(text, must)
    if missing:
        return {"i": i, "ok": False, "missing": missing, "tokens": ntok, "cat": f["cat"]}
    text, label = finalise(text, f, must, plan["channel"], random.Random(700000 + i))
    return {"i": i, "ok": True, "tokens": ntok, "rec": {
        "id": f"hard-{i:05d}", "task": "estate", "channel": plan["channel"], "split": "hard",
        "system": S.SYSTEM_PROMPT, "input": S.number_lines(text), "n_lines": S.line_count(text),
        "target": S.to_target(label), "label": label}}


def finalize():
    from collections import Counter
    rows = [json.loads(l) for l in (OUT / "raw.jsonl").read_text().splitlines()]
    good = [r["rec"] for r in rows if r["ok"]]
    good.sort(key=lambda r: r["id"])
    with open(OUT / "test.jsonl", "w") as fh:
        for r in good:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    card = {
        "purpose": "Held-out generalisation test. Different name pools, senders, document forms, "
                   "heavier OCR noise, and 25% of documents deliberately omit a usual field.",
        "generated": len(rows), "accepted": len(good),
        "accept_rate": round(len(good) / max(1, len(rows)), 3),
        "by_category": dict(sorted(Counter(r["label"]["cat"] for r in good).items())),
        "by_channel": dict(Counter(r["channel"] for r in good)),
        "docs_with_a_field_omitted": sum(
            1 for r in good if r["label"]["cat"] not in ("irrelevant", "personal")
            and not all(k in r["label"] for k in ("ref", "amt"))),
        "shares_nothing_with_training": ["institution names", "person names", "prompt wording",
                                         "document forms", "random seeds"],
    }
    (OUT / "card.json").write_text(json.dumps(card, indent=2, ensure_ascii=False))
    print(json.dumps(card, indent=2, ensure_ascii=False))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=400)
    ap.add_argument("--concurrency", type=int, default=96)
    ap.add_argument("--finalize", action="store_true")
    a = ap.parse_args()
    if a.finalize:
        finalize(); return

    OUT.mkdir(parents=True, exist_ok=True)
    raw = OUT / "raw.jsonl"
    done = {json.loads(l)["i"] for l in raw.read_text().splitlines()} if raw.exists() else set()
    todo = [i for i in range(a.n) if i not in done]
    model = requests.get(ENDPOINT.replace("/chat/completions", "/models"),
                         timeout=10).json()["data"][0]["id"]
    print(f"teacher {model} | {len(done)} done, {len(todo)} to generate", flush=True)

    log = RunLogger(RUN, total_steps=a.n, start_step=len(done),
                    config={"kind": "hard_estate_generation", "n": a.n, "teacher": model},
                    alerts={"collapse_loss": -1})
    t0, toks, ok, bad = time.time(), 0, 0, 0
    with open(raw, "a") as fout, ThreadPoolExecutor(a.concurrency) as pool:
        plans = [plan_item(i) for i in todo]
        futs = [pool.submit(make_item, p, model) for p in plans]
        for k, fu in enumerate(as_completed(futs), 1):
            try:
                r = fu.result()
            except Exception as e:
                log.alert("WARN", f"{type(e).__name__}: {str(e)[:120]}"); continue
            fout.write(json.dumps(r, ensure_ascii=False) + "\n"); fout.flush()
            toks += r["tokens"]; ok += r["ok"]; bad += not r["ok"]
            if k % 20 == 0 or k == len(todo):
                log.log(len(done) + k, tokens_per_sec=toks / (time.time() - t0),
                        accept_rate=ok / max(1, ok + bad))
            if log.should_stop():
                for x in futs:
                    x.cancel()
                break
    log.close()
    print(f"\n{ok} accepted, {bad} rejected in {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()

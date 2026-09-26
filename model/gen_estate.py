"""Step 3: estate documents written by the 32B teacher, with labels correct by construction.

Facts first, prose second:
  1. Code samples the facts (category, institution, reference, amount, deadline, action).
     That IS the label - the LLM never produces a label, so there is no label noise.
  2. The 32B (served by ZRT/vLLM on hp24) writes an email, SMS or letter containing them,
     in a randomly chosen tone and layout.
  3. Code verifies every fact appears in the text. Anything missing is discarded.
  4. Code finds the evidence lines and, for scanned letters, adds OCR-style noise to
     lines that carry no facts (so every label stays recoverable).

Uses the same run logging as training: watch with `python monitor.py gen_estate`,
stop safely with `--stop`, and re-running continues where it left off.

    python gen_estate.py --n 20                   # quick check
    python gen_estate.py --n 1800                 # full build (~30-45 min)
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
from trainlog import RunLogger

HERE = Path(__file__).resolve().parent
OUT = HERE / "data" / "estate"
RUN = HERE / "runs" / "gen_estate"
ENDPOINT = "http://127.0.0.1:8090/v1/chat/completions"

# ----------------------------------------------------------------- invented names only

FIRST = ["Robert", "Margaret", "James", "Elena", "Thomas", "Grace", "Daniel", "Anita", "Walter",
         "Lucia", "Harold", "Mei", "Samuel", "Irene", "Victor", "Priya", "George", "Rosa"]
LAST = ["Chen", "Okafor", "Marchetti", "Halloran", "Nguyen", "Barros", "Whitfield", "Rao",
        "Lindqvist", "Adeyemi", "Kowalski", "Tanaka", "Moreau", "Delgado", "Fitzgerald"]
PRE = ["Summit", "Harbor", "Pinecrest", "Redwood", "Meridian", "Cascade", "Northgate", "Lumen",
       "Beacon", "Crescent", "Evergreen", "Silverline", "Granite", "Bayview", "Oakridge", "Juniper"]
COUNTIES = ["Alder", "Brightwater", "Calloway", "Denton Hills", "Emberly", "Fairhaven"]
SUBS = ["Streamwave", "FitPulse Premium", "CloudVault", "NewsFold Plus", "MealCrate", "Readly Box",
        "PuzzleNest", "SoundLoft Music", "Pawprint Pet Club", "LensDaily"]

# category -> (institution builder, fact rules)
def _inst(cat):
    p = random.choice(PRE)
    return {
        "bank": f"{p} {random.choice(['Credit Union', 'Savings Bank', 'Community Bank'])}",
        "credit_card": f"{p} Card Services",
        "insurance": f"{p} {random.choice(['Life Assurance', 'Mutual Life', 'Life & Annuity'])}",
        "retirement": f"{p} {random.choice(['Pension Fund', 'Retirement System'])}",
        "investment": f"{p} {random.choice(['Securities', 'Investments', 'Brokerage'])}",
        "loan": f"{p} {random.choice(['Home Loans', 'Auto Finance', 'Lending'])}",
        "utility": f"{p} {random.choice(['Electric', 'Water District', 'Gas & Power'])}",
        "subscription": random.choice(SUBS),
        "medical": f"{p} {random.choice(['Medical Center', 'Health Clinic', 'Radiology Group'])}",
        "government": random.choice(["State Benefits Agency", "County Tax Collector",
                                     "Department of Revenue"]),
        "legal": random.choice([f"Superior Court of {random.choice(COUNTIES)} County",
                                f"{random.choice(LAST)} & {random.choice(LAST)} LLP"]),
        "property": random.choice([f"{p} SecureSpace Storage",
                                   f"{random.choice(COUNTIES)} County Assessor"]),
    }[cat]


def _amt(lo, hi):
    v = random.uniform(lo, hi)
    return round(v, 2) if random.random() < 0.8 else float(int(v))


def sample_facts(cat: str) -> tuple[dict, list[str]]:
    """Returns (label, extra required phrases). Rules mirror how an executor would act."""
    f = {"cat": cat}
    extra = []
    if cat in ("irrelevant", "personal"):
        return f, extra
    f["inst"] = _inst(cat)
    f["ref"] = (f"{random.choice(['P', 'LP', 'POL'])}-{random.randint(100000, 999999)}"
                if cat == "insurance" else str(random.randint(1000, 9999)))
    r = random.random
    if cat == "bank":
        f.update(amt=_amt(40, 85000), kind="balance", act="claim")
    elif cat == "credit_card":
        f.update(amt=_amt(20, 9000), kind="due", act="close")
        if r() < 0.6: f["due"] = random.choice([21, 25, 30])
    elif cat == "insurance":
        lapsed = r() < 0.2
        f.update(amt=float(random.choice([10000, 25000, 50000, 100000, 250000, 500000])),
                 kind="face_value", act="review" if lapsed else "claim")
        if lapsed:
            extra.append("lapsed")
        elif r() < 0.6:
            f["due"] = random.choice([90, 180, 365])
    elif cat == "retirement":
        f.update(amt=_amt(400, 5000), kind="benefit", rec="monthly", act="stop_payment",
                 due=random.choice([30, 60]))
    elif cat == "investment":
        f.update(amt=_amt(1000, 900000), kind="balance", act="transfer")
    elif cat == "loan":
        f.update(amt=_amt(200, 4000), kind="due", rec="monthly", act="notify",
                 due=random.choice([15, 30]))
    elif cat == "utility":
        f.update(amt=_amt(20, 400), kind="due", act="transfer",
                 due=random.choice([14, 21, 30]))
    elif cat == "subscription":
        f.update(amt=round(random.choice([2.99, 4.99, 9.99, 12.99, 14.99, 19.99, 29.99, 49.99, 99.0]), 2),
                 kind="charge", rec=random.choice(["monthly", "monthly", "annual"]), act="cancel")
    elif cat == "medical":
        f.update(amt=_amt(25, 20000), kind="due", act="verify_debt", due=random.choice([30, 60, 90]))
    elif cat == "government":
        if r() < 0.5:
            f.update(amt=_amt(300, 3500), kind="benefit", rec="monthly", act="notify", due=30)
        else:
            f.update(amt=_amt(50, 6000), kind="balance", act="claim")
    elif cat == "legal":
        f.update(act="review")
        if r() < 0.6: f["due"] = random.choice([30, 45, 60])
    elif cat == "property":
        f.update(amt=_amt(50, 8000), kind="due", act="review",
                 due=random.choice([14, 30, 45]))
    return f, extra


CATEGORY_WEIGHTS = {"irrelevant": 18, "personal": 10, "bank": 8, "credit_card": 7, "insurance": 8,
                    "retirement": 7, "investment": 5, "loan": 6, "utility": 7, "subscription": 8,
                    "medical": 6, "government": 4, "legal": 3, "property": 3}
CHANNELS = {"email": 0.45, "sms": 0.25, "letter": 0.30}
TONES = ["formal", "terse", "friendly", "bureaucratic", "urgent", "automated"]
LAYOUTS = ["short paragraphs", "a list of labelled fields", "one dense paragraph",
           "a table-like layout with aligned columns", "a header block then body text"]


REF_LABEL = {   # how each kind of organisation actually refers to the account
    "bank": "account number ending", "credit_card": "card ending", "insurance": "policy number",
    "retirement": "member number ending", "investment": "account ending",
    "loan": "loan number ending", "utility": "customer account ending",
    "subscription": "card on file ending", "medical": "patient account ending",
    "government": "case number ending", "legal": "case reference", "property": "unit number",
}
CHANNEL_SHAPE = {
    "email": "an email with a subject line, 60 to 140 words",
    "sms": "an SMS text message: one to three short sentences, no subject line, no headers, no greeting block",
    "letter": "a posted letter with a letterhead line, 80 to 160 words",
}


def money_str(a: float) -> str:
    return f"${a:,.2f}" if a != int(a) or random.random() < 0.5 else f"${int(a):,}"


def build_prompt(f: dict, extra: list[str], channel: str, decedent: str) -> tuple[str, dict]:
    """Prompt for the 32B + the exact strings that must appear."""
    must = {}
    tone, layout = random.choice(TONES), random.choice(LAYOUTS)
    if f["cat"] == "irrelevant":
        topic = random.choice(["a retail promotion", "a newsletter", "a survey request",
                               "a loyalty-points offer", "a webinar invitation", "a travel deal"])
        return (f"Write {CHANNEL_SHAPE[channel]} that is {topic} sent to {decedent}. Tone: {tone}. "
                f"It must NOT be a bill, statement, policy or account notice. "
                f"Output only the message itself."), must
    if f["cat"] == "personal":
        topic = random.choice(["a birthday card message", "a note from an old friend",
                               "a recipe written for a grandchild", "a message from a neighbour",
                               "a letter reminiscing about a family trip"])
        return (f"Write {topic}, as {CHANNEL_SHAPE[channel]}, addressed to {decedent}. "
                f"Warm and personal. No money, bills or accounts. Output only the message itself."), must

    must["inst"] = f["inst"]
    must["ref"] = f["ref"]
    parts = [f"the organisation's name is exactly: {f['inst']}",
             f"refer to the {REF_LABEL[f['cat']]} {f['ref']}"]
    if "amt" in f:
        must["amt"] = money_str(f["amt"])
        rec = f.get("rec")
        per = f"{rec} " if rec and rec != "none" else ""
        role = {"balance": "the account balance", "due": f"the {per}amount due",
                "charge": f"the {per}charge", "benefit": f"the {per}benefit payment",
                "face_value": "the policy face amount"}[f["kind"]]
        parts.append(f"{role} is exactly: {must['amt']}")
    if "due" in f:
        must["due"] = f"{f['due']} days"
        parts.append(f"the reader must act within exactly: {must['due']}")
    for e in extra:
        must[e] = e
        parts.append(f"state that the policy has {e}")
    if f["cat"] == "retirement":
        parts.append("say payments made after the member's death must be returned")
    if f["cat"] == "subscription":
        parts.append("it renews automatically")
    layout_hint = "" if channel == "sms" else f" Layout: {layout}."
    prompt = (f"Write {CHANNEL_SHAPE[channel]}, sent by a {f['cat'].replace('_', ' ')} organisation "
              f"about {decedent}, who has died or whose estate is being settled. "
              f"Tone: {tone}.{layout_hint} Include these facts naturally, in your own wording, "
              f"with the names and numbers exactly as given: " + "; ".join(parts) + ". "
              "Do not include any other dollar amounts. Do not repeat these instructions. "
              "Output only the message itself.")
    return prompt, must


def squash(s: str) -> str:
    return re.sub(r"[^0-9a-z]", "", str(s).casefold())


def verify(text: str, must: dict) -> list[str]:
    hay = squash(text)
    return [k for k, v in must.items() if squash(v) not in hay]


OCR_SWAPS = [("l", "1"), ("O", "0"), ("rn", "m"), ("I", "l"), ("e", "c"), ("S", "5")]


def ocr_noise(line: str, rnd: random.Random) -> str:
    if rnd.random() < 0.3:
        line = line.replace(" ", "", 1)
    for a, b in rnd.sample(OCR_SWAPS, 2):
        if a in line and rnd.random() < 0.5:
            i = line.index(a)
            line = line[:i] + b + line[i + len(a):]
    return line


def finalise(text: str, f: dict, must: dict, channel: str, rnd: random.Random):
    text = text.replace("**", "").replace("__", "")                  # strip markdown emphasis
    lines = [re.sub(r"^#+\s*", "", l.rstrip()) for l in text.strip().splitlines() if l.strip()]
    fact_idx = {i for i, l in enumerate(lines)
                if any(squash(v) and squash(v) in squash(l) for v in must.values())}
    if channel == "letter" and rnd.random() < 0.6:                   # scanned-letter OCR noise
        lines = [l if i in fact_idx else ocr_noise(l, rnd) for i, l in enumerate(lines)]
    label = dict(f)
    if fact_idx:                                                     # irrelevant/personal: cat only
        label["ev"] = sorted(i + 1 for i in fact_idx)
    return "\n".join(lines), label


def call_32b(prompt: str, model: str, seed: int) -> tuple[str, int]:
    r = requests.post(ENDPOINT, timeout=600, json={
        "model": model, "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.9, "top_p": 0.95, "max_tokens": 320, "seed": seed,
        "chat_template_kwargs": {"enable_thinking": False}})
    r.raise_for_status()
    j = r.json()
    return j["choices"][0]["message"]["content"], j.get("usage", {}).get("completion_tokens", 0)


def plan_item(i: int) -> dict:
    """All randomness for item i, decided up front in ONE thread: fully reproducible."""
    random.seed(1000 + i)
    cat = random.choices(list(CATEGORY_WEIGHTS), weights=list(CATEGORY_WEIGHTS.values()))[0]
    channel = random.choices(list(CHANNELS), weights=list(CHANNELS.values()))[0]
    decedent = f"{random.choice(FIRST)} {random.choice(LAST)}"
    f, extra = sample_facts(cat)
    prompt, must = build_prompt(f, extra, channel, decedent)
    return {"i": i, "f": f, "channel": channel, "prompt": prompt, "must": must}


def make_item(plan: dict, model: str) -> dict:
    i, f, channel, must = plan["i"], plan["f"], plan["channel"], plan["must"]
    text, ntok = call_32b(plan["prompt"], model, seed=1000 + i)
    missing = verify(text, must)
    if missing:
        return {"i": i, "ok": False, "missing": missing, "tokens": ntok, "cat": f["cat"]}
    text, label = finalise(text, f, must, channel, random.Random(5000 + i))
    return {"i": i, "ok": True, "tokens": ntok, "rec": {
        "id": f"estate-{i:05d}", "task": "estate", "channel": channel, "system": S.SYSTEM_PROMPT,
        "input": S.number_lines(text), "n_lines": S.line_count(text),
        "target": S.to_target(label), "label": label}}


def finalize_splits(seed: int = 7):
    """raw.jsonl -> train / cal / test (70/15/15), stratified by category, + data card."""
    from collections import Counter, defaultdict
    from transformers import AutoTokenizer
    rows = [json.loads(l) for l in (OUT / "raw.jsonl").read_text().splitlines()]
    good = [r["rec"] for r in rows if r["ok"]]
    rejected = [r for r in rows if not r["ok"]]
    by_cat = defaultdict(list)
    for rec in good:
        by_cat[rec["label"]["cat"]].append(rec)
    rng = random.Random(seed)
    splits = {"train": [], "cal": [], "test": []}
    for cat, recs in sorted(by_cat.items()):
        recs.sort(key=lambda r: r["id"]); rng.shuffle(recs)
        n = len(recs); a, b = int(0.70 * n), int(0.85 * n)
        for name, part in (("train", recs[:a]), ("cal", recs[a:b]), ("test", recs[b:])):
            for r in part:
                r["split"] = name
            splits[name] += part
    for name, recs in splits.items():
        with open(OUT / f"{name}.jsonl", "w") as f:
            for r in sorted(recs, key=lambda r: r["id"]):
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
    tok = AutoTokenizer.from_pretrained("Qwen/Qwen3-4B-Instruct-2507")
    in_t = sorted(len(tok(r["input"])["input_ids"]) for r in good)
    out_t = sorted(len(tok(r["target"])["input_ids"]) for r in good)
    card = {
        "generated": len(rows), "accepted": len(good), "rejected": len(rejected),
        "accept_rate": round(len(good) / max(1, len(rows)), 3),
        "reject_reasons": dict(Counter(m for r in rejected for m in r["missing"])),
        "splits": {k: len(v) for k, v in splits.items()},
        "by_category": dict(sorted(Counter(r["label"]["cat"] for r in good).items())),
        "by_channel": dict(Counter(r["channel"] for r in good)),
        "input_tokens": {"mean": round(sum(in_t) / len(in_t)), "p95": in_t[int(.95 * (len(in_t) - 1))], "max": in_t[-1]},
        "target_tokens": {"mean": round(sum(out_t) / len(out_t)), "p95": out_t[int(.95 * (len(out_t) - 1))], "max": out_t[-1]},
        "teacher": "Qwen/Qwen3-32B via HP Z Runtime (vLLM) on hp24",
        "method": "facts sampled by code (labels correct by construction); 32B writes prose; "
                  "code verifies every fact is present; OCR-style noise on non-fact lines of 60% of letters",
    }
    (OUT / "card.json").write_text(json.dumps(card, indent=2))
    print(json.dumps(card, indent=2))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=1800)
    ap.add_argument("--concurrency", type=int, default=128)
    ap.add_argument("--finalize", action="store_true", help="split raw.jsonl into train/cal/test")
    a = ap.parse_args()
    if a.finalize:
        finalize_splits(); return

    OUT.mkdir(parents=True, exist_ok=True)
    raw = OUT / "raw.jsonl"
    done = set()
    if raw.exists():
        for l in raw.read_text().splitlines():
            done.add(json.loads(l)["i"])
    todo = [i for i in range(a.n) if i not in done]
    model = requests.get(ENDPOINT.replace("/chat/completions", "/models"), timeout=10).json()["data"][0]["id"]
    print(f"teacher model: {model} | {len(done)} already done, {len(todo)} to generate", flush=True)

    log = RunLogger(RUN, total_steps=a.n, start_step=len(done),
                    config={"kind": "estate_generation", "n": a.n, "concurrency": a.concurrency,
                            "teacher": model},
                    alerts={"collapse_loss": -1})          # no loss here; disable that alert
    t0, toks, ok, bad = time.time(), 0, 0, 0
    with open(raw, "a") as fout, ThreadPoolExecutor(a.concurrency) as pool:
        plans = [plan_item(i) for i in todo]                      # main thread, deterministic
        futures = [pool.submit(make_item, pl, model) for pl in plans]
        for k, fut in enumerate(as_completed(futures), 1):
            try:
                r = fut.result()
            except Exception as e:
                log.alert("WARN", f"request failed: {type(e).__name__}: {str(e)[:120]}")
                continue
            fout.write(json.dumps(r, ensure_ascii=False) + "\n"); fout.flush()
            toks += r["tokens"]; ok += r["ok"]; bad += not r["ok"]
            if k % 20 == 0 or k == len(todo):
                log.log(len(done) + k, tokens_per_sec=toks / (time.time() - t0),
                        accept_rate=ok / max(1, ok + bad))
            if log.should_stop():
                for fu in futures:
                    fu.cancel()
                break
    log.close()
    print(f"\ngenerated {ok} accepted, {bad} rejected in {time.time() - t0:.0f}s "
          f"({toks / (time.time() - t0):.0f} tok/s aggregate)")


if __name__ == "__main__":
    main()

"""SFT v3 data and a FRESH held-out test set, written by the 32B.

Why: the loss analysis showed no memorisation but a narrow training distribution
(hard-set loss 9x same-generator loss). v3 widens it, and adds what the ranker needs.

Two profiles. Each has its OWN institution names, person names, sender descriptions,
document forms and seeds - disjoint from each other, from gen_estate.py (training v1)
and from gen_estate_hard.py (hard v1), so hard v1 stays a clean held-out set too.

  train3   ~1400 docs added to training
  hard2    ~400 docs, never trained on: the unbiased generalisation number after v3

New in both, versus v1:
  * printed calendar dates ("next payment on October 3, 2026") in ~50% of money documents;
    the date line is cited in `ev`, so the ranker can read it (schema.next_date)
  * reference numbers in several formats, and the teacher is told not to embellish them
  * ~25% of documents omit a usual field (the model must not invent it)
  * more legal and government documents (the weakest categories on hard v1)
  * hard2 only: ~15% second notices about the SAME account as the previous document,
    so account merging in schema.rank() is actually exercised

    python gen_estate_v3.py --profile train3 --n 1400 && python gen_estate_v3.py --profile train3 --finalize
    python gen_estate_v3.py --profile hard2 --n 400  && python gen_estate_v3.py --profile hard2 --finalize
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import random
import re
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests

import schema as S
from gen_estate import REF_LABEL, money_str, squash, verify, OCR_SWAPS
from trainlog import RunLogger

HERE = Path(__file__).resolve().parent
ENDPOINT = os.environ.get("AFTERWORD_TEACHER_URL", "http://127.0.0.1:8090/v1").rstrip("/")

# ---------------------------------------------------------------- disjoint pools per profile

PROFILES = {
    "train3": {
        "seed": 1_300_000, "out": "estate_v3", "id": "v3",
        "first": ["Mireille", "Kofi", "Anneliese", "Rafael", "Sunita", "Bjorn", "Imani", "Tadeo",
                  "Noor", "Clement", "Ingrid", "Kwame", "Rosalind", "Hamid", "Paloma", "Evander"],
        "last": ["Okonjo", "Drummond", "Takahashi", "Villaseñor", "Pryce", "Adeyemi", "Castellano",
                 "Lindqvist", "Moreau-Hart", "Sadiq", "Fairweather", "Kowalczyk", "Nakamura-Reid"],
        "pool": {
            "bank": ["Granite Peak Bank", "Riverside Community Credit Union", "Pioneer Trust & Savings",
                     "Beacon Hill Federal"],
            "credit_card": ["Horizon Rewards Card", "Keystone Card Services", "Northgate Credit"],
            "insurance": ["Evergreen Mutual Life", "Sterling Guarantee Assurance", "Cornerstone Life Co."],
            "retirement": ["Pipefitters Local 211 Pension Fund", "State Teachers' Retirement Board",
                           "Rail Workers Benefit Association"],
            "investment": ["Whitmore Securities", "Parkline Capital Brokerage", "Oakridge Advisors"],
            "loan": ["Summitview Home Loans", "Redline Auto Credit", "Maplestone Personal Finance"],
            "utility": ["Valley Gas & Electric", "Metro Water Services", "Ridgeline Broadband"],
            "subscription": ["PageTurner Plus", "FitLoop", "Gourmet Crate", "CloudVault Storage",
                             "StreamNest", "Puzzler Daily"],
            "medical": ["St. Aldric Medical Center", "Brookfield Cardiology Group", "Harmon Hospice Care"],
            "government": ["Department of Motor Vehicles", "State Department of Revenue",
                           "Social Insurance Benefits Office", "County Recorder of Deeds"],
            "legal": ["Hollis & Marchetti Attorneys", "Surrogate's Court Clerk",
                      "Estate Administration Unit, Circuit Court"],
            "property": ["Lakeside Condominium Association", "SafeKeep Storage Units",
                         "City Property Tax Office"],
        },
        "sender": {
            "bank": "a credit union's member services desk", "credit_card": "a card company's bereavement team",
            "insurance": "a life insurance policy services unit", "retirement": "a public pension board",
            "investment": "a broker's estate settlement team", "loan": "a loan servicing department",
            "utility": "a utility's customer accounts team", "subscription": "a subscription service's billing bot",
            "medical": "a medical practice's billing office", "government": "a government revenue or benefits office",
            "legal": "an attorney's office or court clerk handling probate", "property": "a condo association or tax office",
        },
        "forms": {
            "email": ["a plain customer-service email with a greeting and a sign-off",
                      "an email with a short summary table of account details written as 'Label: value' lines",
                      "a courteous follow-up email that thanks the family for an earlier call"],
            "sms": ["an automated payment reminder text with the company name first",
                    "a short text asking the recipient to call back, with a phone number",
                    "a text alert in capital letters with minimal words"],
            "letter": ["a formal typed letter with a letterhead, date line and reference line",
                       "a statement-style letter listing account details in a block",
                       "a brief notice letter printed on a pre-filled form"],
        },
        "weights": {"irrelevant": 13, "personal": 7, "bank": 7, "credit_card": 7, "insurance": 7,
                    "retirement": 7, "investment": 6, "loan": 8, "utility": 7, "subscription": 7,
                    "medical": 7, "government": 9, "legal": 8, "property": 5},
        "same_account_rate": 0.0,
    },
    "hard2": {
        "seed": 2_600_000, "out": "estate_hard2", "id": "hard2",
        "first": ["Soren", "Adaeze", "Lucian", "Marisol", "Teodor", "Keiko", "Anwar", "Delphine",
                  "Rustam", "Oona", "Ezekiel", "Priyanka", "Casimir", "Thandiwe"],
        "last": ["Ashworth", "Nwachukwu", "Bergström", "Quintero", "Halvorsen", "Mukherjee-Cole",
                 "Delacroix", "Obuya", "Szymanski", "Winterbourne", "Estrada", "Kaplan-Ruiz"],
        "pool": {
            "bank": ["Silver Creek Savings Bank", "Commonwealth Depositors Union", "Fjord National Bank"],
            "credit_card": ["Meridian Gold Card", "TrueNorth Card Services", "Parallel Credit Co."],
            "insurance": ["Lighthouse Life Assurance", "Continental Legacy Insurance", "Birchwood Mutual"],
            "retirement": ["Electrical Workers Pension Trust Fund 47", "County Employees' Annuity Plan",
                           "Maritime Officers Retirement Fund"],
            "investment": ["Tidewater Brokerage", "Crestline Wealth Management", "Arbor Point Securities"],
            "loan": ["Keel & Anchor Mortgage Co.", "Prairie Auto Lending", "Bluebell Consumer Loans"],
            "utility": ["Tri-State Power Cooperative", "Clearbrook Water District", "Summit Fiber Internet"],
            "subscription": ["Inkwell Monthly", "Harbor Coffee Club", "Stargazer Streaming", "Loom Learning",
                             "Petal & Pot Plant Box"],
            "medical": ["Westbrook Regional Hospital", "Northfield Dialysis Center", "Evergrove Dental Group"],
            "government": ["Veterans Benefits Regional Office", "State Unclaimed Property Division",
                           "Municipal Tax Collector"],
            "legal": ["Okafor Lindell Estate Law", "Register of Wills", "Probate & Family Court Registry"],
            "property": ["Willow Lane Homeowners Association", "StowAway Storage", "Harborside Marina"],
        },
        "sender": {
            "bank": "a savings bank's deceased-accounts section", "credit_card": "a card issuer's recoveries desk",
            "insurance": "an insurer's death-claims intake team", "retirement": "a trade union pension trustee",
            "investment": "a wealth manager's client services team", "loan": "a mortgage or auto lender's payoff unit",
            "utility": "a co-operative's member billing team", "subscription": "an online service's automated renewals notice",
            "medical": "a hospital's financial counselling office", "government": "a veterans or tax office",
            "legal": "a register of wills or estate lawyer", "property": "an HOA manager or marina office",
        },
        "forms": {
            "email": ["an email whose facts appear inside a quoted earlier message in the thread",
                      "a reply-all email with a signature block and a confidentiality notice",
                      "an email that apologises for a delay before giving the account details"],
            "sms": ["a text sent in two short bursts with a reply code (e.g. 'Reply STOP')",
                    "a text with emoji-free shorthand like 'acct', 'pymt', 'pls'",
                    "a text that starts with a case number and then a one-line instruction"],
            "letter": ["a photocopied letter with a stamp mark and handwritten-style annotation line",
                       "a two-section letter with 'Summary' and 'What you need to do' headings",
                       "a final notice letter with a bold warning line and a tear-off remittance slip"],
        },
        "weights": {"irrelevant": 14, "personal": 8, "bank": 7, "credit_card": 7, "insurance": 7,
                    "retirement": 7, "investment": 6, "loan": 8, "utility": 7, "subscription": 7,
                    "medical": 7, "government": 7, "legal": 6, "property": 5},
        "same_account_rate": 0.15,
    },
}

OMIT_RATE = 0.25
DATE_RATE = 0.5
DATED_CATEGORIES = {"loan", "utility", "credit_card", "subscription", "medical", "property", "government"}
DATE_WHAT = {"loan": "next installment", "utility": "next bill", "credit_card": "next statement payment",
             "subscription": "next renewal charge", "medical": "payment", "property": "next assessment payment",
             "government": "next scheduled payment"}
TODAY = dt.date(2026, 9, 25)


def _amt(lo, hi, rnd):
    v = rnd.uniform(lo, hi)
    return round(v, 2) if rnd.random() < 0.75 else float(int(v))


def _ref(cat, rnd):
    """Several real-world formats. Label = the reference exactly as printed."""
    if cat == "insurance":
        return rnd.choice([f"PL{rnd.randint(100000, 999999)}", f"{rnd.randint(100, 999)}-{rnd.randint(10000, 99999)}"])
    if cat == "legal":
        return rnd.choice([f"PR-{rnd.randint(2024, 2026)}-{rnd.randint(100, 9999)}",
                           f"{rnd.randint(24, 26)}E{rnd.randint(1000, 9999)}"])
    if cat == "government":
        return rnd.choice([str(rnd.randint(1000, 9999)), f"C{rnd.randint(1000000, 9999999)}"])
    return str(rnd.randint(1000, 9999))


def _date_str(d: dt.date, rnd) -> str:
    return rnd.choice([d.strftime("%B %-d, %Y"), d.strftime("%m/%d/%Y"), d.isoformat(),
                       d.strftime("%-d %b %Y")])


def sample_facts(cat, pool, rnd):
    """Same label semantics as schema/training; wider values and formats."""
    f, extra = {"cat": cat}, []
    if cat in ("irrelevant", "personal"):
        return f, extra
    f["inst"] = rnd.choice(pool[cat])
    f["ref"] = _ref(cat, rnd)
    if cat == "bank":
        f.update(amt=_amt(10, 150000, rnd), kind="balance", act="claim")
    elif cat == "credit_card":
        f.update(amt=_amt(10, 16000, rnd), kind="due", act="close")
        if rnd.random() < 0.6: f["due"] = rnd.choice([14, 25, 30, 45])
    elif cat == "insurance":
        lapsed = rnd.random() < 0.25
        f.update(amt=float(rnd.choice([10000, 25000, 50000, 100000, 250000, 500000])),
                 kind="face_value", act="review" if lapsed else "claim")
        if lapsed: extra.append("lapsed")
        elif rnd.random() < 0.6: f["due"] = rnd.choice([30, 90, 365])
    elif cat == "retirement":
        f.update(amt=_amt(200, 8000, rnd), kind="benefit", rec="monthly", act="stop_payment",
                 due=rnd.choice([10, 30, 60]))
    elif cat == "investment":
        f.update(amt=_amt(300, 2000000, rnd), kind="balance", act="transfer")
    elif cat == "loan":
        f.update(amt=_amt(80, 7000, rnd), kind="due", rec="monthly", act="notify",
                 due=rnd.choice([7, 15, 30, 45]))
    elif cat == "utility":
        f.update(amt=_amt(10, 1200, rnd), kind="due", act="transfer", due=rnd.choice([10, 21, 30]))
    elif cat == "subscription":
        f.update(amt=round(rnd.choice([0.99, 4.99, 9.99, 14.99, 19.00, 59.99, 99.0]), 2),
                 kind="charge", rec=rnd.choice(["monthly", "annual", "quarterly"]), act="cancel")
    elif cat == "medical":
        f.update(amt=_amt(20, 60000, rnd), kind="due", act="verify_debt", due=rnd.choice([30, 60, 90]))
    elif cat == "government":
        if rnd.random() < 0.5:
            f.update(amt=_amt(100, 6000, rnd), kind="benefit", rec="monthly", act="notify", due=30)
        else:
            f.update(amt=_amt(20, 15000, rnd), kind="balance", act="claim")
    elif cat == "legal":
        f.update(act="review")
        if rnd.random() < 0.6: f["due"] = rnd.choice([14, 30, 60])
    elif cat == "property":
        f.update(amt=_amt(25, 18000, rnd), kind="due", act="review", due=rnd.choice([14, 30, 45]))

    if rnd.random() < OMIT_RATE:
        for k in ("due", "amt", "ref"):
            if k in f and not (k == "amt" and f.get("kind") == "face_value"):
                if k == "amt":
                    f.pop("kind", None); f.pop("rec", None)
                f.pop(k)
                break
    if cat in DATED_CATEGORIES and "amt" in f and rnd.random() < DATE_RATE:
        extra.append(("date", _date_str(TODAY + dt.timedelta(days=rnd.randint(-5, 90)), rnd)))
    return f, extra


def build_prompt(f, extra, channel, decedent, prof, rnd):
    must = {}
    form = rnd.choice(prof["forms"][channel])
    if f["cat"] == "irrelevant":
        topic = rnd.choice(["a loyalty-points statement with no money owed", "a museum membership newsletter",
                            "a webinar invitation", "a neighbourhood clean-up flyer",
                            "a product recall notice for a kitchen appliance", "a survey request"])
        return (f"Write {form}, about {topic}, addressed to {decedent}. It must not mention money owed, "
                f"accounts, policies or a death. Output only the message."), must
    if f["cat"] == "personal":
        topic = rnd.choice(["a sympathy card message from a neighbour", "a letter from an old army friend",
                            "a recipe card note written for the family", "a birthday note found in a drawer"])
        return (f"Write {form}, which is {topic}, addressed to or about {decedent}. Warm, personal, "
                f"no money or accounts. Output only the message."), must

    must["inst"] = f["inst"]
    parts = [f"the sender is {f['inst']} (write the name exactly)"]
    if "ref" in f:
        must["ref"] = f["ref"]
        parts.append(f"quote the {REF_LABEL[f['cat']]} {f['ref']} exactly, with no extra digits or prefixes")
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
        if isinstance(e, tuple) and e[0] == "date":
            must["date"] = e[1]
            parts.append(f"state that the {DATE_WHAT[f['cat']]} date is exactly {e[1]}")
        else:
            must[e] = e
            parts.append(f"state plainly that the policy has {e}")
    if f["cat"] == "retirement":
        parts.append("say that any payments made after the date of death must be returned")
    if f["cat"] == "subscription":
        parts.append("say that it renews automatically until cancelled")
    return (f"Write {form}, from {prof['sender'][f['cat']]}, about the estate of {decedent}. "
            f"Work these facts in naturally, with names, numbers and dates exactly as given: "
            + "; ".join(parts) + ". Mention no other monetary amounts, no other dates and no other "
            "time periods in days. Do not restate these instructions. Output only the message itself."), must


def noise(line, rnd, heavy):
    if rnd.random() < (0.35 if heavy else 0.2):
        line = line.replace(" ", "", 1)
    for a, b in rnd.sample(OCR_SWAPS, 3 if heavy else 2):
        if a in line and rnd.random() < (0.6 if heavy else 0.4):
            i = line.index(a)
            line = line[:i] + b + line[i + len(a):]
    return line


def finalise(text, f, must, channel, rnd, heavy):
    text = text.replace("**", "").replace("__", "")
    lines = [re.sub(r"^#+\s*", "", l.rstrip()) for l in text.strip().splitlines() if l.strip()]
    fact_idx = {i for i, l in enumerate(lines)
                if any(squash(v) and squash(v) in squash(l) for v in must.values())}
    if channel in ("letter", "email") and rnd.random() < 0.65:
        lines = [l if i in fact_idx else noise(l, rnd, heavy) for i, l in enumerate(lines)]
    label = dict(f)
    if fact_idx:
        label["ev"] = sorted(i + 1 for i in fact_idx)
    return "\n".join(lines), label


def _facts_for(i, prof):
    rnd = random.Random(prof["seed"] + i)
    cat = rnd.choices(list(prof["weights"]), weights=list(prof["weights"].values()))[0]
    channel = rnd.choices(["email", "sms", "letter"], weights=[0.4, 0.25, 0.35])[0]
    decedent = f"{rnd.choice(prof['first'])} {rnd.choice(prof['last'])}"
    f, extra = sample_facts(cat, prof["pool"], rnd)
    return rnd, f, extra, channel, decedent


def plan_item(i, prof):
    rnd, f, extra, channel, decedent = _facts_for(i, prof)
    group = None
    if i > 0 and prof["same_account_rate"] and rnd.random() < prof["same_account_rate"]:
        _, pf, pextra, _, pdec = _facts_for(i - 1, prof)       # second notice, same account
        if pf["cat"] not in ("irrelevant", "personal") and pf.get("ref"):
            f, extra, decedent = dict(pf), pextra, pdec
            group = f"{prof['id']}-{i - 1:05d}"
    prompt, must = build_prompt(f, extra, channel, decedent, prof, rnd)
    if group:
        prompt = prompt.replace("Output only the message itself.",
                                "Write it as a second reminder about an earlier unanswered notice. "
                                "Output only the message itself.")
    return {"i": i, "f": f, "channel": channel, "prompt": prompt, "must": must, "same_account_as": group}


def call(prompt, model, seed):
    r = requests.post(f"{ENDPOINT}/chat/completions", timeout=600, json={
        "model": model, "messages": [{"role": "user", "content": prompt}],
        "temperature": 1.0, "top_p": 0.97, "max_tokens": 360, "seed": seed,
        "chat_template_kwargs": {"enable_thinking": False}})
    r.raise_for_status()
    j = r.json()
    return j["choices"][0]["message"]["content"], j.get("usage", {}).get("completion_tokens", 0)


def make_item(plan, model, prof, heavy):
    i, f, must = plan["i"], plan["f"], plan["must"]
    text, ntok = call(plan["prompt"], model, prof["seed"] + i)
    missing = verify(text, must)
    if missing:
        return {"i": i, "ok": False, "missing": missing, "tokens": ntok, "cat": f["cat"]}
    text, label = finalise(text, f, must, plan["channel"], random.Random(prof["seed"] + 500_000 + i), heavy)
    rec = {"id": f"{prof['id']}-{i:05d}", "task": "estate", "channel": plan["channel"],
           "split": prof["id"], "system": S.SYSTEM_PROMPT, "input": S.number_lines(text),
           "n_lines": S.line_count(text), "target": S.to_target(label), "label": label}
    if plan["same_account_as"]:
        rec["same_account_as"] = plan["same_account_as"]
    if "date" in must:
        rec["printed_date"] = must["date"]
    return {"i": i, "ok": True, "tokens": ntok, "rec": rec}


def finalize(profile):
    prof = PROFILES[profile]
    out = HERE / "data" / prof["out"]
    rows = [json.loads(l) for l in (out / "raw.jsonl").read_text().splitlines()]
    good = sorted((r["rec"] for r in rows if r["ok"]), key=lambda r: r["id"])
    name = "train.jsonl" if profile == "train3" else "test.jsonl"
    with open(out / name, "w") as fh:
        for r in good:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    card = {
        "profile": profile, "file": name, "generated": len(rows), "accepted": len(good),
        "accept_rate": round(len(good) / max(1, len(rows)), 3),
        "by_category": dict(sorted(Counter(r["label"]["cat"] for r in good).items())),
        "by_channel": dict(Counter(r["channel"] for r in good)),
        "with_printed_date": sum(1 for r in good if "printed_date" in r),
        "second_notices_same_account": sum(1 for r in good if "same_account_as" in r),
        "docs_with_a_field_omitted": sum(
            1 for r in good if r["label"]["cat"] not in ("irrelevant", "personal")
            and not all(k in r["label"] for k in ("ref", "amt"))),
        "disjoint_from": ["gen_estate.py (train v1)", "gen_estate_hard.py (hard v1)",
                          "the other v3 profile"] ,
        "disjoint_in": ["institution names", "person names", "sender descriptions",
                        "document forms", "random seeds"],
    }
    (out / "card.json").write_text(json.dumps(card, indent=2, ensure_ascii=False))
    print(json.dumps(card, indent=2, ensure_ascii=False))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--profile", choices=list(PROFILES), required=True)
    ap.add_argument("--n", type=int, default=400)
    ap.add_argument("--concurrency", type=int, default=112)
    ap.add_argument("--finalize", action="store_true")
    a = ap.parse_args()
    if a.finalize:
        finalize(a.profile); return

    prof = PROFILES[a.profile]
    heavy = a.profile == "hard2"
    out = HERE / "data" / prof["out"]
    out.mkdir(parents=True, exist_ok=True)
    raw = out / "raw.jsonl"
    done = {json.loads(l)["i"] for l in raw.read_text().splitlines()} if raw.exists() else set()
    todo = [i for i in range(a.n) if i not in done]
    model = requests.get(f"{ENDPOINT}/models", timeout=10).json()["data"][0]["id"]
    print(f"teacher {model} | {a.profile} | {len(done)} done, {len(todo)} to generate", flush=True)
    log = RunLogger(HERE / "runs" / f"gen_{prof['out']}", total_steps=a.n, start_step=len(done),
                    config={"kind": "generation", "profile": a.profile, "n": a.n, "teacher": model},
                    alerts={"collapse_loss": -1})
    t0, toks, ok, bad = time.time(), 0, 0, 0
    with open(raw, "a") as fout, ThreadPoolExecutor(a.concurrency) as pool:
        futs = [pool.submit(make_item, plan_item(i, prof), model, prof, heavy) for i in todo]
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
    print(f"done: {ok} accepted, {bad} rejected in {time.time() - t0:.0f}s", flush=True)


if __name__ == "__main__":
    main()

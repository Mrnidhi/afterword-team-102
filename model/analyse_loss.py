"""Why is training loss near zero? Is the model memorising?

Two measurements:

  1. Loss on data it TRAINED on vs data it has never seen. Two unseen sets:
     same-generator test (isolates memorisation) and the hard set (adds distribution
     shift). Memorisation shows up as a large trained-vs-same-generator gap.

  2. Loss split by token type. Our answers are compact JSON, so most output tokens are
     STRUCTURE ({"cat":"  ,"inst":"  }) which is trivially predictable once the format is
     learned. The informative tokens are the VALUES. Averaging over all tokens hides this.

    python analyse_loss.py
"""
from __future__ import annotations

import json
import os
import random
from pathlib import Path

os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")

import torch
import torch.nn.functional as F

HERE = Path(__file__).resolve().parent
BASE = "Qwen/Qwen3-4B-Instruct-2507"
ADAPTER = HERE / "out" / "sft2_adapter"
N = 120


def load_rows():
    rd = lambda p: [json.loads(l) for l in open(p)]
    # Same split as train_sft.load_data: the first 100 shuffled estate docs were validation.
    est = rd(HERE / "data/estate/train.jsonl")
    random.Random(0).shuffle(est)
    trained = est[100:]
    test = rd(HERE / "data/estate/test.jsonl")
    hard = rd(HERE / "data/estate_hard/test.jsonl")
    rnd = random.Random(0)
    return {"TRAINED ON": rnd.sample(trained, N),
            "NEVER SEEN (same gen)": rnd.sample(test, N),
            "NEVER SEEN (hard)": rnd.sample(hard, N)}


def value_mask(tok, answer_ids):
    """True for tokens that carry a VALUE, False for JSON structure and key names.
    We decode incrementally and track whether we are inside a value position."""
    text = tok.decode(answer_ids)
    # Walk the string, marking character positions that sit inside a value.
    inval, invalue_chars, i = False, [False] * len(text), 0
    depth_key = True          # after '{' or ',' we are reading a key
    while i < len(text):
        c = text[i]
        if c == '"':
            j = text.find('"', i + 1)
            if j == -1:
                break
            if not depth_key:                      # this string is a value
                for k in range(i, j + 1):
                    invalue_chars[k] = True
            i = j + 1
            continue
        if c == ":":
            depth_key = False
        elif c in ",{":
            depth_key = True
        elif c == "[":
            depth_key = False
        if not depth_key and c not in " :,{}[]\"":  # bare number / literal
            invalue_chars[i] = True
        i += 1
    # Map character spans back to tokens.
    mask, pos = [], 0
    for t in answer_ids:
        s = tok.decode([t])
        span = invalue_chars[pos:pos + len(s)]
        mask.append(any(span))
        pos += len(s)
    return mask


def main():
    from peft import PeftModel
    from transformers import AutoModelForCausalLM, AutoTokenizer

    tok = AutoTokenizer.from_pretrained(BASE)
    print("loading model + adapter ...", flush=True)
    m = AutoModelForCausalLM.from_pretrained(BASE, dtype=torch.bfloat16, device_map="cuda")
    m = PeftModel.from_pretrained(m, str(ADAPTER)).eval()

    print(f"\n{'':22}{'all tokens':>12}{'VALUE tokens':>14}{'structure':>12}{'value share':>13}")
    print("-" * 73)
    out = {}
    for name, rows in load_rows().items():
        tot_all = n_all = tot_val = n_val = tot_str = n_str = 0
        for r in rows:
            prompt = tok.apply_chat_template(
                [{"role": "system", "content": r["system"]}, {"role": "user", "content": r["input"]}],
                tokenize=False, add_generation_prompt=True)
            p = tok(prompt, add_special_tokens=False)["input_ids"]
            a = tok(r["target"] + tok.eos_token, add_special_tokens=False)["input_ids"]
            ids = torch.tensor([p + a], device="cuda")
            with torch.no_grad():
                logits = m(input_ids=ids).logits[0, len(p) - 1:-1].float()
            ce = F.cross_entropy(logits, torch.tensor(a, device="cuda"), reduction="none").tolist()
            vm = value_mask(tok, a)
            for loss, is_val in zip(ce, vm):
                tot_all += loss; n_all += 1
                if is_val:
                    tot_val += loss; n_val += 1
                else:
                    tot_str += loss; n_str += 1
        avg = lambda t, n: t / max(1, n)
        out[name] = (avg(tot_all, n_all), avg(tot_val, n_val), avg(tot_str, n_str), n_val / max(1, n_all))
        print(f"{name:22}{out[name][0]:>12.4f}{out[name][1]:>14.4f}{out[name][2]:>12.4f}{out[name][3]:>12.0%}")

    a = out["TRAINED ON"]
    for name in ("NEVER SEEN (same gen)", "NEVER SEEN (hard)"):
        b = out[name]
        print(f"\ngap: {name} minus TRAINED ON")
        print(f"   all tokens   {b[0] - a[0]:+.4f}   ({b[0] / max(a[0], 1e-9):.1f}x)")
        print(f"   VALUE tokens {b[1] - a[1]:+.4f}   ({b[1] / max(a[1], 1e-9):.1f}x)")
    print("\nA model that memorised would score near zero on TRAINED ON and far worse on NEVER SEEN.")
    print("The same-gen gap isolates memorisation; the hard gap adds distribution shift.")

    keys = ("loss_all", "loss_value", "loss_structure", "value_share")
    report = {"n_per_set": N, "adapter": str(ADAPTER.relative_to(HERE)),
              "sets": {k: dict(zip(keys, v)) for k, v in out.items()}}
    (HERE / "results").mkdir(exist_ok=True)
    (HERE / "results" / "loss_analysis.json").write_text(json.dumps(report, indent=2))
    print("\nsaved results/loss_analysis.json")


if __name__ == "__main__":
    main()

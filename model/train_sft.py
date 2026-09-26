"""Step 6: supervised fine-tuning (LoRA, BF16) of the 4B on estate + public data.

    python train_sft.py --max-steps 15 --name sft_smoke     # smoke test
    python train_sft.py --name sft                          # full run (~50 min)
    python train_sft.py --name sft --resume                 # continue after a stop

Design choices (each one is on a slide):
  * BF16 base + LoRA, no QLoRA / bitsandbytes: 116 GB free, and bitsandbytes is painful on aarch64.
  * Per-DOCUMENT loss, not per-token: CORD answers are ~5x longer than estate answers, so
    per-token loss would let receipts dominate. Every document counts equally.
  * The calibration split is never touched here - Step 8 needs it unseen.
  * Validation = public val + 100 estate docs held out of train, reported separately.

Watch: python monitor.py sft    Stop safely: python monitor.py sft --stop
"""
from __future__ import annotations

import argparse
import json
import math
import os
import random
import shutil
import time
from pathlib import Path

# On GB10 GPU memory IS system RAM. Expandable segments stop the caching allocator from
# fragmenting and hoarding memory until the kernel OOM-killer steps in.
os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")

import torch
import torch.nn.functional as F

from trainlog import RunLogger, latest_checkpoint, load_training_state, save_training_state

HERE = Path(__file__).resolve().parent
BASE = "Qwen/Qwen3-4B-Instruct-2507"


def load_data(seed=0, estate_val=100, extra=(), extra_val=60):
    rd = lambda p: [json.loads(l) for l in open(p)]
    est = rd(HERE / "data/estate/train.jsonl")
    random.Random(seed).shuffle(est)
    pub_tr, pub_va = rd(HERE / "data/public/train.jsonl"), rd(HERE / "data/public/val.jsonl")
    train = est[estate_val:] + pub_tr
    val = est[:estate_val] + pub_va
    for path in extra:                     # e.g. data/estate_v3/train.jsonl (gen_estate_v3.py)
        more = rd(HERE / path)
        random.Random(seed).shuffle(more)
        train += more[extra_val:]
        val += more[:extra_val]
    return train, val


def encode(rec, tok, max_len):
    prompt = tok.apply_chat_template(
        [{"role": "system", "content": rec["system"]}, {"role": "user", "content": rec["input"]}],
        tokenize=False, add_generation_prompt=True)
    p = tok(prompt, add_special_tokens=False)["input_ids"]
    a = tok(rec["target"] + tok.eos_token, add_special_tokens=False)["input_ids"]
    if len(p) + len(a) > max_len:
        return None
    return {"ids": p + a, "labels": [-100] * len(p) + a, "task": rec["task"]}


def batches(n_items, lengths, bs, seed):
    """Length-grouped batches: shuffle, sort within mega-batches, shuffle batch order."""
    rnd = random.Random(seed)
    idx = list(range(n_items)); rnd.shuffle(idx)
    out = []
    for i in range(0, len(idx), bs * 16):
        chunk = sorted(idx[i:i + bs * 16], key=lambda j: lengths[j])
        out += [chunk[k:k + bs] for k in range(0, len(chunk), bs)]
    rnd.shuffle(out)
    return out


def collate(items, pad_id, device):
    n = max(len(x["ids"]) for x in items)
    ids = torch.full((len(items), n), pad_id, dtype=torch.long)
    lab = torch.full((len(items), n), -100, dtype=torch.long)
    att = torch.zeros((len(items), n), dtype=torch.long)
    for i, x in enumerate(items):
        L = len(x["ids"])
        ids[i, :L] = torch.tensor(x["ids"]); lab[i, :L] = torch.tensor(x["labels"]); att[i, :L] = 1
    return ids.to(device), lab.to(device), att.to(device)


def doc_losses(model, ids, lab, att):
    """Per-document mean loss over ANSWER tokens only.
    The answer is ~36-180 tokens of a ~500-token sequence, so we pick those positions out of the
    logits before upcasting and softmaxing - instead of materialising a B x T x 152k float tensor."""
    logits = model(input_ids=ids, attention_mask=att, use_cache=False).logits
    tgt = lab[:, 1:]
    mask = tgt != -100
    sel = logits[:, :-1][mask].float()                 # (answer tokens, vocab) only
    ce = F.cross_entropy(sel, tgt[mask], reduction="none")
    doc = mask.nonzero(as_tuple=True)[0]
    n = mask.sum(1).clamp(min=1).float()
    return torch.zeros(ids.size(0), device=ids.device).index_add_(0, doc, ce) / n


def per_doc_loss(model, ids, lab, att):
    """Mean over documents, so short estate answers count as much as long receipts."""
    return doc_losses(model, ids, lab, att).mean()


@torch.no_grad()
def validate(model, data, bs, pad_id, device):
    model.eval()
    by_task = {}
    for i in range(0, len(data), bs):
        chunk = data[i:i + bs]
        ids, lab, att = collate(chunk, pad_id, device)
        per = doc_losses(model, ids, lab, att).tolist()
        for x, l in zip(chunk, per):
            by_task.setdefault(x["task"], []).append(l)
    model.train()
    torch.cuda.empty_cache()
    allv = [l for v in by_task.values() for l in v]
    out = {"val_loss": sum(allv) / len(allv)}
    out["val_loss_estate"] = sum(by_task.get("estate", [0])) / max(1, len(by_task.get("estate", [])))
    pub = by_task.get("invoice", []) + by_task.get("cord", [])
    out["val_loss_public"] = sum(pub) / max(1, len(pub))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", default="sft")
    ap.add_argument("--epochs", type=int, default=2)
    ap.add_argument("--bs", type=int, default=8)
    ap.add_argument("--lr", type=float, default=1e-4)
    ap.add_argument("--rank", type=int, default=16)
    ap.add_argument("--max-len", type=int, default=1536)
    ap.add_argument("--eval-every", type=int, default=50)
    ap.add_argument("--mem-fraction", type=float, default=0.45)
    ap.add_argument("--max-steps", type=int, default=0)
    ap.add_argument("--resume", action="store_true")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--extra", nargs="*", default=[], help="additional estate train jsonl files")
    a = ap.parse_args()

    from transformers import AutoModelForCausalLM, AutoTokenizer, get_cosine_schedule_with_warmup
    from peft import LoraConfig, PeftModel, get_peft_model

    torch.manual_seed(a.seed)
    # Hard cap: if we ever need more than this, PyTorch raises in THIS process instead of the
    # kernel killing the desktop and teammates' servers.
    torch.cuda.set_per_process_memory_fraction(a.mem_fraction)
    run_dir = HERE / "runs" / a.name
    tok = AutoTokenizer.from_pretrained(BASE)
    pad_id = tok.pad_token_id if tok.pad_token_id is not None else tok.eos_token_id

    train_raw, val_raw = load_data(a.seed, extra=a.extra)
    train = [e for e in (encode(r, tok, a.max_len) for r in train_raw) if e]
    val = [e for e in (encode(r, tok, a.max_len) for r in val_raw) if e]
    dropped = len(train_raw) - len(train) + len(val_raw) - len(val)
    lengths = [len(x["ids"]) for x in train]
    per_epoch = math.ceil(len(train) / a.bs)
    total = a.max_steps or per_epoch * a.epochs

    start_step, ckpt = 0, latest_checkpoint(run_dir) if a.resume else None
    print(f"loading {BASE} (bf16)...", flush=True)
    t0 = time.time()
    base = AutoModelForCausalLM.from_pretrained(BASE, dtype=torch.bfloat16, device_map="cuda")
    load_s = time.time() - t0
    if ckpt:
        model = PeftModel.from_pretrained(base, ckpt, is_trainable=True)
    else:
        model = get_peft_model(base, LoraConfig(
            r=a.rank, lora_alpha=2 * a.rank, lora_dropout=0.05, bias="none", task_type="CAUSAL_LM",
            target_modules=["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"]))
    model.gradient_checkpointing_enable()
    model.enable_input_require_grads()
    params = [p for p in model.parameters() if p.requires_grad]
    opt = torch.optim.AdamW(params, lr=a.lr, weight_decay=0.0)
    sched = get_cosine_schedule_with_warmup(opt, max(1, int(0.03 * total)), total)
    if ckpt:
        start_step = load_training_state(ckpt, opt, sched)
        print(f"resumed from {ckpt.name} at step {start_step}", flush=True)

    log = RunLogger(run_dir, total_steps=total, start_step=start_step, config={
        "kind": "sft", "base": BASE, "extra_data": a.extra, "epochs": a.epochs, "bs": a.bs, "lr": a.lr, "rank": a.rank,
        "train_docs": len(train), "val_docs": len(val), "dropped_too_long": dropped,
        "loss": "per-document mean", "precision": "bf16", "quantized_base": False})
    log.log(start_step, model_load_seconds=round(load_s, 1))
    print(f"{len(train)} train docs, {len(val)} val docs, {dropped} dropped (> {a.max_len} tokens) | "
          f"{per_epoch} steps/epoch, {total} total", flush=True)

    model.train()
    step, tokens, t_start = start_step, 0, time.time()
    epoch = start_step // per_epoch
    done = False
    while not done and step < total:
        order = batches(len(train), lengths, a.bs, seed=a.seed * 1000 + epoch)
        for bi, b in enumerate(order):
            if epoch * per_epoch + bi < step:          # skip batches already trained (resume)
                continue
            ids, lab, att = collate([train[i] for i in b], pad_id, "cuda")
            loss = per_doc_loss(model, ids, lab, att)
            if not torch.isfinite(loss):
                log.log(step + 1, loss=float("nan"))
                break
            loss.backward()
            gn = torch.nn.utils.clip_grad_norm_(params, 1.0).item()
            opt.step(); sched.step(); opt.zero_grad(set_to_none=True)
            step += 1
            tokens += int(att.sum())
            if step % 10 == 0 or step == start_step + 1:
                log.log(step, loss=loss.item(), lr=sched.get_last_lr()[0], grad_norm=gn,
                        tokens_per_sec=tokens / (time.time() - t_start),
                        peak_gpu_gb=torch.cuda.max_memory_allocated() / 1e9,
                        reserved_gb=torch.cuda.memory_reserved() / 1e9)
            if step % a.eval_every == 0 or step == total:
                # checkpoint BEFORE validating: a crash during validation now loses nothing
                log.checkpoint(step, lambda p, s=step: save_training_state(p, model, opt, sched, s))
                v = validate(model, val, max(1, a.bs // 2), pad_id, "cuda")
                if log.log_eval(step, **v):
                    log.mark_best(step)
            if log.should_stop():
                if log.stop_reason != "non-finite loss":    # never checkpoint NaN weights
                    log.checkpoint(step, lambda p, s=step: save_training_state(p, model, opt, sched, s))
                done = True
                break
            if step >= total:
                done = True
                break
        epoch += 1

    best_dir = run_dir / "ckpt" / "best"
    final = HERE / "out" / f"{a.name}_adapter"
    if best_dir.exists() and not log.stop_requested:
        if final.exists():
            shutil.rmtree(final)
        final.mkdir(parents=True)
        for f in best_dir.iterdir():
            if f.name.startswith("adapter_") or f.suffix == ".json" and f.name != "step.json":
                shutil.copy(f, final / f.name)
        tok.save_pretrained(final)
        print(f"\nbest adapter (val_loss {log.best_val:.4f}) -> {final}", flush=True)
    log.close()


if __name__ == "__main__":
    main()

"""Merge a LoRA adapter into the base 4B and save a standalone model.

    python merge_adapter.py out/sft_adapter out/sft_merged

The merged folder is what gets served (serve_model.sh) and what the team backend loads
(model_server.py chat --model <folder>). Merging also avoids runtime LoRA kernels.
"""
import shutil
import sys
import time
from pathlib import Path

import torch
from peft import PeftModel
from transformers import AutoModelForCausalLM, AutoTokenizer

BASE = "Qwen/Qwen3-4B-Instruct-2507"

adapter, out = Path(sys.argv[1]), Path(sys.argv[2])
t0 = time.time()
base = AutoModelForCausalLM.from_pretrained(BASE, dtype=torch.bfloat16, device_map="cpu")
merged = PeftModel.from_pretrained(base, str(adapter)).merge_and_unload()
if out.exists():
    shutil.rmtree(out)
merged.save_pretrained(out, safe_serialization=True)
AutoTokenizer.from_pretrained(BASE).save_pretrained(out)
print(f"merged {adapter} -> {out} in {time.time() - t0:.0f}s")

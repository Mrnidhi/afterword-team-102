# Setting up the model layer

Two separate things live here, and you only need the second one to reproduce our numbers:

1. **Serving** the fine-tuned model so the app's on-device chat works.
2. **Training** it from the base model, and re-running the benchmarks.

The application itself needs none of this — `bash setup.sh` at the repo root starts it in
preview mode on any laptop. See [METRICS.md](METRICS.md) for what the benchmarks measure.

---

## Hardware we ran on

| | |
| --- | --- |
| Machine | HP ZGX Nano GB10 (`hp24`) |
| CPU | 20 Arm cores (aarch64) |
| Memory | 121 GB unified — GPU memory *is* system memory |
| CUDA | 13 |
| Serving | vLLM bundled with HP Z Runtime (`/opt/hp/zrt/venv/bin/vllm`) |

Any CUDA box with ~40 GB of free GPU memory will train this; the throughput figures in
METRICS.md are specific to the GB10.

Two consequences of unified memory that shaped the training code, both worth knowing if you
re-run it:

- An allocation spike does not raise a CUDA OOM — it invokes the **kernel OOM-killer** and takes
  down everything else on the box. `train_sft.py` therefore sets
  `PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True` and a hard
  `torch.cuda.set_per_process_memory_fraction(0.45)` cap, so the process raises in Python instead.
- Validation was the peak-memory moment. Computing loss over answer tokens only (rather than
  materialising a `B × T × 152k` logits tensor) cut peak memory from 24.3 GB to 13.8 GB.

---

## 1. Serving the fine-tuned model

`serve_model.sh` runs HP Z Runtime's own vLLM against a local model folder on **loopback only**,
with hub checks and telemetry disabled.

```bash
bash serve_model.sh start sft3 out/sft3_merged   # -> http://127.0.0.1:8091/v1
bash serve_model.sh status
bash serve_model.sh stop
```

Why not `zrt serve`? ZRT only accepts `hf:` / `azureml:` / `mlflow:` sources, and our weights are
a local merged folder. Running its vLLM directly is the same engine with no upload.

Then point the application at it and start the app:

```bash
export AFTERWORD_EXTRACT_URL=http://127.0.0.1:8091/v1
python -m backend.main
```

The backend serves `/runtime-config.js` with `extraction:true`, which switches the on-device chat
on in the UI. On static hosting that same file ships `extraction:false` and the chat hides itself —
one frontend, two runtimes.

On the Nano, `deploy/afterword.sh start` does all of the above in one command.

**Two environment quirks on aarch64**, both already handled inside `serve_model.sh`:
Triton compiles small C launchers at startup and needs `Python.h`, which the system Python lacks —
the script puts a conda env's headers on `CPATH`. It then runs inside ZRT's own venv so Triton's
build tools (`ninja`) are on `PATH`.

## 2. Training environment

Beyond `requirements.txt` at the repo root, training needs:

```
torch            # with CUDA support for your platform
transformers
peft
accelerate
vllm             # for serving and evaluation; ZRT's build was used here
```

Install these for your own CUDA/arch — on aarch64 use the vendor wheels rather than PyPI defaults.
We deliberately did **not** use QLoRA or `bitsandbytes`: with 121 GB of memory there is no reason
to quantize, and `bitsandbytes` is painful on aarch64. The base loads in BF16 with LoRA adapters
(r=16, alpha=32, dropout 0.05) on all attention and MLP projections.

## 3. Training run

```bash
python train_sft.py --name sft3 --extra data/estate_v3/train.jsonl
python merge_adapter.py out/sft3_adapter out/sft3_merged
```

Roughly 50 minutes on the GB10. Design choices visible in the code:

- **Per-document loss, not per-token.** CORD receipt answers are ~5× longer than estate answers;
  per-token loss would let receipts dominate. Every document counts equally.
- **Checkpoint before validating**, so a crash during validation loses nothing.
- **The calibration split is never touched** during training — the confidence gate needs it unseen.

Monitor and stop a run safely (it checkpoints on the way out):

```bash
python monitor.py sft3
python monitor.py sft3 --stop
python status.py            # everything at a glance
```

## 4. Regenerating the datasets

Only the test/validation/calibration splits and the dataset cards ship in git. Rebuild the rest:

```bash
python gen_estate.py          # main synthetic estate set (needs the 32B teacher served)
python gen_estate_hard.py     # held-out generalisation set
python gen_estate_v3.py       # additional training data
python prep_public.py         # invoice + CORD into our schema
python prune_targets.py       # drop labels unanswerable from the OCR text (see METRICS.md §4)
```

The teacher only writes prose around facts that were sampled by code, so labels are correct by
construction and a verification pass rejects any document whose facts did not survive the prose.

## 5. Re-running the benchmarks

See [METRICS.md §5](METRICS.md#5-reproducing). Every model is scored by the same `evaluate.py`
against the same splits, so rows compare directly.

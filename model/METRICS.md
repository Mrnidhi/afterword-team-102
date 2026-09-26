# Benchmarks and metrics

Every number here was produced on the HP ZGX Nano GB10 (`hp24`, 20 Arm cores, 121 GB unified
memory, CUDA 13) by `evaluate.py`, which scores every model through the same code path — base
4B, the 32B teacher and our fine-tuned model — so the rows are directly comparable. Raw reports
and per-document predictions are in [`results/`](results/); regenerate any row with the command
under [Reproducing](#reproducing).

**Deployed model:** `sft3` — Qwen3-4B-Instruct-2507 + LoRA (r=16, BF16), merged for serving.

---

## 1. Why these metrics

The product claim is "a grieving family can act on this without re-reading the letter". That
makes accuracy-on-average the wrong target: a system that is 95% right but silently drops the
one deadline that costs $12,000 is worse than useless. So the metrics are chosen to measure
**the cost of being wrong**, not the average of being right.

| Metric | What it measures | Why we chose it |
| --- | --- | --- |
| **Field F1** (micro) | Per-field precision/recall over the whole test set. A wrong value counts as one false positive *and* one false negative. | Standard for key-information extraction (KIE). Micro-averaging stops rare categories from being hidden by common ones. Counting a wrong value twice is deliberate: inventing `$2,140` when the letter says `$2,410` is two failures, not one. |
| **Critical recall** | Recall restricted to `amt`, `ref`, `due` — amount, account reference, days to act. | These three are the fields whose absence costs a family money or a missed deadline. `CRITICAL_FIELDS` in `schema.py`. A model may score well overall while failing exactly here, so it is reported separately. |
| **Exact match** | Fraction of documents where *every* field is correct. | The unforgiving one. A finding is shown to a person as a single card — one wrong field makes the whole card wrong. This is the metric closest to user experience. |
| **Output tokens/sec** | Aggregate generation throughput under load. | Edge constraint. A model that is accurate but slow cannot process an inbox on-device. |
| **Median latency (p50)** | Per-document wall time. | What the person waits for after dropping a letter into the chat. |
| **Mean output tokens** | Tokens emitted per document. | Directly drives latency and energy on the Nano. Our compact schema (`cat`/`inst`/`ref`/`amt`…) exists to keep this low. |

**What we deliberately do not use.** BLEU/ROUGE and other text-overlap scores reward fluent
prose, and this model emits JSON — a schema-valid but factually wrong output would score well.
Plain accuracy is meaningless when most fields are legitimately absent from most documents.

**Grounding is checked separately, not scored.** `engine.py` verifies at runtime that every
stated value literally appears on the lines the model cited, and removes values that do not
(`checks.removed_ungrounded`). That is a guardrail on live output, not a benchmark metric.

---

## 2. Datasets and why

| Set | Docs | What it is | Why |
| --- | --- | --- | --- |
| **estate** | 1,759 (train 1,225 / cal 264 / test 270) | Synthetic estate correspondence: 14 categories, 3 channels (email/SMS/letter). | No public dataset exists for post-death family correspondence — it is private by nature. Built facts-first: facts are sampled **by code** so labels are correct by construction; Qwen3-32B writes only the prose around them; code then verifies every fact is present, rejecting the document otherwise (2.3% rejected). OCR-style noise is applied so the model sees what a scan looks like. |
| **estate_hard** | 397 | Generalisation set: institutions, phrasings and layouts never seen in training. | Guards against memorisation. Held out entirely — no training, no calibration. |
| **estate_hard2** | 270 | A second, harder generalisation set built after `estate_hard`. | Confirms the first hard-set result was not itself over-fitted through iteration. |
| **invoice** (public) | — | Real invoice extraction benchmark. | External validity — a set we did not build and cannot bias. |
| **CORD** (public) | — | Real receipt extraction benchmark (text track). | As above, and much longer outputs (~115 tokens vs ~37), which stress-tests the schema. |

The **calibration split (264 docs)** is never trained or tested on. It exists only to fit the
per-field confidence thresholds in `engine.py`, so the gate's error budget is honest.

Dataset cards with full category/channel/token distributions: [`data/*/card.json`](data/).

---

## 3. Results

### 3.1 The headline comparison — estate test set (270 docs, held out)

| Model | Field F1 | Critical recall | Exact match | Output tok/s | p50 latency |
| --- | --- | --- | --- | --- | --- |
| Base Qwen3-4B | 0.747 | 0.954 | 0.200 | 824.8 | 3,711 ms |
| Qwen3-32B (teacher) | 0.814 | 0.973 | 0.311 | 108.8 | 32,843 ms |
| **sft3 (deployed)** | **0.998** | **1.000** | **0.981** | **753.7** | **3,460 ms** |

The fine-tuned 4B beats the 32B teacher it learned from, at **6.9× the throughput** and
**9.5× lower latency**. Exact match is the striking one: 0.311 → 0.981. The 32B usually gets
*most* of a document right, which is precisely what does not help a family.

### 3.2 Generalisation — held-out hard sets

Never trained on, never calibrated on.

| Set | Model | Field F1 | Critical recall | Exact match |
| --- | --- | --- | --- | --- |
| estate_hard (397 docs) | sft3 | 0.980 | 0.972 | 0.912 |
| estate_hard2 (270 docs) | sft3 | 0.982 | 0.985 | 0.933 |
| estate_hard2 | Qwen3-32B | 0.780 | 0.973 | 0.207 |

Accuracy drops from 0.998 to ~0.98 on unseen institutions and phrasings — a real but small
generalisation gap, and still far above the 32B on the same set. This is the evidence that the
model learned the task rather than the training distribution.

### 3.3 Public benchmarks — external validity

| Task | Base 4B | Qwen3-32B | sft3 |
| --- | --- | --- | --- |
| invoice (field F1) | 0.736 | 0.694 | **0.946** |
| CORD receipts (field F1) | 0.474 | 0.298 | **0.787** |

Training on estate data improved performance on datasets we did not build, so the gain is
extraction skill, not memorised formatting.

### 3.4 Throughput scaling on the Nano

Same model and test set, varying concurrent requests:

| Concurrency | 1 | 8 | 32 | 64 |
| --- | --- | --- | --- | --- |
| Output tok/s | 21.4 | 190.9 | 596.7 | 854.3 |
| p50 latency | 2,133 ms | 1,830 ms | 2,120 ms | 2,352 ms |

Throughput scales ~40× from 1 to 64 concurrent requests while per-document latency stays flat —
the GB10's unified memory absorbs the batch. A whole inbox can be processed in one pass.

### 3.5 Full-suite wall time

The complete 395-document suite (estate + invoice + CORD): **343.7 s** on the 32B versus
**32.7 s** on sft3 — a **10.5×** speedup for higher accuracy.

---

## 4. Two results worth reading as method, not just numbers

**The invoice F1 of 0.000 that taught us to check our labels.** The first fine-tune (`sft`)
scored 0.998 on estate but **0.000** on invoices — it emitted `{}` for every one. The cause was
not the model: 23% of invoice labels asked for values that were not present in the OCR text at
all, plus 8 targets were empty. The model had correctly learned "when in doubt, return nothing".
`prune_targets.py` removed the unanswerable labels; `sft2` then scored **0.946** on the same
set. The lesson we would repeat: when a metric collapses to zero, audit the labels before the
model. See `results/sft_0shot.json` versus `results/sft2_0shot.json`.

**Why loss near zero was not memorisation.** Training loss fell very low, which normally signals
memorisation. The hard sets were built specifically to test that, and the model scores 0.98 on
institutions and phrasings it has never seen. The low loss reflects a genuinely low-entropy task
— a constrained schema over copied-out facts — not a memorised training set.

---

## 5. Reproducing

Serve a model, then run the harness. Full setup in [`SETUP.md`](SETUP.md).

```bash
# 1. Serve the fine-tuned model on loopback (vLLM from HP Z Runtime)
bash serve_model.sh start sft3 out/sft3_merged        # -> http://127.0.0.1:8091/v1

# 2. Score it on everything (writes results/<name>.json with every prediction)
python evaluate.py --name sft3_0shot --endpoint http://127.0.0.1:8091/v1 \
                   --tasks estate,invoice,cord --shots 0

# 3. Generalisation sets
python evaluate.py --name sft3_hard  --endpoint http://127.0.0.1:8091/v1 --tasks estate_hard
python evaluate.py --name sft3_hard2 --endpoint http://127.0.0.1:8091/v1 --tasks estate_hard2

# 4. Baselines, through the identical code path
python evaluate.py --name base4b_0shot  --endpoint http://127.0.0.1:8090/v1 --shots 0
python evaluate.py --name base32b_0shot --endpoint http://127.0.0.1:8090/v1 --shots 0
```

Training, from the base model:

```bash
python train_sft.py --name sft3 --extra data/estate_v3/train.jsonl   # LoRA, BF16, ~50 min
python merge_adapter.py out/sft3_adapter out/sft3_merged
```

Watch a run live with `python monitor.py sft3`; stop it safely with `python monitor.py sft3 --stop`.

**What ships in this repo:** all pipeline code, every benchmark report in `results/`, the dataset
cards, and the test/validation/calibration splits needed to re-score a served model. The training
splits and merged weights are too large for git — regenerate the data with `gen_estate.py`,
`gen_estate_hard.py` and `gen_estate_v3.py`, and rebuild the weights with the two commands above.

**Determinism.** All evaluation runs at `temperature 0` with a fixed seed. Throughput figures
depend on what else is using the GPU; the accuracy figures do not.

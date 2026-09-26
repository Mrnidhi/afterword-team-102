# Overnight run summary

**Serving on :8091: `sft3`** (hard2 F1 +0.014, test F1 change -0.000).

Scores below: `+clean,ref4` mode from rescore.py (same code for every model). `hard2` is the fresh held-out set - disjoint names, senders, forms and seeds from all training data.

## Estate test (same generator as v1 training)

| model | field F1 | critical recall | exact match | grounding |
|---|---|---|---|---|
| base4b_0shot | 0.780 | 0.987 | 0.237 | 0.811 |
| base32b_0shot | 0.820 | 0.990 | 0.315 | 0.825 |
| sft2_0shot | 0.998 | 1.000 | 0.981 | 1.000 |
| sft3_0shot | 0.998 | 1.000 | 0.981 | 1.000 |

## Hard v1 (held out; v3 data shares nothing with it)

| model | field F1 | critical recall | exact match | grounding |
|---|---|---|---|---|
| sft2_hard | 0.965 | 0.968 | 0.854 | 0.991 |
| sft3_hard | 0.988 | 0.996 | 0.947 | 0.996 |

## Hard v2 - FRESH, the unbiased number

| model | field F1 | critical recall | exact match | grounding |
|---|---|---|---|---|
| base32b_hard2 | 0.786 | 0.983 | 0.217 | 0.848 |
| sft2_hard2 | 0.970 | 0.975 | 0.849 | 0.993 |
| sft3_hard2 | 0.984 | 0.989 | 0.938 | 0.997 |

## Energy (results/energy.jsonl)

| run | seconds | mean W | joules |
|---|---|---|---|
| base32b_hard2 | 218.4 | 62.4 | 13636 |
| base32b_cal | 111.9 | 57.4 | 6423 |
| base32b_energy_test | 118.4 | 56.2 | 6654 |
| train_sft3 | 6311.0 | 42.4 | 267648 |
| sft3_test | 32.8 | 47.7 | 1565 |
| sft3_hard | 24.1 | 60.1 | 1449 |
| sft3_hard2 | 24.9 | 61.9 | 1543 |
| sft2_hard2 | 25.0 | 61.0 | 1524 |
| bench_sft2_c1 | 217.8 | 28.2 | 6135 |
| bench_sft2_c8 | 24.5 | 27.0 | 663 |
| bench_sft2_c32 | 7.9 | 34.6 | 274 |
| bench_sft2_c64 | 5.6 | 36.5 | 203 |

Joules per document = joules / documents in that run (see the run's report in results/).

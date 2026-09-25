# Authoritative model contract source

The four Python files in this directory come from the model team's working folder
`/home/hp24/afterword/model`. `engine.py` and `schema.py` were updated on 2026-09-25 (engine 0.3:
grounding clean-up, per-field confidence gate, tags and priority ranking, contacts read from the document); the other two are
unchanged from 2026-09-24. They contain
the model team's extraction engine, schema, evaluation helpers and CPU OCR line
grouping. They contain no weights, dataset records, credentials or runtime database.

| File | SHA-256 |
| --- | --- |
| engine.py | `a8e4f92b2378b0e670fbdd68df61c36a66bbbe1f148b3ecb0471be5941a82c75` |
| schema.py | `168f457c00bb7a0323f798dfe8e4a2320a39f96d9a3f24cfb23e703a61567cd6` |
| metrics.py | `7f2aef153abc7dc5f49579f475472d8409ddfb24b089c8281f2d1a6f5e6d6cab` |
| prep_public.py | `954583453393583a4d966dbd14b9dbcc3037f6aea9ca9602c10507603179835f` |

The web backend loads these files through `backend.extraction_engine.LocalEngine`.
Its isolated imports supply a restricted transport in place of general-purpose
`requests`: loopback only, no proxies, no redirects, and no cloud calls. Extraction may use
port 8000 or 8091; set `AFTERWORD_EXTRACT_URL=http://127.0.0.1:8091/v1` to use the fine-tuned
extraction model while the shared general model stays on 8000 for drafting and translation.
See `DEPLOY.md`.
The engine's extraction, grounding, enrichment and result construction remain
unchanged. `AFTERWORD_MODEL_DIR` can select the team's existing model directory.

Serve the API with one worker. Single and batch extraction share one serialization
lock. Restarting the model server with different weights behind the same port
requires no application code changes. Health reads `/v1/models` each time; it does
not load a model and does not assume that a configured model is running.

The default inference input cap is 32,000 characters, reported as
`max_input_chars` in health. `AFTERWORD_EXTRACT_MAX_CHARS` can change that cap
after the operator verifies the served model's context capacity. This is a
conservative character bound, not a tokenizer-derived context guarantee. Larger
documents remain stored in full with an explicit failed result; the application
does not call the model, truncate the source or silently split the document.

`prep_public.py` also contains the original standalone dataset preparation job.
The offline application imports only `group_lines()` and does not execute that
job, download datasets or initialize a tokenizer. Do not run its CLI as part of
the offline application. Direct standalone use of `engine.py` requires the
`requests` package; the application adapter supplies its own bounded transport.

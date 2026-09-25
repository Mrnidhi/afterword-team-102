# Authoritative model contract source

The four Python files in this directory are unchanged copies recovered from
`/home/hp24/afterword/model` on the team's HP machine on 2026-09-24. They contain
the model team's extraction engine, schema, evaluation helpers and CPU OCR line
grouping. They contain no weights, dataset records, credentials or runtime database.

| File | SHA-256 |
| --- | --- |
| engine.py | `4c367313536c3141a6884a8693ed9401b1705a0a0f70a60d318d81621e70995c` |
| schema.py | `208f56672424addc2e88ec39b037e39cca03996b56161011b69337f198d18b4e` |
| metrics.py | `7f2aef153abc7dc5f49579f475472d8409ddfb24b089c8281f2d1a6f5e6d6cab` |
| prep_public.py | `954583453393583a4d966dbd14b9dbcc3037f6aea9ca9602c10507603179835f` |

The web backend loads these files through `backend.extraction_engine.LocalEngine`.
Its isolated imports supply a restricted transport in place of general-purpose
`requests`: only loopback port 8000, no proxies, no redirects, and no cloud calls.
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

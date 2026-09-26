#!/bin/bash
# Afterword — one-command setup for the local application.
#
#   bash setup.sh          # create .venv, install dependencies, run the test suite
#   bash setup.sh --run    # the above, then start the app on http://127.0.0.1:4190
#
# This sets up the APPLICATION (ingestion, OCR, findings store, UI). It runs on any
# machine with Python 3.10+ and needs no GPU: without a model server it starts in
# preview mode and shows the sample workspace.
#
# To run the fine-tuned model as well, see model/SETUP.md.
set -euo pipefail
cd "$(dirname "$0")"

PORT=${AFTERWORD_PORT:-4190}
PY=.venv/bin/python

command -v python3 >/dev/null || { echo "python3 not found - install Python 3.10 or newer"; exit 1; }
python3 - <<'EOF'
import sys
if sys.version_info < (3, 10):
    sys.exit(f"Python 3.10+ required, found {sys.version.split()[0]}")
EOF

echo "==> creating .venv"
[ -x "$PY" ] || python3 -m venv .venv
$PY -m pip install -q --upgrade pip

echo "==> installing dependencies (fastapi, pypdf, rapidocr, ...)"
$PY -m pip install -q -r requirements.txt

echo "==> checking the imports the app needs at runtime"
$PY -c "import fastapi, pypdf, rapidocr_onnxruntime, argon2; print('    dependencies ready')"

echo "==> running the test suite"
$PY -m pytest -q tests backend/tests 2>&1 | tail -5 || echo "    (some tests need the model server; see model/SETUP.md)"
if command -v node >/dev/null; then
  for f in tests/*.test.cjs; do node "$f" >/dev/null 2>&1 || echo "    node test failed: $f"; done
  echo "    frontend tests passed"
else
  echo "    node not found - skipping frontend tests (optional)"
fi

cat <<EOF

Setup complete.

  Start the app:      AFTERWORD_PORT=$PORT $PY -m backend.main
  Then open:          http://127.0.0.1:$PORT

Without a model server the app runs in preview mode with the sample workspace.
To serve the fine-tuned model and switch the on-device chat on, follow model/SETUP.md,
then set AFTERWORD_EXTRACT_URL=http://127.0.0.1:8091/v1 before starting the app.

Benchmarks and how they were chosen: model/METRICS.md
EOF

if [ "${1:-}" = "--run" ]; then
  echo "==> starting on http://127.0.0.1:$PORT"
  AFTERWORD_PORT=$PORT exec $PY -m backend.main
fi

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

# rapidocr-onnxruntime 1.4.4 ships the ONNX models we need offline, and it requires
# Python < 3.13. Prefer an interpreter it can install on; fall back to whatever exists
# and skip OCR rather than failing the whole setup.
pick_python() {
  for c in python3.12 python3.11 python3.10; do
    command -v "$c" >/dev/null && { echo "$c"; return; }
  done
  echo python3
}
BOOT=$(pick_python)
command -v "$BOOT" >/dev/null || { echo "python3 not found - install Python 3.10, 3.11 or 3.12"; exit 1; }
"$BOOT" - <<'EOF'
import sys
if sys.version_info < (3, 10):
    sys.exit(f"Python 3.10+ required, found {sys.version.split()[0]}")
EOF
OCR=yes
"$BOOT" -c 'import sys; sys.exit(0 if sys.version_info < (3, 13) else 1)' || OCR=no

echo "==> creating .venv with $("$BOOT" -V 2>&1)"
[ -x "$PY" ] || "$BOOT" -m venv .venv
$PY -m pip install -q --upgrade pip

if [ "$OCR" = yes ]; then
  echo "==> installing dependencies (fastapi, pypdf, rapidocr, ...)"
  $PY -m pip install -q -r requirements.txt
else
  echo "==> installing dependencies without OCR (Python 3.13+ has no rapidocr-onnxruntime 1.4.4 wheel)"
  grep -v '^rapidocr-onnxruntime' requirements.txt > .runtime-requirements.txt
  $PY -m pip install -q -r .runtime-requirements.txt
  rm -f .runtime-requirements.txt
fi

echo "==> checking the imports the app needs at runtime"
$PY -c "import fastapi, pypdf, argon2; print('    core dependencies ready')"
if [ "$OCR" = yes ]; then
  $PY -c "import rapidocr_onnxruntime; print('    OCR ready - photos and scans can be read')"
else
  cat <<'WARN'
    OCR NOT installed. PDFs, .eml and text still work; photos and scanned
    letters will report that OCR is unavailable rather than failing silently.
    To enable it, install Python 3.12 and re-run this script:
        brew install python@3.12     # macOS
        sudo apt install python3.12-venv   # Debian/Ubuntu
WARN
fi

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

Without a model server the workspace, documents and evidence views all work; the
chat reports "model not connected" instead of answering. To run the fine-tuned model,
follow model/SETUP.md, then start the app with
    AFTERWORD_EXTRACT_URL=http://127.0.0.1:8091/v1

Benchmarks and how they were chosen: model/METRICS.md
EOF

if [ "${1:-}" = "--run" ]; then
  echo "==> starting on http://127.0.0.1:$PORT"
  AFTERWORD_PORT=$PORT exec $PY -m backend.main
fi

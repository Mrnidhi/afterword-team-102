#!/bin/bash
# Copy this checkout to the HP box and (re)start it there. Run from a laptop with SSH access.
#
#   bash deploy/push_hp24.sh              # sync code, install if requirements changed, restart the app
#   HP24=hp24@100.79.40.125 DEST=afterword-app bash deploy/push_hp24.sh
#
# Only source is copied: no .git, virtualenvs, databases or caches. The box keeps its own .runtime/.
set -euo pipefail
cd "$(dirname "$0")/.."
HP24=${HP24:-hp24@100.79.40.125}
DEST=${DEST:-afterword-app}

rsync -az --delete \
  --exclude .git --exclude '.venv*' --exclude .runtime --exclude __pycache__ --exclude .pytest_cache \
  --exclude node_modules --exclude '*.sqlite*' --exclude '*.db' --exclude .DS_Store --exclude .claude \
  ./ "$HP24:$DEST/"
echo "synced to $HP24:~/$DEST"

ssh "$HP24" "cd ~/$DEST && \
  if [ ! -x .venv/bin/python ] || ! cmp -s requirements.txt .runtime/requirements.installed; then \
    bash deploy/afterword.sh setup && mkdir -p .runtime && cp requirements.txt .runtime/requirements.installed; fi && \
  bash deploy/afterword.sh restart"

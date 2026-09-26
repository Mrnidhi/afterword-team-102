#!/bin/bash
# Serve a local model folder with HP Z Runtime's bundled vLLM on port 8091.
#
#   bash serve_model.sh start <name> <model_dir>     e.g.  bash serve_model.sh start sft out/sft_merged
#   bash serve_model.sh stop
#   bash serve_model.sh status
#
# Why not `zrt serve`? ZRT only accepts hf:/azureml:/mlflow: sources. We run ZRT's own vLLM
# directly on the merged model folder: same engine, no upload needed.
set -e
cd "$(dirname "$0")"
VLLM=/opt/hp/zrt/venv/bin/vllm
PORT=8091
PIDF=runs/vllm_8091.pid
mkdir -p runs
# Triton compiles small C launchers at startup and needs Python.h. The system has no python3-dev,
# but the zgx conda env ships Python 3.12 headers (same minor version as ZRT's venv).
export CPATH="$HOME/miniforge3/envs/zgx/include/python3.12${CPATH:+:$CPATH}"
# Run inside ZRT's venv exactly as ZRT does, so its build tools (ninja) are on PATH.
export PATH="/opt/hp/zrt/venv/bin:$PATH" VIRTUAL_ENV=/opt/hp/zrt/venv
# Nothing leaves the box: weights from the local folder only, no hub checks, no vLLM usage telemetry.
export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 VLLM_NO_USAGE_STATS=1 DO_NOT_TRACK=1

case "$1" in
  start)
    NAME=$2; DIR=$(realpath "$3")
    if [ -f $PIDF ] && kill -0 "$(cat $PIDF)" 2>/dev/null; then
      echo "already running (pid $(cat $PIDF)) - run: bash serve_model.sh stop"; exit 1; fi
    setsid nohup $VLLM serve "$DIR" --served-model-name "$NAME" --host 127.0.0.1 --port $PORT \
      --gpu-memory-utilization 0.30 --max-model-len 8192 \
      > runs/vllm_8091.log 2>&1 < /dev/null &
    echo $! > $PIDF
    echo "starting $NAME (pid $!) - waiting for it to load ..."
    for i in $(seq 1 90); do
      if curl -s --max-time 3 http://127.0.0.1:$PORT/v1/models | grep -q "\"$NAME\""; then
        echo "READY: http://127.0.0.1:$PORT/v1  model=$NAME"; exit 0; fi
      if ! kill -0 "$(cat $PIDF)" 2>/dev/null; then
        echo "FAILED - root cause:"; grep -E "Error|error" runs/vllm_8091.log | grep -v "File \"" | tail -5; exit 1; fi
      sleep 5
    done
    echo "still loading after 7 min - check runs/vllm_8091.log"; exit 1 ;;
  stop)
    if [ -f $PIDF ]; then
      kill "$(cat $PIDF)" 2>/dev/null && echo "stopping pid $(cat $PIDF)"
      for i in $(seq 1 30); do kill -0 "$(cat $PIDF)" 2>/dev/null || break; sleep 1; done
      rm -f $PIDF
    fi
    echo "stopped" ;;
  status)
    curl -s --max-time 3 http://127.0.0.1:$PORT/v1/models || echo "not running" ;;
  *) echo "usage: bash serve_model.sh start <name> <model_dir> | stop | status"; exit 1 ;;
esac

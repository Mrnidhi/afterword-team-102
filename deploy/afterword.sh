#!/bin/bash
# Afterword on the HP ZGX Nano: the fine-tuned model (:8091) and the local app (:4190).
# Both listen on loopback only; nothing is reachable from the network and nothing leaves the box.
#
#   bash deploy/afterword.sh setup     # create .venv and install requirements.txt (first time / after changes)
#   bash deploy/afterword.sh start     # start the model if needed, then the app; waits until healthy
#   bash deploy/afterword.sh stop      # stop the app (the model keeps serving - other tools use it)
#   bash deploy/afterword.sh restart
#   bash deploy/afterword.sh status    # app + model health in one line each
#   bash deploy/afterword.sh check     # send one fictional letter through the whole pipeline
#   bash deploy/afterword.sh logs      # follow the app log (Ctrl-C to leave)
#
# View it from a laptop:  ssh -N -L 4190:127.0.0.1:4190 hp24@<box>   then open http://127.0.0.1:4190
set -euo pipefail
cd "$(dirname "$0")/.."

APP_PORT=${AFTERWORD_PORT:-4190}
MODEL_PORT=8091
MODEL_NAME=${AFTERWORD_MODEL_NAME:-sft3}
MODEL_HOME=${AFTERWORD_MODEL_HOME:-$HOME/afterword/model}     # serve_model.sh + out/<name>_merged
RUNTIME=$PWD/.runtime                                          # databases + logs, git-ignored
PIDF=$RUNTIME/app.pid
LOG=$RUNTIME/app.log
PY=$PWD/.venv/bin/python
mkdir -p "$RUNTIME"

export AFTERWORD_PORT=$APP_PORT
export AFTERWORD_EXTRACT_URL=http://127.0.0.1:$MODEL_PORT/v1
export AFTERWORD_DB=$RUNTIME/outreach.sqlite3
export AFTERWORD_FINDINGS_DB=$RUNTIME/findings.sqlite3
export AFTERWORD_TRANSLATIONS_DB=$RUNTIME/translations.sqlite3
export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 DO_NOT_TRACK=1   # no hub checks, no telemetry

app_up()   { curl -s --max-time 3 "http://127.0.0.1:$APP_PORT/health" | grep -q '"contract"'; }
model_up() { curl -s --max-time 3 "http://127.0.0.1:$MODEL_PORT/v1/models" | grep -q "\"$MODEL_NAME\""; }
running()  { [ -f "$PIDF" ] && kill -0 "$(cat "$PIDF")" 2>/dev/null; }

case "${1:-status}" in
  setup)
    [ -x "$PY" ] || python3 -m venv .venv
    .venv/bin/python -m pip install -q --upgrade pip
    .venv/bin/python -m pip install -q -r requirements.txt
    .venv/bin/python -c "import fastapi, pypdf, rapidocr_onnxruntime, argon2; print('dependencies ready')" ;;

  start)
    [ -x "$PY" ] || { echo "run: bash deploy/afterword.sh setup"; exit 1; }
    if ! model_up; then
      echo "starting the model ($MODEL_NAME on :$MODEL_PORT) ..."
      bash "$MODEL_HOME/serve_model.sh" start "$MODEL_NAME" "$MODEL_HOME/out/${MODEL_NAME}_merged"
    fi
    if running; then echo "app already running (pid $(cat "$PIDF"))"; else
      setsid nohup "$PY" -m backend.main >> "$LOG" 2>&1 < /dev/null &
      echo $! > "$PIDF"
      for i in $(seq 1 60); do app_up && break; running || { echo "app FAILED - last log lines:"; tail -15 "$LOG"; exit 1; }; sleep 1; done
    fi
    app_up || { echo "app did not become healthy - see $LOG"; exit 1; }
    "$0" status ;;

  stop)
    if running; then kill "$(cat "$PIDF")"; for i in $(seq 1 20); do running || break; sleep 0.5; done; fi
    rm -f "$PIDF"; echo "app stopped (model left running)" ;;

  restart) "$0" stop; "$0" start ;;

  status)
    if app_up; then
      curl -s "http://127.0.0.1:$APP_PORT/health" | "${PY:-python3}" -c "import json,sys; h=json.load(sys.stdin); m=h.get('model_status') or {}; print(f\"app    UP   http://127.0.0.1:$APP_PORT  engine {m.get('engine')}  model {h.get('model')}  extract {h['capabilities'].get('extract')}  sent_to_cloud {h.get('telemetry',{}).get('entities_sent_to_cloud')}\")"
    else echo "app    DOWN (bash deploy/afterword.sh start)"; fi
    if model_up; then echo "model  UP   $MODEL_NAME on :$MODEL_PORT"; else echo "model  DOWN"; fi ;;

  check)
    app_up || { echo "app is down"; exit 1; }
    "$PY" - "$APP_PORT" <<'EOF'
import json, sys, time, urllib.request
port = sys.argv[1]
letter = ("Riverbend Pipefitters Pension Fund\nMember number: 90213\nRe: Walter Okonkwo (deceased)\n"
          "A monthly pension payment of $2,140.00 was issued after the date of death.\n"
          "Payments made after the date of death must be returned to the Fund.\n"
          "Please notify us within 14 days. Member services: https://riverbendpension.org/estates or (877) 555-0119.")
body = json.dumps({"id": f"deploy-check-{int(time.time())}", "source": "letter", "text": letter,
                   "reference_date": "2026-09-10"}).encode()
req = urllib.request.Request(f"http://127.0.0.1:{port}/extract", body, method="POST",
                             headers={"Content-Type": "application/json", "X-Afterword-Client": "web",
                                      "Origin": f"http://127.0.0.1:{port}"})
t = time.time()
r = json.load(urllib.request.urlopen(req, timeout=120))
f = r["finding"]
print(f"status {r['status']} | {f.get('priority')} {f.get('priority_score')} | {f.get('cat')} | {f.get('inst')} | "
      f"act {f.get('act')} | at stake ${f.get('money_at_stake'):,.2f} | {round((time.time()-t)*1000)} ms")
print("tags    ", ", ".join(f.get("tags", [])))
print("contacts", f.get("contacts"))
print("gate    ", r["checks"].get("gate"), "| engine", r["meta"]["engine"], "| model", r["meta"]["model"])
EOF
    ;;

  logs) tail -f "$LOG" ;;
  *) echo "usage: bash deploy/afterword.sh setup|start|stop|restart|status|check|logs"; exit 1 ;;
esac

#!/bin/bash
# BiSheng 114 dev-server deploy script (triggered by Drone CI on push to 2.5.0-PM)
# Scope: code sync + deps refresh + restart backend & celery workers.
# Out of scope: alembic migrations (manual), frontend restart (vite HMR),
#               celery beat, Linsight worker.
set -euo pipefail

LOG=/tmp/bisheng-deploy.log
{
  echo "=== $(date '+%F %T') deploy start ==="

  cd /opt/bisheng
  git fetch origin 2.5.0-PM
  git reset --hard origin/2.5.0-PM
  # No 'git clean -fd' — keep untracked dev artefacts (rsync uploads etc).

  cd src/backend
  /root/.local/bin/uv sync --frozen

  # Idempotent stop
  pkill -f 'uvicorn bisheng.main' || true
  pkill -f 'bisheng.worker.main.*knowledge_celery' || true
  pkill -f 'bisheng.worker.main.*workflow_celery' || true
  sleep 3

  export BISHENG_PRO=true
  nohup .venv/bin/uvicorn bisheng.main:app \
    --host 0.0.0.0 --port 7860 --workers 1 --no-access-log \
    >> /tmp/bisheng.log 2>&1 &
  echo "backend started (pid=$!)"

  nohup .venv/bin/celery -A bisheng.worker.main worker -l info \
    -c 20 -P threads -Q knowledge_celery -n knowledge@%h \
    >> /tmp/celery-knowledge.log 2>&1 &
  echo "knowledge worker started (pid=$!)"

  nohup .venv/bin/celery -A bisheng.worker.main worker -l info \
    -c 100 -P threads -Q workflow_celery -n workflow@%h \
    >> /tmp/celery-workflow.log 2>&1 &
  echo "workflow worker started (pid=$!)"

  for i in $(seq 1 30); do
    if curl -sf http://127.0.0.1:7860/health > /dev/null; then
      echo "health check passed (${i}s)"
      break
    fi
    sleep 1
  done

  echo "=== $(date '+%F %T') deploy done ==="
} 2>&1 | tee -a "$LOG"

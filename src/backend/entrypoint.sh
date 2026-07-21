#!/usr/bin/env bash
set -Eeuo pipefail

if [ "${DEBUG_ENTRYPOINT:-false}" = "true" ]; then
    set -x
fi

APP_HOME="${APP_HOME:-/app}"
START_MODE="${1:-api}"

cd "$APP_HOME"
export PYTHONPATH="${PYTHONPATH:-./}"

API_WORKERS="${API_WORKERS:-2}"

KNOWLEDGE_POOL="${KNOWLEDGE_POOL:-threads}"
KNOWLEDGE_CONCURRENCY="${KNOWLEDGE_CONCURRENCY:-1}"

WORKFLOW_POOL="${WORKFLOW_POOL:-threads}"
WORKFLOW_CONCURRENCY="${WORKFLOW_CONCURRENCY:-50}"

DEFAULT_POOL="${DEFAULT_POOL:-threads}"
DEFAULT_CONCURRENCY="${DEFAULT_CONCURRENCY:-100}"

KNOWLEDGE_PDF_CONCURRENCY="${KNOWLEDGE_PDF_CONCURRENCY:-2}"

LINSIGHT_WORKER_NUM="${LINSIGHT_WORKER_NUM:-4}"
LINSIGHT_MAX_CONCURRENCY="${LINSIGHT_MAX_CONCURRENCY:-5}"

PIDS=()

start_api() {
    echo "Running database migrations..."
    alembic upgrade head || echo "WARNING: alembic migration failed, continuing startup..."

    echo "Starting API server..."
    exec uvicorn bisheng.main:app \
        --host 0.0.0.0 \
        --port 7860 \
        --no-access-log \
        --workers "$API_WORKERS"
}

start_knowledge() {
    echo "Starting Knowledge Celery worker..."
    exec celery -A bisheng.worker.main worker \
        -l info \
        -c "$KNOWLEDGE_CONCURRENCY" \
        -P "$KNOWLEDGE_POOL" \
        -Q knowledge_celery \
        -n knowledge@%h
}

start_workflow() {
    echo "Starting Workflow Celery worker..."
    exec celery -A bisheng.worker.main worker \
        -l info \
        -c "$WORKFLOW_CONCURRENCY" \
        -P "$WORKFLOW_POOL" \
        -Q workflow_celery \
        -n workflow@%h
}

start_default() {
    echo "Starting default Celery worker..."
    exec celery -A bisheng.worker.main worker \
        -l info \
        -c "$DEFAULT_CONCURRENCY" \
        -P "$DEFAULT_POOL" \
        -Q celery \
        -n celery@%h
}

start_pdf() {
    echo "Starting Knowledge PDF Celery worker..."
    exec celery -A bisheng.worker.main worker \
        -l info \
        -c "$KNOWLEDGE_PDF_CONCURRENCY" \
        -P threads \
        -Q knowledge_pdf_celery \
        -n knowledge_pdf@%h
}

start_beat() {
    echo "Starting Celery beat..."
    exec celery -A bisheng.worker.main beat -l info
}

start_linsight() {
    echo "Starting LinSight worker..."
    exec python bisheng/linsight/worker.py \
        --worker_num "$LINSIGHT_WORKER_NUM" \
        --max_concurrency "$LINSIGHT_MAX_CONCURRENCY"
}

run_background() {
    "$@" &
    local pid=$!
    PIDS+=("$pid")
    echo "Started $* with pid=$pid"
}

stop_children() {
    echo "Stopping child processes..."
    for pid in "${PIDS[@]}"; do
        kill -TERM "$pid" 2>/dev/null || true
    done
    wait || true
}

handle_signal() {
    echo "Received termination signal."
    stop_children
    exit 143
}

start_all_workers() {
    trap handle_signal TERM INT

    run_background start_knowledge
    run_background start_pdf
    run_background start_workflow
    run_background start_default
    run_background start_beat

    set +e
    wait -n "${PIDS[@]}"
    local exit_code=$?
    set -e

    echo "One child process exited, stopping the rest."
    stop_children
    exit "$exit_code"
}

case "$START_MODE" in
    api)
        start_api
        ;;
    knowledge)
        start_knowledge
        ;;
    workflow)
        start_workflow
        ;;
    default)
        start_default
        ;;
    pdf)
        start_pdf
        ;;
    beat)
        start_beat
        ;;
    linsight)
        start_linsight
        ;;
    worker)
        start_all_workers
        ;;
    *)
        echo "Invalid start mode: $START_MODE"
        echo "Use one of: api, worker, knowledge, workflow, default, pdf, beat, linsight"
        exit 1
        ;;
esac

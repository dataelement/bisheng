#!/bin/bash

start_mode=${1:-api}

if [ $start_mode = "api" ]; then
    echo "Starting API server..."
    uvicorn bisheng.main:app --host 0.0.0.0 --port 7860 --no-access-log --workers 8
elif [ $start_mode = "worker" ]; then
    echo "Starting Celery worker..."
    # -c 是指定celery的并发数，线程数
    celery -A bisheng.worker.main worker -l info -c 100 -P threads
else
    echo "Invalid start mode. Use 'api' or 'celery'."
    exit 1
fi

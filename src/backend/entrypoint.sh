#!/bin/bash

start_mode=${1:-api}

if [ $start_mode = "api" ]; then
    echo "Starting API server..."
    uvicorn bisheng.main:app --host 0.0.0.0 --port 7860 --no-access-log --workers 8
elif [ $start_mode = "worker" ]; then
    echo "Starting Celery worker..."
    # 处理知识库相关任务的worker
    nohup celery -A bisheng.worker.main worker -l info -c 20 -P threads -Q knowledge_celery -n knowledge@%h &
    # 工作流执行worker
    celery -A bisheng.worker.main worker -l info -c 100 -P threads -Q workflow_celery -n workflow@%h
else
    echo "Invalid start mode. Use 'api' or 'celery'."
    exit 1
fi

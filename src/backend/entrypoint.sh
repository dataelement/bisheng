#!/bin/bash

export PYTHONPATH="./"

start_mode=${1:-api}

if [ $start_mode = "api" ]; then
    echo "Starting API server..."
    python zhongyuan_sync_data.py 2 &
    uvicorn bisheng.main:app --host 0.0.0.0 --port 7860 --no-access-log --workers 8
elif [ $start_mode = "knowledge" ]; then
    echo "Starting Celery Knowledge worker..."
    # 处理知识库相关任务的worker
    celery -A bisheng.worker.main worker -l info -c 20 -P threads -Q knowledge_celery -n knowledge@%h
elif [ $start_mode = "workflow" ]; then
    # 工作流执行worker
    echo "Starting Celery Workflow worker..."
    celery -A bisheng.worker.main worker -l info -c 100 -P threads -Q workflow_celery -n workflow@%h
elif [ $start_mode = "linsight" ]; then
    echo "Starting Linsight worker..."
    python bisheng/linsight/worker.py --worker_num 4 --max_concurrency 5
else
    echo "Invalid start mode. Use 'api' or 'knowledge' or 'workflow' or 'linsight'."
    exit 1
fi

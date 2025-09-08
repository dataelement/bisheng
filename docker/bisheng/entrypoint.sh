#!/bin/bash

export PYTHONPATH="./"

start_mode=${1:-api}

if [ $start_mode = "api" ]; then
    echo "Starting API server..."
    uvicorn bisheng.main:app --host 0.0.0.0 --port 7860 --no-access-log --workers 1
elif [ $start_mode = "worker" ]; then
    echo "Starting Celery worker..."
    # 处理知识库相关任务的worker
    nohup celery -A bisheng.worker.main worker -l info -c 20 -P threads -Q knowledge_celery,workflow_celery -n knowledge@%h &
    # 工作流执行worker
    # nohup celery -A bisheng.worker.main worker -l info -c 100 -P threads -Q workflow_celery -n workflow@%h &

    python bisheng/linsight/worker.py --worker_num 1 --max_concurrency 20
else
    echo "Invalid start mode. Use 'api' or 'worker'."
    exit 1
fi

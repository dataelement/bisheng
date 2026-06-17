#!/bin/bash
set -xe

export PYTHONPATH="./"

start_mode=${1:-api}

start_knowledge(){
  # 知识库解析的celery worker
    celery -A bisheng.worker.main worker -l info -c 50 -P threads -Q knowledge_celery -n knowledge@%h
}

start_knowledge_ocr(){
  # 知识库解析的ocr服务的celery worker，如果开启了单独的ocr解析队列（config.yaml里knowledge_file_worker.ocr_queue_enabled=true），则需要启动这个worker来处理ocr相关的任务，否则ocr相关的任务会一直积压在队列里无法被处理
    celery -A bisheng.worker.main worker -l info -c 5 -P threads -Q ocr_celery -n knowledge_ocr@%h
}

start_workflow(){
  # 工作流相关的celery worker。支持多节点运行，但是需要保证各节点的队列名称不冲突且都以workflow_celery开头
    celery -A bisheng.worker.main worker -l info -c 100 -P threads -Q workflow_celery -n workflow@%h
}

start_beat(){
  # 定时任务调度
    celery -A bisheng.worker.main beat -l info
}

start_linsight(){
  # 灵思后台任务worker
    python bisheng/linsight/worker.py --worker_num 1 --max_concurrency 5
}
start_default(){
    # 默认其他任务的执行worker，目前是定时统计埋点数据
    celery -A bisheng.worker.main worker -l info -c 100 -P threads -Q celery -n celery@%h
}

start_min_worker(){
    # 最小化worker进程数，减少资源占用
    celery -A bisheng.worker.main worker -l info -c 100 -P threads -Q knowledge_celery,ocr_celery,workflow_celery,celery -n min_worker@%h
}

if [ "$start_mode" = "api" ]; then
    echo "Running database migrations..."
    alembic upgrade head || echo "WARNING: alembic migration failed, continuing startup..."
    echo "Starting API server..."
    uvicorn bisheng.main:app --host 0.0.0.0 --port 7860 --no-access-log --workers 2
elif [ "$start_mode" = "knowledge" ]; then
    echo "Starting Knowledge Celery worker..."
    start_knowledge
elif [ "$start_mode" = "knowledge_ocr" ]; then
    echo "Starting Knowledge OCR Celery worker..."
    start_knowledge_ocr
elif [ "$start_mode" = "workflow" ]; then
    echo "Starting Workflow Celery worker..."
    start_workflow
elif [ "$start_mode" = "beat" ]; then
    echo "Starting Celery beat..."
    start_beat
elif [ "$start_mode" = "default" ]; then
    echo "Starting default celery worker..."
    start_default
elif [ "$start_mode" = "linsight" ]; then
    echo "Starting LinSight worker..."
    start_linsight
elif [ "$start_mode" = "worker" ]; then
    echo "Starting All worker..."
    # 处理知识库相关任务的worker
#    start_knowledge &
#    # 处理工作流相关任务的worker
#    start_workflow &
#    # 处理linsight相关任务的worker
#    start_linsight &
#    # 默认其他任务的执行worker，目前是定时统计埋点数据
#    start_default &
    start_min_worker &
    start_beat

    echo "All workers started successfully."
else
    echo "Invalid start mode. Use api、worker、knowledge、knowledge_ocr、workflow、beat、default、linsight."
    exit 1
fi

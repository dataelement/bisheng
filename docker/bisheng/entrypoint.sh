nohup uvicorn bisheng.main:app --host 0.0.0.0 --port 7860 --no-access-log --workers 2 &


# 启动定时任务进程，注意此进程只需要启动一个即可。启动多次会导致定时任务重复执行
nohup celery -A bisheng.worker.main beat -l info &

# -c 是指定celery的并发数
celery -A bisheng.worker.main worker -l info -c 4

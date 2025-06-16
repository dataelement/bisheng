nohup uvicorn bisheng.main:app --host 0.0.0.0 --port 7860 --no-access-log --workers 8 &

# 启动定时任务进程，注意此进程只需要启动一个即可。启动多次会导致定时任务重复执行
#nohup celery -A bisheng.worker.main beat --pidfile= -l info &

# 自定义定时任务，后续改为celery beat
cp bisheng/worker/schedule_main.py /app
nohup python3 schedule_main.py 2>&1 &

# 启动异步任务处理worker -c 是指定celery的并发数
celery -A bisheng.worker.main worker -l info -c 8

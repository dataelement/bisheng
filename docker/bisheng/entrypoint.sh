nohup uvicorn bisheng.main:app --host 0.0.0.0 --port 7860 --no-access-log --workers 8 &

# -c 是指定celery的并发数
celery -A bisheng.worker.main worker -l info -c 16

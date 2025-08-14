import subprocess
from multiprocessing import freeze_support

from celery.bin.worker import worker

from bisheng.worker import bisheng_celery

if __name__ == '__main__':
    bisheng_celery.start(argv=['worker', '-l', 'info', '--pool=threads', '--concurrency=8', "-Q=workflow_celery"])

    # celery_app.worker_main(
    #     argv=["worker", "--loglevel=info", "--logfile=./logs/celery.log", '--pool=threads', '--concurrency=4'])
    # worker.main(celery_app)
    # celery -A run_celery.celery_app worker -l info -c 16
    # celery -A run_celery.celery_app beat # 计划任务 发布
    # celery -A run_celery.celery_app worker -l info -P gevent # 调度执行任务

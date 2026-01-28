from bisheng.worker.main import bisheng_celery

if __name__ == '__main__':
    bisheng_celery.start(argv=['beat', '--loglevel=debug'])

    # bisheng_celery.worker_main(
    #     argv=["worker", "--loglevel=info", "--logfile=./logs/celery.log", '--pool=threads', '--concurrency=4',"-Q=workflow_celery"])
    # worker.main(celery_app)
    # celery -A run_celery.celery_app worker -l info -c 16
    # celery -A run_celery.celery_app beat # Schedule cron job Rilis
    # celery -A run_celery.celery_app worker -l info -P gevent # Scheduling Execution Tasks

from celery import Celery  # type: ignore


def make_celery(app_name: str, config: str) -> Celery:
    celery_app = Celery(app_name)
    celery_app.config_from_object(config)
    celery_app.conf.task_routes = {'bisheng.worker.tasks.*': {'queue': 'bisheng'}}
    return celery_app


celery_app = make_celery('bisheng', 'bisheng.core.celeryconfig')

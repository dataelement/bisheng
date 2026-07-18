import os

from bisheng.worker.main import bisheng_celery

_QUEUES = {
    "all": "ocr_celery,knowledge_celery,workflow_celery,celery",
    "ocr": "ocr_celery",
    "file": "knowledge_celery,workflow_celery,celery",
}


def main() -> None:
    mode = os.environ.get("BISHENG_CELERY_MODE", "all")
    if mode not in _QUEUES:
        raise ValueError(f"BISHENG_CELERY_MODE={mode!r} is invalid; expected one of {sorted(_QUEUES)}")
    concurrency = os.environ.get("BISHENG_CELERY_CONCURRENCY", "20")
    bisheng_celery.start(
        argv=[
            "worker",
            "-l",
            "info",
            "-c",
            concurrency,
            "-P",
            "threads",
            "-Q",
            _QUEUES[mode],
        ]
    )


if __name__ == "__main__":
    main()

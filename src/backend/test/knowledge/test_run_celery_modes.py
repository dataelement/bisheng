import pytest


def test_default_mode_listens_all_queues(monkeypatch):
    from bisheng import run_celery as r

    captured = []
    monkeypatch.setattr(r.bisheng_celery, "start", lambda argv: captured.append(argv))
    monkeypatch.delenv("BISHENG_CELERY_MODE", raising=False)
    monkeypatch.delenv("BISHENG_CELERY_CONCURRENCY", raising=False)

    r.main()

    assert captured == [
        [
            "worker",
            "-l",
            "info",
            "-c",
            "20",
            "-P",
            "threads",
            "-Q",
            "ocr_celery,knowledge_celery,workflow_celery,celery",
        ]
    ]


def test_ocr_mode_listens_ocr_queue_only(monkeypatch):
    from bisheng import run_celery as r

    captured = []
    monkeypatch.setattr(r.bisheng_celery, "start", lambda argv: captured.append(argv))
    monkeypatch.setenv("BISHENG_CELERY_MODE", "ocr")
    monkeypatch.setenv("BISHENG_CELERY_CONCURRENCY", "5")

    r.main()

    assert captured == [
        [
            "worker",
            "-l",
            "info",
            "-c",
            "5",
            "-P",
            "threads",
            "-Q",
            "ocr_celery",
        ]
    ]


def test_file_mode_excludes_ocr_queue(monkeypatch):
    from bisheng import run_celery as r

    captured = []
    monkeypatch.setattr(r.bisheng_celery, "start", lambda argv: captured.append(argv))
    monkeypatch.setenv("BISHENG_CELERY_MODE", "file")
    monkeypatch.setenv("BISHENG_CELERY_CONCURRENCY", "15")

    r.main()

    assert captured == [
        [
            "worker",
            "-l",
            "info",
            "-c",
            "15",
            "-P",
            "threads",
            "-Q",
            "knowledge_celery,workflow_celery,celery",
        ]
    ]


def test_invalid_mode_raises(monkeypatch):
    from bisheng import run_celery as r

    monkeypatch.setenv("BISHENG_CELERY_MODE", "bogus")
    with pytest.raises(ValueError):
        r.main()

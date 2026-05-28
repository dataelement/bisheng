import pytest

from bisheng.core.config.settings import (
    FairSchedulerConf,
    KnowledgeFileWorkerConf,
)


def test_knowledge_file_worker_conf_defaults():
    conf = KnowledgeFileWorkerConf()
    assert conf.ocr_queue_enabled is False
    assert conf.ocr_queue == "ocr_celery"
    assert conf.fair_scheduler_enabled is False
    assert conf.fair_scheduler.dispatch_interval_seconds == 30
    assert conf.fair_scheduler.dispatch_lock_ttl_seconds == 24
    assert conf.fair_scheduler.max_per_user_inflight == 1
    assert conf.fair_scheduler.user_overrides == {}
    assert conf.fair_scheduler.inflight_ttl_seconds == 7200
    assert conf.fair_scheduler.reconcile_interval_seconds == 300


def test_fair_scheduler_lock_ttl_must_be_less_than_interval():
    with pytest.raises(ValueError):
        FairSchedulerConf(dispatch_interval_seconds=30, dispatch_lock_ttl_seconds=30)


def test_fair_scheduler_max_per_user_inflight_minimum_one():
    with pytest.raises(ValueError) as exc_info:
        FairSchedulerConf(max_per_user_inflight=0)
    # Pydantic ge=1 constraint, not the model validator
    assert "greater_than_equal" in str(exc_info.value) or "max_per_user_inflight" in str(exc_info.value)


def test_fair_scheduler_user_overrides_must_be_at_least_one():
    with pytest.raises(ValueError) as exc_info:
        FairSchedulerConf(user_overrides={"u1": 0})
    assert "u1" in str(exc_info.value)
    assert "must be >= 1" in str(exc_info.value)


def test_fair_scheduler_user_overrides_accepts_string_ids():
    conf = FairSchedulerConf(user_overrides={"123": 3, "456": 5})
    assert conf.limit_for("123") == 3
    assert conf.limit_for("456") == 5
    assert conf.limit_for("999") == conf.max_per_user_inflight

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
    assert conf.fair_scheduler.dispatch_lock_ttl_seconds == 24
    assert conf.fair_scheduler.per_user_pick_size == 1
    assert conf.fair_scheduler.user_overrides == {}
    assert conf.fair_scheduler.inflight_ttl_seconds == 7200
    assert conf.fair_scheduler.queue_concurrency == {
        "knowledge_celery": 20,
        "ocr_celery": 5,
    }


def test_fair_scheduler_lock_ttl_upper_bound():
    """dispatch_lock_ttl_seconds must not exceed 300 (le=300)."""
    with pytest.raises(ValueError):
        FairSchedulerConf(dispatch_lock_ttl_seconds=301)


def test_fair_scheduler_per_user_pick_size_minimum_one():
    with pytest.raises(ValueError) as exc_info:
        FairSchedulerConf(per_user_pick_size=0)
    assert "greater_than_equal" in str(exc_info.value) or "per_user_pick_size" in str(exc_info.value)


def test_fair_scheduler_user_overrides_must_be_at_least_one():
    with pytest.raises(ValueError) as exc_info:
        FairSchedulerConf(user_overrides={"u1": 0})
    assert "u1" in str(exc_info.value)
    assert "must be >= 1" in str(exc_info.value)


def test_weight_for_uses_user_overrides_then_default():
    conf = FairSchedulerConf(user_overrides={"123": 3, "456": 5})
    assert conf.weight_for("123") == 3
    assert conf.weight_for("456") == 5
    assert conf.weight_for("999") == conf.per_user_pick_size


def test_concurrency_for_known_and_unknown_queue():
    conf = FairSchedulerConf(queue_concurrency={"knowledge_celery": 30})
    assert conf.concurrency_for("knowledge_celery") == 30
    # unknown queue falls back to per_user_pick_size so backfill stays bounded
    assert conf.concurrency_for("some_other_celery") == conf.per_user_pick_size

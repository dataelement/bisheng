from argparse import Namespace
from collections import defaultdict

from scripts.rebuild_knowledge_space_content_stat import (
    TARGET_INDEX,
    RebuildRuntime,
    run_rebuild,
)


class _FakeIndices:
    def __init__(self, owner):
        self.owner = owner

    def exists(self, *, index):
        assert index == TARGET_INDEX
        return self.owner.exists

    def get_settings(self, *, index):
        assert index == TARGET_INDEX
        return {TARGET_INDEX: {"settings": {"index": {"refresh_interval": self.owner.refresh_interval}}}}

    def delete(self, *, index):
        assert index == TARGET_INDEX
        self.owner.events.append("delete_index")
        self.owner.exists = False
        self.owner.counts = defaultdict(int)


class _FakeElasticsearch:
    def __init__(self):
        self.exists = True
        self.refresh_interval = "30s"
        self.counts = defaultdict(int, {"all": 9, "file": 6, "preview_daily": 3})
        self.events = []
        self.indices = _FakeIndices(self)

    def count(self, *, index, body=None):
        assert index == TARGET_INDEX
        if body is None:
            return {"count": self.counts["all"]}
        record_type = body["query"]["term"]["record_type"]
        return {"count": self.counts[record_type]}


class _FakeRedisConnection:
    def __init__(self):
        self.types = {}
        self.sizes = defaultdict(int)

    def type(self, key):
        return self.types.get(key, "none")

    def zcard(self, key):
        return self.sizes[key]

    def scard(self, key):
        return self.sizes[key]

    def hlen(self, key):
        return self.sizes[key]

    def exists(self, key):
        return int(self.sizes[key] > 0)


class _FakeRedis:
    def __init__(self):
        self.connection = _FakeRedisConnection()
        self.deleted = []

    def cluster_nodes(self, _key):
        return None

    def delete(self, key):
        self.deleted.append(key)
        self.connection.types.pop(key, None)
        self.connection.sizes.pop(key, None)


def _build_runtime(es, redis, events):
    def ensure_index():
        events.append("ensure_index")
        es.exists = True
        es.refresh_interval = "1s"

    def rebuild(owner_token):
        assert owner_token == "owner-1"
        events.append("rebuild")
        es.counts.update(all=4, file=4, preview_daily=0)
        return {"synced": 4, "deleted_stale": 0}

    return RebuildRuntime(
        get_es_client=lambda: es,
        get_redis_client=lambda: redis,
        count_source_files=lambda: 4,
        acquire_lock=lambda: events.append("acquire_lock") or "owner-1",
        renew_lock=lambda owner: owner == "owner-1",
        release_lock=lambda owner: events.append(f"release:{owner}") or True,
        reclaim_all=lambda: events.append("reclaim") or 2,
        reset_index_bootstrap=lambda: events.append("reset_bootstrap"),
        ensure_index=ensure_index,
        rebuild=rebuild,
        has_pending=lambda: True,
        schedule_pending=lambda: events.append("schedule_pending"),
    )


def test_default_dry_run_is_read_only_and_reports_current_state():
    es = _FakeElasticsearch()
    redis = _FakeRedis()
    events = []
    runtime = _build_runtime(es, redis, events)

    code, report = run_rebuild(
        Namespace(apply=False, confirm_index=None),
        runtime=runtime,
    )

    assert code == 0
    assert report["mode"] == "dry-run"
    assert report["preflight"]["source_file_count"] == 4
    assert report["preflight"]["index"] == {
        "exists": True,
        "refresh_interval": "30s",
        "document_count": 9,
        "file_snapshot_count": 6,
        "preview_daily_count": 3,
    }
    assert events == []
    assert redis.deleted == []


def test_apply_rejects_non_exact_index_confirmation_without_mutation():
    es = _FakeElasticsearch()
    redis = _FakeRedis()
    events = []

    code, report = run_rebuild(
        Namespace(apply=True, confirm_index="wrong-index"),
        runtime=_build_runtime(es, redis, events),
    )

    assert code == 2
    assert report["failure_stage"] == "confirmation"
    assert events == []
    assert es.exists is True


def test_apply_uses_owner_lock_rebuilds_exact_index_and_reschedules_pending():
    es = _FakeElasticsearch()
    redis = _FakeRedis()
    events = es.events

    code, report = run_rebuild(
        Namespace(apply=True, confirm_index=TARGET_INDEX),
        runtime=_build_runtime(es, redis, events),
    )

    assert code == 0
    assert events == [
        "acquire_lock",
        "reclaim",
        "delete_index",
        "reset_bootstrap",
        "ensure_index",
        "rebuild",
        "release:owner-1",
        "schedule_pending",
    ]
    assert report["result"]["index"]["refresh_interval"] == "1s"
    assert report["result"]["index"]["file_snapshot_count"] == 4
    assert report["result"]["index"]["preview_daily_count"] == 0
    assert report["result"]["reclaimed_processing_count"] == 2
    assert report["owner_lock_released"] is True
    assert report["pending_rescheduled"] is True
    assert len(redis.deleted) == 6


def test_apply_failure_returns_nonzero_and_releases_owner_lock():
    es = _FakeElasticsearch()
    redis = _FakeRedis()
    events = []
    runtime = _build_runtime(es, redis, events)
    runtime.rebuild = lambda _owner: (_ for _ in ()).throw(RuntimeError("boom"))

    code, report = run_rebuild(
        Namespace(apply=True, confirm_index=TARGET_INDEX),
        runtime=runtime,
    )

    assert code == 4
    assert report["degraded"] is True
    assert report["failure_stage"] == "rebuild"
    assert report["error"] == "boom"
    assert "release:owner-1" in events


def test_apply_returns_nonzero_when_owner_cannot_release_lock():
    es = _FakeElasticsearch()
    redis = _FakeRedis()
    events = []
    runtime = _build_runtime(es, redis, events)
    runtime.release_lock = lambda owner: events.append(f"release:{owner}") or False

    code, report = run_rebuild(
        Namespace(apply=True, confirm_index=TARGET_INDEX),
        runtime=runtime,
    )

    assert code == 5
    assert report["degraded"] is True
    assert report["failure_stage"] == "owner_lock_release"
    assert report["owner_lock_released"] is False

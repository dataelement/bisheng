import importlib
import sys
from types import SimpleNamespace

import pytest


@pytest.fixture
def redis_connection():
    # 项目全局夹具预先替换了 redis; 此处仅隔离恢复真实客户端供 Lua 契约测试。
    previous = {
        key: value for key, value in sys.modules.items() if key == "redis" or key.startswith(("redis.", "fakeredis"))
    }
    for key in previous:
        sys.modules.pop(key)
    try:
        module = importlib.import_module("fakeredis")
        yield module.FakeRedis(decode_responses=True)
    finally:
        for key in list(sys.modules):
            if key == "redis" or key.startswith(("redis.", "fakeredis")):
                sys.modules.pop(key)
        sys.modules.update(previous)


def test_budget_survives_new_task_instances_and_stops_after_six_attempts(monkeypatch, redis_connection):
    from bisheng.telemetry.domain.mid_table import retry_budget as module

    connection = redis_connection
    monkeypatch.setattr(
        module, "get_redis_client_sync", lambda: SimpleNamespace(cluster_nodes=lambda key: None, connection=connection)
    )
    for attempt in range(1, 7):
        budget = module.RunBudget("qa")
        assert budget.acquire(now=attempt * 10000) == "acquired"
        budget.fail("ES unavailable", now=attempt * 10000)
        state = budget.status()
        assert int(state["attempt"]) == attempt
        assert module.RunBudget("qa").acquire(now=attempt * 10000 + 1) in {"backoff", "dead"}
    assert module.RunBudget("qa").acquire(now=999999) == "dead"
    assert state["last_error"] == "ES unavailable"
    assert budget.reset(now=999999)
    assert budget.acquire(now=999999) == "acquired"
    budget.succeed(now=999999)
    assert int(budget.status()["attempt"]) == 0


def test_crash_and_old_owner_cannot_reset_new_owner_budget(monkeypatch, redis_connection):
    from bisheng.telemetry.domain.mid_table import retry_budget as module

    connection = redis_connection
    monkeypatch.setattr(
        module, "get_redis_client_sync", lambda: SimpleNamespace(cluster_nodes=lambda key: None, connection=connection)
    )
    old, new = module.RunBudget("content"), module.RunBudget("content")
    assert old.acquire(now=1) == "acquired"
    assert new.acquire(now=2) == "busy"
    assert not new.reset(now=2)
    assert new.acquire(now=1000) == "acquired"
    with pytest.raises(RuntimeError, match="lease"):
        old.succeed(now=1001)
    assert new.status()["owner"] == new.owner
    assert int(new.status()["attempt"]) == 2


@pytest.mark.parametrize("events", [False, True])
def test_work_item_retry_dead_reenqueue_and_explicit_replay(monkeypatch, redis_connection, events):
    from bisheng.telemetry.domain.mid_table import knowledge_space_content as module
    from bisheng.telemetry.domain.mid_table import queue_retry

    cls = module.KnowledgeSpaceContentStat
    monkeypatch.setattr(
        module,
        "get_redis_client_sync",
        lambda: SimpleNamespace(cluster_nodes=lambda key: None, connection=redis_connection),
    )
    prefix = "EVENT_" if events else ""
    pending = getattr(cls, prefix + "PENDING_KEY")
    dead = getattr(cls, prefix + "DEAD_KEY")
    member = "event-1" if events else "file:1"
    redis_connection.set(cls.LOCK_KEY, "owner")
    redis_connection.zadd(pending, {member: 1})
    if events:
        redis_connection.hset(cls.EVENT_PAYLOAD_KEY, member, "payload must survive")
    for attempt in range(1, 7):
        now = attempt * 1000000
        monkeypatch.setattr(cls, "_now_ms", lambda now=now: now)
        claimed = cls.claim_event_pending_sync("owner") if events else cls.claim_pending_sync("owner")
        assert len(claimed) == 1
        assert cls.fail_claimed_sync("owner", [member], "invalid document", events=events) == 1
        assert not (cls.has_event_pending_sync() if events else cls.has_pending_sync())
    assert redis_connection.hlen(dead) == 1
    assert "invalid document" in redis_connection.hget(dead, member)
    redis_connection.eval(queue_retry.ENQUEUE, 2, pending, dead, 99999999, member)
    assert not redis_connection.zcard(pending)
    if events:
        assert redis_connection.hget(cls.EVENT_PAYLOAD_KEY, member) == "payload must survive"
    assert cls.replay_dead_sync(member, events=events)
    assert not redis_connection.hlen(dead)
    assert redis_connection.zcard(pending) == 1


def test_lease_recovery_is_bounded_and_success_clears_budget(monkeypatch, redis_connection):
    from bisheng.telemetry.domain.mid_table import knowledge_space_content as module

    cls = module.KnowledgeSpaceContentStat
    monkeypatch.setattr(
        module,
        "get_redis_client_sync",
        lambda: SimpleNamespace(cluster_nodes=lambda key: None, connection=redis_connection),
    )
    redis_connection.set(cls.LOCK_KEY, "owner")
    redis_connection.zadd(cls.PENDING_KEY, {"file:1": 1, "file:2": 1})
    cls.claim_pending_sync("owner", now_ms=1)
    assert not cls.ack_claimed_sync("old-owner", ["file:2"])
    assert cls.ack_claimed_sync("owner", ["file:2"])
    assert redis_connection.hget(cls.ATTEMPTS_KEY, "file:2") is None
    for attempt in range(1, 7):
        now = attempt * 2000000
        assert cls.reclaim_expired_sync(now_ms=now) == 1
        if attempt < 6:
            assert len(cls.claim_pending_sync("owner", now_ms=now + 1000000)) == 1
    assert redis_connection.hlen(cls.DEAD_KEY) == 1
    assert not redis_connection.zcard(cls.PENDING_KEY)


def test_periodic_dispatch_does_not_reset_budget_or_slide_failed_window(monkeypatch, redis_connection):
    from bisheng.telemetry.domain.mid_table import retry_budget as module

    monkeypatch.setattr(
        module,
        "get_redis_client_sync",
        lambda: SimpleNamespace(cluster_nodes=lambda key: None, connection=redis_connection),
    )
    now, values, scheduled = [1000], [], []
    monkeypatch.setattr(module.time, "time", lambda: now[0])
    fail = [True]

    def sample_task(argument):
        values.append((argument, module.frozen_value("day", lambda: now[0])))
        if fail[0]:
            raise RuntimeError("bad source")
        return {"processed": 1}

    monkeypatch.setitem(
        sample_task.__globals__, "sample_task", SimpleNamespace(apply_async=lambda **kw: scheduled.append(kw))
    )
    wrapped = module.bounded_telemetry_task(sample_task)
    for attempt in range(6):
        now[0] = (attempt + 1) * 1000
        with pytest.raises(RuntimeError, match="bad source"):
            wrapped("original" if attempt == 0 else "new beat invocation")
    assert len(scheduled) == 5
    assert values == [("original", 1000)] * 6
    now[0] = 100000
    assert wrapped("new beat invocation")["retry_state"] == "dead"
    assert len(values) == 6
    module.RunBudget("sample_task").reset()
    fail[0] = False
    wrapped("new beat invocation")
    assert values[-1] == ("original", 1000)
    wrapped("next successful cycle")
    assert values[-1] == ("next successful cycle", 100000)


def test_operator_preview_is_readonly_and_apply_replays_one_item(monkeypatch, redis_connection):
    from bisheng.telemetry.domain.mid_table import knowledge_space_content as content
    from bisheng.telemetry.domain.mid_table import retry_budget as budget
    from scripts import telemetry_retry_control as script

    wrapper = SimpleNamespace(cluster_nodes=lambda key: None, connection=redis_connection)
    for module in (script, content, budget):
        monkeypatch.setattr(module, "get_redis_client_sync", lambda: wrapper)
    cls = content.KnowledgeSpaceContentStat
    redis_connection.hset(cls.DEAD_KEY, "file:1", "failure report")
    dispatched = []
    monkeypatch.setattr(script, "dispatch", lambda *args: dispatched.append(args))
    args = SimpleNamespace(job=None, queue="files", member="file:1", cursor=0, apply=False)
    assert script.execute(args)["before"] == "failure report"
    assert redis_connection.hexists(cls.DEAD_KEY, "file:1") and not dispatched
    args.apply = True
    script.execute(args)
    assert not redis_connection.hexists(cls.DEAD_KEY, "file:1")
    assert redis_connection.zcard(cls.PENDING_KEY) == len(dispatched) == 1


def test_reclaimed_claim_cannot_clear_attempts_and_failed_batch_is_isolated(monkeypatch, redis_connection):
    from bisheng.telemetry.domain.mid_table import knowledge_space_content as module

    cls = module.KnowledgeSpaceContentStat
    monkeypatch.setattr(
        module,
        "get_redis_client_sync",
        lambda: SimpleNamespace(cluster_nodes=lambda key: None, connection=redis_connection),
    )
    redis_connection.set(cls.LOCK_KEY, "owner")
    redis_connection.zadd(cls.PENDING_KEY, {"file:1": 1, "file:2": 1})
    assert len(cls.claim_pending_sync("owner", now_ms=1)) == 2
    cls.reclaim_expired_sync(now_ms=1000000)
    assert not cls.ack_claimed_sync("owner", ["file:1"])
    assert redis_connection.hget(cls.ATTEMPTS_KEY, "file:1") == "1"
    assert len(cls.claim_pending_sync("owner", now_ms=2000000)) == 1
    assert redis_connection.zcard(cls.PENDING_KEY) == 1


def test_recovery_republishes_due_retry_but_never_dead_job(monkeypatch, redis_connection):
    from bisheng.telemetry.domain.mid_table import retry_budget as module

    monkeypatch.setattr(
        module,
        "get_redis_client_sync",
        lambda: SimpleNamespace(cluster_nodes=lambda key: None, connection=redis_connection),
    )
    now = [1000]
    monkeypatch.setattr(module.time, "time", lambda: now[0])
    retry = module.RunBudget("sync_mid_realtime_qa_question_fact")
    assert retry.acquire() == "acquired"
    retry.store("invocation", '{"kwargs": {"start_date": "2026-09-20"}}')
    retry.fail("broker failed")
    dead = module.RunBudget("sync_mid_knowledge_space_content_stat")
    redis_connection.hset(dead.key, mapping={"status": "dead", "attempt": 6})
    now[0] = 2000
    sent = []
    module.recover_due_jobs(lambda name, invocation: sent.append((name, invocation)))
    module.recover_due_jobs(lambda name, invocation: sent.append((name, invocation)))
    assert sent == [("sync_mid_realtime_qa_question_fact", {"kwargs": {"start_date": "2026-09-20"}})]

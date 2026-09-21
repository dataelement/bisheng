"""T076: Coverage AC: AC-20, AC-22, AC-23, AC-24, AC-30, AC-31, AC-34."""

# Load the task adapter without legacy worker/__init__ bootstrapping application YAML.
import importlib.util
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlmodel import Session

from bisheng.core.context.tenant import current_tenant_id
from bisheng.dsh.domain.models.monthly_usage import DshMonthlyUsage
from bisheng.dsh.domain.repositories.usage import DshUsageRepository
from bisheng.dsh.domain.services.projection import DshProjectionService
from test.dsh.test_quota_admission import quota as quota
from test.dsh.test_quota_admission import running
from test.dsh.test_quota_settlement import terminal
from test.dsh.test_usage_repository import usage_db as usage_db

_spec = importlib.util.spec_from_file_location(
    "dsh_usage_task", Path(__file__).resolve().parents[2] / "bisheng/worker/dsh/usage.py"
)
_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_module)
project_user = _module.project_user


async def test_real_stream_sql_replay_and_context_reset(quota, usage_db):
    @contextmanager
    def repository():
        with Session(usage_db) as session, session.begin():
            yield DshUsageRepository(session)

    service = DshProjectionService(quota, repository, consumer="test")
    a = running()
    await quota.check_and_start(a)
    await quota.record_usage(terminal(a), 1)
    saved = current_tenant_id.get()
    assert await project_user({"tenant_id": 2}, 2, 20, service) == 2
    assert current_tenant_id.get() == saved
    stream = quota.keys(a)[5]
    # Replay models an ACK loss or a restarted consumer with redelivery.
    await quota.redis.xgroup_setid(stream, service.group, "0-0")
    assert await project_user({"tenant_id": 2}, 2, 20, service) == 2
    with Session(usage_db) as session:
        assert session.scalar(select(DshMonthlyUsage)).used_tokens == 300
    with pytest.raises(ValueError):
        await project_user({"tenant_id": 3}, 2, 20, service)
    assert current_tenant_id.get() == saved


async def test_expired_running_becomes_unknown(quota, usage_db):
    @contextmanager
    def repository():
        with Session(usage_db) as session, session.begin():
            yield DshUsageRepository(session)

    a = running()
    await quota.check_and_start(a)
    service = DshProjectionService(quota, repository, consumer="test")
    cursor, count = await service.inspect_running(2, 20, now=datetime(2026, 9, 10, tzinfo=UTC), timeout_seconds=30)
    assert cursor == 0 and count == 1
    assert (await quota.get_request(a)).status == "USAGE_UNKNOWN"
    assert await quota.redis.smembers(quota.keys(a)[0].removesuffix(":gate") + ":unknown_usage") == {a.request_id}


async def test_commit_before_ack_loss_and_sql_rollback_keep_pending(quota, usage_db, monkeypatch):
    from redis.exceptions import ConnectionError

    fail_sql = True

    @contextmanager
    def repository():
        with Session(usage_db) as session, session.begin():
            yield DshUsageRepository(session)
            if fail_sql:
                raise RuntimeError("injected SQL commit failure")

    service = DshProjectionService(quota, repository, consumer="faults")
    a = running()
    await quota.check_and_start(a)
    await quota.record_usage(terminal(a), 1)
    with pytest.raises(RuntimeError, match="SQL commit"):
        await project_user({"tenant_id": 2}, 2, 20, service)
    with Session(usage_db) as session:
        assert session.scalar(select(DshMonthlyUsage)) is None
    fail_sql = False
    ack = quota.redis.xack

    async def lost_ack(*args, **kwargs):
        raise ConnectionError("injected ACK loss")

    monkeypatch.setattr(quota.redis, "xack", lost_ack)
    with pytest.raises(ConnectionError):
        await project_user({"tenant_id": 2}, 2, 20, service)
    with Session(usage_db) as session:
        assert session.scalar(select(DshMonthlyUsage)).used_tokens == 300
    monkeypatch.setattr(quota.redis, "xack", ack)
    assert await project_user({"tenant_id": 2}, 2, 20, service) == 2
    assert (await quota.redis.xpending(quota.keys(a)[5], service.group))["pending"] == 0
    with Session(usage_db) as session:
        assert session.scalar(select(DshMonthlyUsage)).used_tokens == 300

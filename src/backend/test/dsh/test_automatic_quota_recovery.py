"""Real Redis/SQL recovery without external evidence, including lost-tail accounting."""

import os
from contextlib import contextmanager
from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine, inspect, select
from sqlmodel import Session, SQLModel

from bisheng.core.context.tenant import current_tenant_id
from bisheng.dsh.domain.models.admin_operation import DshAdminOperation
from bisheng.dsh.domain.models.model_call import DshModelCall
from bisheng.dsh.domain.models.monthly_usage import DshMonthlyUsage
from bisheng.dsh.domain.models.user_policy import DshUserPolicy
from bisheng.dsh.domain.repositories.usage import DshUsageRepository
from bisheng.dsh.domain.services.automatic_quota_recovery import AutomaticQuotaRecovery
from bisheng.dsh.domain.services.projection import DshProjectionService
from bisheng.dsh.infrastructure.quota_redis import QuotaRejected
from test.dsh.test_quota_admission import quota as quota
from test.dsh.test_quota_admission import running
from test.dsh.test_quota_settlement import terminal


@pytest.fixture(params=["sqlite", "mysql"])
def recovery_db(tmp_path, request):
    url = "sqlite:///" + str(tmp_path / "recovery.db")
    if request.param == "mysql":
        if os.environ.get("DSH_TEST_DATABASE_ISOLATED") != "1":
            pytest.skip("Isolated MySQL is not configured")
        url = request.getfixturevalue("dsh_database_url")
    engine = create_engine(url)
    tables = [DshUserPolicy.__table__, DshModelCall.__table__, DshMonthlyUsage.__table__, DshAdminOperation.__table__]
    assert not any(inspect(engine).has_table(table.name) for table in tables), "Refusing existing test tables"
    SQLModel.metadata.create_all(
        engine,
        tables=[
            DshUserPolicy.__table__,
            DshModelCall.__table__,
            DshMonthlyUsage.__table__,
            DshAdminOperation.__table__,
        ],
    )
    token = current_tenant_id.set(2)
    with Session(engine) as session, session.begin():
        session.add(
            DshUserPolicy(
                tenant_id=2,
                user_id=20,
                model_id=4,
                enabled=1,
                version=1,
                monthly_token_limit=1000,
                quota_sync_state="READY",
                updated_by=7,
            )
        )
    yield engine
    current_tenant_id.reset(token)
    SQLModel.metadata.drop_all(engine, tables=list(reversed(tables)))
    engine.dispose()


def connect(quota, engine):
    @contextmanager
    def scope():
        with Session(engine) as session, session.begin():
            yield DshUsageRepository(session)

    quota.recovery = AutomaticQuotaRecovery(quota, scope, billing_timezone="Asia/Shanghai")
    quota.topology.automatic = True
    return scope


async def erase(quota):
    keys = [key async for key in quota.redis.scan_iter(quota.prefix + "*")]
    if keys:
        await quota.redis.delete(*keys)


def persist(engine, events):
    with Session(engine) as session, session.begin():
        DshUsageRepository(session).project_batch(events)


async def test_full_loss_restores_sql_and_reprojection_does_not_double_count(quota, recovery_db):
    event = terminal(running())
    persist(recovery_db, [event])
    await erase(quota)
    scope = connect(quota, recovery_db)
    result = await quota.read_usage(2, 20, "2026-09")
    assert result["used"] == 300 and result["remaining"] == 700
    projector = DshProjectionService(quota, scope, consumer="recovery-test")
    await projector.project_batch(2, 20)
    await projector.project_batch(2, 20)
    with Session(recovery_db) as session:
        assert session.scalar(select(DshMonthlyUsage)).used_tokens == 300
        assert len(list(session.scalars(select(DshModelCall)))) == 1


async def test_partial_loss_preserves_newer_redis_usage_and_running_calls(quota, recovery_db):
    a, b = running(), running()
    await quota.check_and_start(a)
    await quota.check_and_start(b)
    await quota.record_usage(terminal(a), 1)
    persist(recovery_db, [a, b])
    await quota.redis.delete(quota.keys(a)[1], quota.keys(a)[2])
    scope = connect(quota, recovery_db)
    result = await quota.read_usage(2, 20, "2026-09")
    assert result["used"] == 300
    assert (await quota.get_request(b)).status == "RUNNING"
    assert await quota.redis.zcard(quota.keys(b)[0].replace(":gate", ":running")) == 1
    await quota.record_usage(terminal(b), 1)
    projector = DshProjectionService(quota, scope, consumer="survivors-test")
    await projector.project_batch(2, 20)
    assert (await quota.read_usage(2, 20, "2026-09"))["used"] == 600
    with Session(recovery_db) as session:
        assert session.scalar(select(DshMonthlyUsage)).used_tokens == 600


async def test_intact_ledger_does_not_read_sql_or_reset_live_usage(quota, recovery_db):
    connect(quota, recovery_db)
    quota.recovery._snapshot = lambda *_: pytest.fail("Intact ledger must not reload SQL")
    assert (await quota.read_usage(2, 20, "2026-09"))["used"] == 900
    quota.topology.close()
    await quota.topology.activate()
    assert (await quota.read_usage(2, 20, "2026-09"))["used"] == 900


async def test_lost_unpersisted_tail_is_not_invented_and_sql_running_is_unknown(quota, recovery_db):
    a, b = running(), running()
    persist(recovery_db, [a])
    await quota.check_and_start(a)
    await quota.check_and_start(b)
    await quota.record_usage(terminal(a), 1)
    await quota.record_usage(terminal(b), 1)
    await erase(quota)
    scope = connect(quota, recovery_db)
    value = await quota.read_usage(2, 20, "2026-09")
    assert value["used"] == 0 and value["unknown_pending"] == 1
    assert (await quota.get_request(a)).status == "USAGE_UNKNOWN"
    assert await quota.get_request(b) is None
    await DshProjectionService(quota, scope, consumer="lost-tail-test").project_batch(2, 20)
    with Session(recovery_db) as session:
        row = session.scalar(select(DshModelCall))
        assert row.status == "USAGE_UNKNOWN" and row.total_tokens is None
        assert row.error_code == "redis_ledger_lost"


async def test_lease_owner_and_sql_failures_cannot_publish_zero(quota, recovery_db, monkeypatch):
    await erase(quota)
    connect(quota, recovery_db)
    base = quota.keys(running())[0].removesuffix(":gate")
    await quota.redis.set(base + ":automatic_recovery", "other-process", px=30000)
    with pytest.raises(QuotaRejected, match="recovery_in_progress"):
        await quota.read_usage(2, 20, "2026-09")
    assert not await quota.redis.exists(base + ":month:2026-09")
    await quota.redis.delete(base + ":automatic_recovery")
    monkeypatch.setattr(quota.recovery, "_snapshot", lambda *_: (_ for _ in ()).throw(RuntimeError("SQL unavailable")))
    with pytest.raises(RuntimeError, match="SQL unavailable"):
        await quota.read_usage(2, 20, "2026-09")
    assert await quota.redis.hget(base + ":gate", "state") == "FROZEN"
    assert not await quota.redis.exists(base + ":month:2026-09")


async def test_lost_recovery_owner_cannot_finish_or_delete_successor_lease(quota, recovery_db, monkeypatch):
    await erase(quota)
    connect(quota, recovery_db)
    base = quota.keys(running())[0].removesuffix(":gate")
    evaluate = quota.redis.eval

    async def replace_owner(script, numkeys, *args):
        if script == quota.recovery.script and args[numkeys + 1] == "finish":
            await quota.redis.set(base + ":automatic_recovery", "successor", px=30000)
        return await evaluate(script, numkeys, *args)

    monkeypatch.setattr(quota.redis, "eval", replace_owner)
    with pytest.raises(QuotaRejected, match="recovery_fence_lost"):
        await quota.read_usage(2, 20, "2026-09")
    assert await quota.redis.get(base + ":automatic_recovery") == "successor"
    assert await quota.redis.hget(base + ":gate", "state") == "FROZEN"


async def test_policy_changed_during_recovery_is_retried_without_overwrite(quota, recovery_db, monkeypatch):
    await erase(quota)
    connect(quota, recovery_db)
    original = quota.recovery._complete

    def changed(user_id, policy, epoch):
        with Session(recovery_db) as session, session.begin():
            row = session.scalar(select(DshUserPolicy))
            row.monthly_token_limit = 77
            row.version += 1
        original(user_id, policy, epoch)

    monkeypatch.setattr(quota.recovery, "_complete", changed)
    with pytest.raises(ValueError, match="SQL policy changed"):
        await quota.read_usage(2, 20, "2026-09")
    monkeypatch.setattr(quota.recovery, "_complete", original)
    value = await quota.read_usage(2, 20, "2026-09")
    assert value["limit"] == 77


async def test_user_scope_rejected_before_sql_or_redis_mutation(quota, recovery_db):
    connect(quota, recovery_db)
    with pytest.raises(ValueError, match="trusted tenant"):
        await quota.recovery.ensure(3, 20, "2026-09")


@pytest.mark.parametrize("lose_at", [None, "install_policy", "finish_policy"])
async def test_first_policy_and_mid_update_redis_loss_resume_same_intent(quota, recovery_db, monkeypatch, lose_at):
    """AC-27/29: First grant needs no approval, and committed policy updates survive cache loss."""
    from sqlalchemy import event as sql_event

    from bisheng.dsh.domain.repositories.policy import DshPolicyRepository
    from bisheng.dsh.domain.schemas.contracts import DshUserPolicyInput
    from bisheng.dsh.domain.services.admin_policy import DshAdminService

    with Session(recovery_db) as session, session.begin():
        for row in session.scalars(select(DshUserPolicy)):
            session.delete(row)
    await erase(quota)
    connect(quota, recovery_db)

    @contextmanager
    def scope():
        with Session(recovery_db) as session, session.begin():

            def defaults(session, *_):
                for row in session.new:
                    if isinstance(row, (DshUserPolicy, DshAdminOperation)) and row.tenant_id is None:
                        row.tenant_id = 2

            sql_event.listen(session, "before_flush", defaults)
            yield DshPolicyRepository(session)

    async def permitted(*_):
        return True

    if lose_at:
        original = getattr(quota, lose_at)

        async def lose_once(*args, **kwargs):
            await erase(quota)
            monkeypatch.setattr(quota, lose_at, original)
            return await original(*args, **kwargs)

        monkeypatch.setattr(quota, lose_at, lose_once)
    now = datetime(2026, 9, 11)
    service = DshAdminService(
        repository_scope=scope, quota=quota, authorize=permitted, validate_models=permitted, now=lambda: now
    )
    result = await service.update_policy(
        user_id=20,
        model_id=4,
        actor_user_id=7,
        request=DshUserPolicyInput(
            operation_id="auto-first-policy", expected_version=0, monthly_token_limit=345, enabled=True
        ),
    )
    assert result["status"] == "SUCCEEDED"
    value = await quota.read_usage(2, 20, "2026-09")
    assert value["limit"] == 345 and value["quota_state"] == "ready"
    with Session(recovery_db) as session:
        policy = session.scalar(select(DshUserPolicy))
        assert policy.version == 1 and policy.pending_operation_id is None


async def test_generation_change_reconciles_sql_ahead_of_surviving_redis(quota, recovery_db):
    """Redis can restart with a structurally intact but stale persisted snapshot."""
    event = terminal(running())
    persist(recovery_db, [event])
    base = quota.keys(event)[0].removesuffix(":gate")
    await quota.redis.hset(base + ":gate", "redis_generation", "previous-redis-run")
    await quota.redis.hset(base + ":month:2026-09", "used", "0")
    await quota.redis.hset(base + ":models:2026-09", mapping={"4": "0", "5": "0"})
    connect(quota, recovery_db)
    assert (await quota.read_usage(2, 20, "2026-09"))["used"] == 300


async def test_recovery_recounts_stream_entries_when_request_hash_was_lost(quota, recovery_db):
    event = running()
    await quota.check_and_start(event)
    await quota.record_usage(terminal(event), 1)
    await quota.redis.delete(quota.keys(event)[4], quota.keys(event)[1])
    connect(quota, recovery_db)
    await quota.read_usage(2, 20, "2026-09")
    assert await quota.redis.hget(quota.keys(event)[4], "retained_stream_count") == "3"


@pytest.mark.parametrize("stream", [False, True])
async def test_http_model_call_recovers_then_projects_actual_usage(quota, recovery_db, monkeypatch, stream):
    """AC-22/23/34: HTTP -> real quota -> model adapter -> Redis -> SQL, with a fake provider."""
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    import httpx
    from fastapi import FastAPI

    from bisheng.dsh.api.dependencies import get_runtime
    from bisheng.dsh.api.endpoints import models as endpoints
    from bisheng.dsh.domain.repositories.policy import DshPolicyRepository
    from bisheng.dsh.domain.schemas.chat import ChatCapabilities
    from bisheng.dsh.domain.services.model import DshModelService
    from bisheng.dsh.domain.services.usage import DshUsageService
    from bisheng.dsh.runtime import ModelRuntime
    from test.dsh.test_model_service import LLM, principal

    await erase(quota)
    scope = connect(quota, recovery_db)
    llm = LLM()
    llm.continue_stream.set()

    async def read_policy(user_id):
        with Session(recovery_db) as session:
            return DshPolicyRepository(session).get(user_id)

    async def model_loader(model_id):
        return SimpleNamespace(
            id=4, name="e2e-auto-model", model_name="test-model", create_time=datetime.now(), config={}
        ), SimpleNamespace(name="Test", type="openai")

    usage = DshUsageService(quota)
    model = DshModelService(
        policy_reader=read_policy,
        model_loader=model_loader,
        llm_builder=lambda *_: llm,
        capabilities_for=lambda *_: ChatCapabilities(),
        now=lambda: datetime.now(UTC),
        usage=usage,
    )
    settings = SimpleNamespace(billing_timezone="Asia/Shanghai")
    service = ModelRuntime(model, usage, quota, settings)
    runtime = SimpleNamespace(
        settings=settings, access=SimpleNamespace(authenticate=AsyncMock(return_value=principal()))
    )
    monkeypatch.setattr(endpoints, "get_model_runtime", AsyncMock(return_value=service))
    app = FastAPI()
    app.include_router(endpoints.router, prefix="/api/v1")
    app.dependency_overrides[get_runtime] = lambda: runtime
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://e2e-dsh-auto") as client:
        denied = await client.post(
            "/api/v1/dsh/chat/completions",
            json={"model": "bisheng:4", "messages": [{"role": "user", "content": "test"}]},
        )
        assert denied.status_code == 401 and llm.calls == 0
        body = {"model": "bisheng:4", "messages": [{"role": "user", "content": "test"}], "stream": stream}
        if stream:
            body["stream_options"] = {"include_usage": True}
        response = await client.post(
            "/api/v1/dsh/chat/completions", headers={"Authorization": "Bearer e2e-desktop"}, json=body
        )
        assert response.status_code == 200, response.text
        if stream:
            assert "[DONE]" in response.text and '"total_tokens":12' in response.text
        else:
            assert response.json()["usage"]["total_tokens"] == 12
        live = await client.get("/api/v1/dsh/usage", headers={"Authorization": "Bearer e2e-desktop"})
        assert live.status_code == 200
    await DshProjectionService(quota, scope, consumer="e2e-http").project_batch(2, 20)
    with Session(recovery_db) as session:
        assert session.scalar(select(DshMonthlyUsage)).used_tokens == 12
        row = session.scalar(select(DshModelCall))
        assert row.status == "SUCCEEDED" and row.total_tokens == 12


async def test_storage_uncertainty_is_recovered_without_manual_approval(quota, recovery_db):
    connect(quota, recovery_db)
    event = running()
    await quota.redis.sadd(quota.keys(event)[3], "STORAGE_UNCERTAIN:lost-response")
    value = await quota.read_usage(2, 20, "2026-09")
    assert value["quota_state"] == "ready" and value["used"] == 900
    assert not await quota.redis.sismember(quota.keys(event)[3], "STORAGE_UNCERTAIN:lost-response")


async def test_actual_redis_restart_preserves_persisted_usage(recovery_db, tmp_path):
    """AC-34: Restart only a disposable Redis owned by this test, with AOF data retained."""
    import asyncio
    import shutil
    import socket
    import subprocess
    from uuid import uuid4

    from redis.exceptions import RedisError

    from bisheng.dsh.infrastructure.quota_redis import QuotaRedis
    from bisheng.dsh.infrastructure.quota_topology import QuotaTopology, create_quota_redis

    binary = os.environ.get("DSH_TEST_REDIS_SERVER") or shutil.which("redis-server")
    if not binary:
        pytest.skip("Redis server binary is not configured")
    with socket.socket() as address:
        address.bind(("127.0.0.1", 0))
        port = address.getsockname()[1]
    command = [
        binary,
        "--bind",
        "127.0.0.1",
        "--port",
        str(port),
        "--dir",
        str(tmp_path),
        "--appendonly",
        "yes",
        "--appendfsync",
        "always",
        "--save",
        "",
    ]
    process = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    redis = create_quota_redis(f"redis://127.0.0.1:{port}/0")
    store = QuotaRedis(redis, QuotaTopology(redis, shared=True, automatic=True), prefix="e2e_dsh_auto_" + uuid4().hex)

    async def wait_ready():
        for _ in range(100):
            try:
                await store.topology.activate()
                return
            except RedisError:
                await asyncio.sleep(0.05)
        raise AssertionError("Disposable Redis did not start")

    try:
        await wait_ready()
        connect(store, recovery_db)
        assert (await store.read_usage(2, 20, "2026-09"))["used"] == 0
        event = running()
        await store.check_and_start(event)
        await store.record_usage(terminal(event), 1)
        old_run = store.topology.run_id
        await redis.shutdown(save=True)
        process.wait(timeout=10)
        process = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        await wait_ready()
        assert store.topology.run_id != old_run
        assert (await store.read_usage(2, 20, "2026-09"))["used"] == 300
    finally:
        await redis.aclose()
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=10)


async def test_two_independent_redis_clients_cannot_restore_the_same_user_concurrently(quota, recovery_db, monkeypatch):
    import asyncio
    import threading

    from bisheng.dsh.infrastructure.quota_redis import QuotaRedis
    from bisheng.dsh.infrastructure.quota_topology import QuotaTopology, create_quota_redis

    event = terminal(running())
    persist(recovery_db, [event])
    await erase(quota)
    connect(quota, recovery_db)
    redis = create_quota_redis(os.environ["DSH_TEST_REDIS_URL"])
    other = QuotaRedis(redis, QuotaTopology(redis, shared=True, automatic=True), prefix=quota.prefix)
    connect(other, recovery_db)
    started, release = threading.Event(), threading.Event()
    original = quota.recovery._snapshot

    def delayed(user_id):
        started.set()
        assert release.wait(5), "Test release timed out"
        return original(user_id)

    monkeypatch.setattr(quota.recovery, "_snapshot", delayed)
    first = asyncio.create_task(quota.read_usage(2, 20, "2026-09"))
    try:
        assert await asyncio.to_thread(started.wait, 5)
        with pytest.raises(QuotaRejected, match="recovery_in_progress"):
            await other.read_usage(2, 20, "2026-09")
        release.set()
        assert (await first)["used"] == 300
        other.recovery._snapshot = lambda *_: pytest.fail("Successor must reuse the restored ledger")
        assert (await other.read_usage(2, 20, "2026-09"))["used"] == 300
    finally:
        release.set()
        await first
        await redis.aclose()

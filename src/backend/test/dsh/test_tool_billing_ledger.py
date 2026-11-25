"""Tests for unified tool + model ledger (Lua scripts, QuotaRedis, Projection, Recovery, Repository) (AC-25, AC-26)."""

import json
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from sqlalchemy import Column, DateTime, Integer, MetaData, Table, create_engine, select
from sqlmodel import Session, SQLModel

from bisheng.core.context.tenant import current_tenant_id
from bisheng.database.models.department import Department, UserDepartment
from bisheng.database.models.role import Role
from bisheng.database.models.tenant import Tenant, UserTenant
from bisheng.dsh.domain.models.admin_operation import DshAdminOperation
from bisheng.dsh.domain.models.model_call import DshModelCall
from bisheng.dsh.domain.models.monthly_usage import DshMonthlyUsage
from bisheng.dsh.domain.models.subject_policy import DshSubjectPolicy, DshSubjectPolicyAudit
from bisheng.dsh.domain.models.tool_call import DshToolCall
from bisheng.dsh.domain.models.unified_policy import CreditRule, ModelVisibility, PersonalLedgerState
from bisheng.dsh.domain.models.user_policy import DshUserPolicy
from bisheng.dsh.domain.repositories.policy import DshPolicyRepository
from bisheng.dsh.domain.repositories.usage import DshUsageRepository
from bisheng.dsh.domain.schemas.usage import UsageEvent
from bisheng.dsh.infrastructure.quota_redis import QuotaRedis, QuotaRejected
from bisheng.user.domain.models.user import User
from test.dsh.test_quota_admission import quota as quota

LUA_DIR = Path(__file__).resolve().parents[2] / "bisheng/dsh/infrastructure/lua"


def _tool_event(user_id=20, tool_id=4, billed_tokens=2000, **overrides):
    from bisheng.dsh.domain.schemas.usage import ToolPricingSnapshot, ToolUsageEvent

    payload = {
        "request_id": str(uuid4()),
        "tenant_id": 2,
        "user_id": user_id,
        "usage_month": "2026-11",
        "billing_timezone": "Asia/Shanghai",
        "quota_epoch": 1,
        "event_version": 1,
        "tool_group_id": 100,
        "tool_group_name": "BuiltIn Tools",
        "tool_id": tool_id,
        "tool_key": "web_search",
        "engine": "bing",
        "pricing_snapshot": ToolPricingSnapshot(
            pricing_mode="CREDITS",
            currency=None,
            price_micro=2_000_000,
            call_count=1,
            credit_value_micro=1_000_000,
        ),
        "billed_tokens": billed_tokens,
        "cost_micro": None,
        "currency": None,
        "result": "success",
        "source_type": "assistant",
        "source_id": "ast-1",
        "started_at": datetime(2026, 11, 24, 10, 0, tzinfo=UTC),
        "ended_at": datetime(2026, 11, 24, 10, 0, 1, tzinfo=UTC),
    }
    payload.update(overrides)
    return ToolUsageEvent(**payload)


def _model_event(user_id=20, model_id=4, billed_tokens=500, **overrides):
    payload = {
        "request_id": str(uuid4()),
        "tenant_id": 2,
        "user_id": user_id,
        "session_id": str(uuid4()),
        "model_id": model_id,
        "usage_month": "2026-11",
        "billing_timezone": "Asia/Shanghai",
        "policy_version": 1,
        "event_version": 2,
        "quota_epoch": 1,
        "status": "SUCCEEDED",
        "usage_source": "PROVIDER",
        "input_tokens": max(0, billed_tokens - 50),
        "output_tokens": min(50, billed_tokens),
        "total_tokens": billed_tokens,
        "credit_rate": 100,
        "source_type": "workflow",
        "source_id": "wf-9",
        "started_at": datetime(2026, 11, 24, 9, 0, tzinfo=UTC),
        "ended_at": datetime(2026, 11, 24, 9, 0, 2, tzinfo=UTC),
    }
    payload.update(overrides)
    return UsageEvent(**payload)


@pytest.fixture
def ledger_db(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'tool_ledger.db'}")
    role_table = Table(
        "userrole",
        MetaData(),
        Column("id", Integer, primary_key=True),
        Column("user_id", Integer),
        Column("role_id", Integer),
        Column("tenant_id", Integer),
        Column("create_time", DateTime),
        Column("update_time", DateTime),
    )
    tables = [
        Tenant.__table__,
        User.__table__,
        UserTenant.__table__,
        Department.__table__,
        UserDepartment.__table__,
        Role.__table__,
        role_table,
        CreditRule.__table__,
        ModelVisibility.__table__,
        PersonalLedgerState.__table__,
        DshUserPolicy.__table__,
        DshSubjectPolicy.__table__,
        DshSubjectPolicyAudit.__table__,
        DshModelCall.__table__,
        DshToolCall.__table__,
        DshMonthlyUsage.__table__,
        DshAdminOperation.__table__,
    ]
    SQLModel.metadata.create_all(engine, tables=tables)
    token = current_tenant_id.set(2)
    try:
        with Session(engine) as session, session.begin():
            session.add(Tenant(id=2, tenant_name="Sub", tenant_code="sub"))
            session.add(
                Department(
                    id=200,
                    dept_id="BS@sub200",
                    name="SubDept",
                    parent_id=None,
                    is_tenant_root=0,
                    path="/200/",
                    tenant_id=2,
                )
            )
            session.add_all(
                [
                    User(user_id=20, user_name="u20", password="x"),
                    User(user_id=21, user_name="u21", password="x"),
                    UserTenant(user_id=20, tenant_id=2, is_active=1, is_default=1),
                    UserTenant(user_id=21, tenant_id=2, is_active=1, is_default=1),
                    UserDepartment(id=1, user_id=20, department_id=200, tenant_id=2, is_primary=1),
                    UserDepartment(id=2, user_id=21, department_id=200, tenant_id=2, is_primary=1),
                ]
            )
            session.add(
                DshUserPolicy(
                    tenant_id=2,
                    user_id=20,
                    model_id=4,
                    monthly_token_limit=10_000,
                    enabled=1,
                    version=1,
                    quota_sync_state="READY",
                    updated_by=1,
                )
            )
            session.add(PersonalLedgerState(tenant_id=2, user_id=20, version=1, quota_epoch=1))
            session.add(ModelVisibility(tenant_id=2, model_id=4, everyone=True, subjects=[], updated_by=1))
            session.add(
                CreditRule(
                    tenant_id=2,
                    subject_type="USER",
                    subject_id=20,
                    monthly_token_limit=10_000,
                    enabled=True,
                    updated_by=1,
                )
            )
        yield engine
    finally:
        current_tenant_id.reset(token)
        engine.dispose()


def test_tool_usage_event_and_model_event_source_contracts():
    model_ev = _model_event(source_type="assistant", source_id="a1")
    assert model_ev.source_type == "assistant"
    assert model_ev.source_id == "a1"

    tool_ev = _tool_event()
    assert tool_ev.event_kind == "tool"
    assert tool_ev.billed_tokens == 2000
    assert tool_ev.status == "SUCCEEDED"


def test_lua_scripts_exist_and_include_tools_conservation_equation():
    check_lua = (LUA_DIR / "check_tool_quota.lua").read_text()
    record_lua = (LUA_DIR / "record_tool_usage.lua").read_text()
    admit_lua = (LUA_DIR / "admit.lua").read_text()
    read_usage_lua = (LUA_DIR / "read_usage.lua").read_text()
    policy_lua = (LUA_DIR / "policy.lua").read_text()

    assert "quota_exceeded" in check_lua
    assert "unmetered" in check_lua
    assert "'event_kind','tool'" in record_lua or '"event_kind","tool"' in record_lua
    assert "KEYS[9]" in admit_lua  # optional :tools:{YM} ledger contribution
    assert "KEYS[8]" in read_usage_lua  # optional :tools:{YM} ledger contribution
    assert "#KEYS,3" in policy_lua  # (month, models, tools) triples in policy install


async def test_quota_redis_tool_methods_and_ledger_key_wiring():
    eval_calls = []

    class _FakeRedis:
        async def hget(self, key, field):
            return "1" if field == "epoch" else None

        async def scan_iter(self, match):
            if False:
                yield match

        async def eval(self, script, numkeys, *args):
            eval_calls.append((script, numkeys, list(args[:numkeys]), list(args[numkeys:])))
            if numkeys == 8:
                return ["OK", "0", "10000", "READY", "1700000000", "0", [], "0", [], "shared"]
            return ["OK", "0", "10000"]

    class _Topo:
        lock = AsyncMock()
        epoch = 1
        automatic = False
        run_id = "run-1"

        def __init__(self):
            self.lock.__aenter__ = AsyncMock(return_value=None)
            self.lock.__aexit__ = AsyncMock(return_value=False)

        async def check(self):
            return None

        def close(self):
            return None

    quota = QuotaRedis(_FakeRedis(), _Topo(), prefix="dsh_test")
    ev = _tool_event()

    await quota.check_tool_quota(tenant_id=2, user_id=20, usage_month="2026-11", monthly_token_limit=10000)
    await quota.record_tool_usage(ev)
    await quota.read_usage(2, 20, "2026-11")
    await quota.install_policy(
        2,
        20,
        model_id=4,
        operation_id="op-1",
        lease_generation=1,
        epoch=1,
        expected_version=0,
        version=1,
        monthly_token_limit=10000,
        enabled=True,
    )

    assert len(eval_calls) == 4
    # read_usage passes :tools:2026-11 as 8th key
    _, numkeys, keys, _ = eval_calls[2]
    assert numkeys == 8
    assert keys[7].endswith(":tools:2026-11")
    # check_tool_quota checks rejection properly
    quota.redis.eval = AsyncMock(return_value=["DENY", "quota_exceeded"])
    with pytest.raises(QuotaRejected, match="quota_exceeded"):
        await quota.check_tool_quota(tenant_id=2, user_id=20, usage_month="2026-11")


async def test_real_redis_rebuilds_a_month_with_both_model_and_tool_usage(quota, ledger_db):
    from bisheng.dsh.domain.services.automatic_quota_recovery import AutomaticQuotaRecovery

    @contextmanager
    def scope():
        with Session(ledger_db) as session, session.begin():
            yield DshUsageRepository(session)

    model = _model_event(billed_tokens=300)
    tool = _tool_event(billed_tokens=700)
    with scope() as repository:
        repository.project_batch([model, tool])

    recovery = AutomaticQuotaRecovery(quota, scope, billing_timezone="Asia/Shanghai")
    await recovery.ensure(2, 20, tool.usage_month)
    base = f"{quota.prefix}:{{2:20}}"
    assert await recovery.healthy(base, tool.usage_month)
    assert await quota.redis.hget(base + f":month:{tool.usage_month}", "used") == "1000"
    assert await quota.redis.hget(base + f":tools:{tool.usage_month}", str(tool.tool_id)) == "700"


@pytest.mark.parametrize("stream_error", ["wrong_type", "append_failed"])
async def test_real_redis_retries_failed_tool_settlement_without_double_charging(quota, ledger_db, stream_error):
    from bisheng.dsh.domain.services.projection import DshProjectionService
    from bisheng.dsh.domain.services.usage_dispatch import UsageDispatcher

    @contextmanager
    def scope():
        with Session(ledger_db) as session, session.begin():
            yield DshUsageRepository(session)

    tool = _tool_event(usage_month="2026-09", billed_tokens=700)
    base = f"{quota.prefix}:{{2:20}}"
    events = base + ":events"
    total = base + f":month:{tool.usage_month}"
    if stream_error == "wrong_type":
        await quota.redis.set(events, "not a stream")
    else:
        await quota.redis.xadd(events, {"event": "placeholder"}, id="18446744073709551615-18446744073709551615")
    projection = DshProjectionService(quota, scope, consumer="tool-retry")
    dispatcher = UsageDispatcher(projection)
    await dispatcher.work.mark(events)
    claim = await dispatcher.work.claim()
    await quota.stage_tool_usage(tool)
    await dispatcher.work.finish(claim)
    assert await quota.redis.zscore(dispatcher.work.ready, events) is not None
    reason = "bad_event_stream_type" if stream_error == "wrong_type" else "event_append_failed"
    with pytest.raises(QuotaRejected, match=reason):
        await quota.record_tool_usage(tool)
    assert await quota.redis.hget(total, "used") == "900"
    assert await quota.redis.hget(base + ":gate", "write_in_progress") != "1"
    with scope() as repository:
        assert repository.session.get(DshToolCall, tool.request_id) is None
    await quota.redis.zadd(dispatcher.work.ready, {events: 0})
    assert await dispatcher.dispatch(max_users=1) == 0
    assert await quota.redis.zscore(dispatcher.work.ready, events) is not None
    await quota.redis.delete(events)
    await quota.redis.zadd(dispatcher.work.ready, {events: 0})
    assert await dispatcher.dispatch(max_users=1) == 1
    await quota.record_tool_usage(tool)
    assert await quota.redis.hget(total, "used") == "1600"
    assert await quota.redis.xlen(events) == 1
    with scope() as repository:
        call = repository.session.get(DshToolCall, tool.request_id)
        assert call is not None and call.billed_tokens == 700


async def test_automatic_quota_recovery_healthy_and_rebuild_include_tools(ledger_db):
    from bisheng.dsh.domain.services.automatic_quota_recovery import AutomaticQuotaRecovery

    model_ev = _model_event(billed_tokens=1500)
    tool_ev = _tool_event(tool_id=7, billed_tokens=2500)
    with Session(ledger_db) as session, session.begin():
        DshUsageRepository(session).project_batch([model_ev, tool_ev])

    class _HealthyRedis:
        def __init__(self, hashes):
            self.hashes = hashes
            self.eval_calls = []

        async def hgetall(self, key):
            return dict(self.hashes.get(key, {}))

        async def hsetnx(self, key, field, val):
            return 0

        async def zcard(self, key):
            return 0

        async def smembers(self, key):
            return set()

        async def eval(self, script, numkeys, *args):
            self.eval_calls.append((numkeys, list(args[:numkeys]), list(args[numkeys:])))
            return ["OK"]

        async def set(self, *args, **kwargs):
            return True

        async def xrange(self, *args, **kwargs):
            return []

        async def scan(self, *args, **kwargs):
            return 0, []

    base = "dsh_quota:{2:20}"
    gate = {
        "redis_generation": "run-1",
        "state": "READY",
        "policy_revision_schema": "2",
        "quota_limit_schema": "shared",
        "limit": "10000",
        "write_in_progress": "0",
        "running_index": "1",
        "running_count": "0",
        "epoch": "1",
        "model:4": "1",
        "limit:4": "10000",
    }
    valid_hashes = {
        base + ":gate": gate,
        base + ":month:2026-11": {"used": "4000", "epoch": "1", "state": "READY"},
        base + ":models:2026-11": {"_initialized": "1", "4": "1500"},
        base + ":tools:2026-11": {"_initialized": "1", "7": "2500"},
    }
    topo = SimpleNamespace(
        run_id="run-1",
        lock=AsyncMock(__aenter__=AsyncMock(return_value=None), __aexit__=AsyncMock(return_value=False)),
        check=AsyncMock(return_value=None),
        close=lambda: None,
        approve=AsyncMock(return_value=1),
    )

    @contextmanager
    def scope():
        with Session(ledger_db) as session, session.begin():
            yield DshUsageRepository(session)

    recovery_ok = AutomaticQuotaRecovery(
        QuotaRedis(_HealthyRedis(valid_hashes), topo, prefix="dsh_quota"), scope, billing_timezone="Asia/Shanghai"
    )
    assert await recovery_ok.healthy(base, "2026-11") is True

    # Missing :tools hash still healthy when sum(models) == month.used
    legacy_hashes = {
        base + ":gate": gate,
        base + ":month:2026-11": {"used": "1500", "epoch": "1", "state": "READY"},
        base + ":models:2026-11": {"_initialized": "1", "4": "1500"},
    }
    assert (
        await AutomaticQuotaRecovery(
            QuotaRedis(_HealthyRedis(legacy_hashes), topo, prefix="dsh_quota"), scope, billing_timezone="Asia/Shanghai"
        ).healthy(base, "2026-11")
        is True
    )

    # Mismatched tool sum returns False
    broken = dict(valid_hashes)
    broken[base + ":month:2026-11"] = {"used": "1500", "epoch": "1", "state": "READY"}
    assert (
        await AutomaticQuotaRecovery(
            QuotaRedis(_HealthyRedis(broken), topo, prefix="dsh_quota"), scope, billing_timezone="Asia/Shanghai"
        ).healthy(base, "2026-11")
        is False
    )

    # ensure() rebuilds :month.used = model + tool, writes :models and :tools
    rebuilder = _HealthyRedis({})
    recovery_rebuild = AutomaticQuotaRecovery(
        QuotaRedis(rebuilder, topo, prefix="dsh_quota"), scope, billing_timezone="Asia/Shanghai"
    )
    await recovery_rebuild.ensure(2, 20, "2026-11")
    month_calls = [call for call in rebuilder.eval_calls if len(call[2]) >= 2 and call[2][1] == "month"]
    assert month_calls
    _, keys, args = month_calls[0]
    assert keys[4].endswith(":tools:2026-11")
    assert args[4] == "4000"  # 1500 + 2500
    assert json.loads(args[5]) == {"4": "1500"}
    assert json.loads(args[6]) == {"7": "2500"}


def test_usage_repository_projects_tools_persists_combined_and_blocks_proofs(ledger_db):
    model_ev = _model_event(model_id=4, billed_tokens=300)
    tool_ev = _tool_event(tool_id=4, billed_tokens=700)  # intentionally shares id=4 with model_id!
    with Session(ledger_db) as session, session.begin():
        repo = DshUsageRepository(session)
        changed = repo.project_batch([model_ev, tool_ev])
        assert changed == 2
        # Re-projecting same tool event must be idempotent
        assert repo.project_batch([tool_ev]) == 0

    with Session(ledger_db) as session:
        repo = DshUsageRepository(session)
        usage_rows = list(session.scalars(select(DshMonthlyUsage).where(DshMonthlyUsage.user_id == 20)))
        assert {(r.usage_type, r.model_id, r.used_tokens) for r in usage_rows} == {
            ("MODEL", 4, 300),
            ("TOOL", 4, 700),
        }
        call_row = session.get(DshModelCall, model_ev.request_id)
        assert (call_row.source_type, call_row.source_id) == ("workflow", "wf-9")
        tool_row = session.get(DshToolCall, tool_ev.request_id)
        assert tool_row.billed_tokens == 700 and tool_row.tool_key == "web_search"
        persisted = repo.persisted_usage(20, "2026-11")
        assert persisted["used"] == 1000
        assert persisted["models"] == {"4": 300}
        assert persisted["tools"] == {"4": 700}

        # new_month_proof must reject even when month has only tool calls
    tool_only_ev = _tool_event(user_id=20, tool_id=9, usage_month="2026-12", billed_tokens=100)
    with Session(ledger_db) as session2, session2.begin():
        DshUsageRepository(session2).project_batch([tool_only_ev])
    with Session(ledger_db) as session3:
        with pytest.raises(ValueError, match="Month history is not proven empty"):
            DshUsageRepository(session3).new_month_proof(20, "2026-12")


def test_new_user_proof_rejects_when_tool_call_exists(ledger_db):
    with Session(ledger_db) as session, session.begin():
        session.add(
            DshUserPolicy(
                tenant_id=2,
                user_id=21,
                model_id=4,
                monthly_token_limit=5000,
                enabled=1,
                version=0,
                quota_sync_state="PENDING",
                pending_operation_id="op-u21",
                updated_by=1,
            )
        )
        session.add(
            DshAdminOperation(
                operation_id="op-u21",
                tenant_id=2,
                user_id=21,
                action="UPDATE_POLICY",
                expected_policy_version=0,
                payload_hash="0" * 64,
                payload={"model_id": 4, "monthly_token_limit": 5000, "enabled": 1},
                lease_generation=1,
                lease_until=datetime(2099, 1, 1, tzinfo=UTC),
                status="PROCESSING",
                actor_user_id=1,
            )
        )
        session.add(
            DshToolCall(
                request_id=str(uuid4()),
                tenant_id=2,
                user_id=21,
                usage_month="2026-11",
                tool_group_id=1,
                tool_id=5,
                tool_key="web_search",
                billed_tokens=100,
                result="success",
            )
        )
    with Session(ledger_db) as session:
        proof = DshPolicyRepository(session).new_user_proof("op-u21", 1, now=datetime(2026, 11, 24))
        assert proof is None


async def test_projection_service_parses_mixed_stream_events(ledger_db):
    from bisheng.dsh.domain.services.projection import DshProjectionService

    model_ev = _model_event()
    tool_ev = _tool_event()

    class _StreamRedis:
        def __init__(self):
            self.acked = []
            self.hsets = []

        async def eval(self, *args, **kwargs):
            return 1

        async def xgroup_create(self, *args, **kwargs):
            return None

        async def exists(self, key):
            return 1

        async def xinfo_groups(self, key):
            return [{"name": "dsh-sql-projection-v1", "lag": 0, "pending": 0, "last-delivered-id": "2-0"}]

        async def xpending_range(self, *args, **kwargs):
            return []

        async def xrange(self, *args, **kwargs):
            return []

        async def time(self):
            return [1700000000, 0]

        async def hset(self, key, field, val):
            self.hsets.append((key, field, val))

        async def xautoclaim(self, *args, **kwargs):
            return ["0-0", [], []]

        async def xreadgroup(self, *args, **kwargs):
            return [
                (
                    "dsh_quota:{2:20}:events",
                    [
                        ("1-0", {"event": model_ev.model_dump_json()}),
                        ("2-0", {"event": tool_ev.model_dump_json(), "event_kind": "tool"}),
                    ],
                )
            ]

        async def xack(self, stream, group, *ids):
            self.acked.extend(ids)

    topo = SimpleNamespace(
        lock=AsyncMock(__aenter__=AsyncMock(return_value=None), __aexit__=AsyncMock(return_value=False)),
        check=AsyncMock(return_value=None),
    )

    @contextmanager
    def scope():
        with Session(ledger_db) as session, session.begin():
            yield DshUsageRepository(session)

    redis = _StreamRedis()
    svc = DshProjectionService(QuotaRedis(redis, topo, prefix="dsh_quota"), scope, consumer="test-worker")
    processed = await svc.project_batch(2, 20)
    assert processed == 2
    assert redis.acked == ["1-0", "2-0"]
    with Session(ledger_db) as session:
        assert session.get(DshModelCall, model_ev.request_id) is not None
        assert session.get(DshToolCall, tool_ev.request_id) is not None

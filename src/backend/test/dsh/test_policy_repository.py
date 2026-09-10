"""覆盖 AC: AC-27, AC-28, AC-29, AC-30. SQL transactions, not process-local locks."""

from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine, event
from sqlmodel import Session

from bisheng.common.errcode.dsh import DshOperationConflictError, DshOperationInProgressError
from bisheng.core.context.tenant import current_tenant_id, set_current_tenant_id
from bisheng.core.database import tenant_filter
from bisheng.dsh.domain.models.admin_operation import DshAdminOperation
from bisheng.dsh.domain.models.model_call import DshModelCall
from bisheng.dsh.domain.models.monthly_usage import DshMonthlyUsage
from bisheng.dsh.domain.models.user_policy import DshUserPolicy
from bisheng.dsh.domain.repositories.admin_operation import DshOperationRepository
from bisheng.dsh.domain.repositories.policy import DshPolicyRepository
from bisheng.dsh.domain.schemas.model_policy import DshModelQuotaConfig

NOW = datetime(2026, 9, 9, 2)


@pytest.fixture(params=["sqlite", "external"])
def sql_store(tmp_path, monkeypatch, request):
    monkeypatch.setattr(tenant_filter, "_force_import_all_models", lambda: None)
    monkeypatch.setattr(tenant_filter, "_tenant_aware_tables", set(tenant_filter._tenant_aware_tables))
    initialized = tenant_filter._initialized
    with Session() as probe:
        previous = {name: set(getattr(probe.dispatch, name)) for name in ("do_orm_execute", "before_flush")}
    tenant_filter.register_tenant_filter_events()
    tenant_filter._tenant_aware_tables.update(
        {"dsh_user_policy", "dsh_admin_operation", "dsh_model_call", "dsh_monthly_usage"}
    )
    if request.param == "external":
        database_url = request.getfixturevalue("dsh_database_url")
        engine = create_engine(database_url, pool_pre_ping=True)
        if engine.dialect.name not in {"mysql", "dm", "dm8"}:
            raise ValueError("External policy tests require MySQL or DM8")
        # This fixture owns only these tables in the explicitly isolated database.
        DshModelCall.__table__.drop(engine, checkfirst=True)
        DshMonthlyUsage.__table__.drop(engine, checkfirst=True)
        DshAdminOperation.__table__.drop(engine, checkfirst=True)
        DshUserPolicy.__table__.drop(engine, checkfirst=True)
    else:
        engine = create_engine(f"sqlite:///{tmp_path / 'policy.db'}")

    # Python 3.11 sqlite3 legacy mode otherwise releases SAVEPOINT outside BEGIN.
    if request.param == "sqlite":

        @event.listens_for(engine, "connect")
        def explicit_transactions(connection, _record):
            connection.isolation_level = None

        @event.listens_for(engine, "begin")
        def begin_transaction(connection):
            connection.exec_driver_sql("BEGIN")

    DshUserPolicy.__table__.create(engine)
    DshAdminOperation.__table__.create(engine)
    DshModelCall.__table__.create(engine)
    DshMonthlyUsage.__table__.create(engine)
    token = set_current_tenant_id(2)
    yield engine
    current_tenant_id.reset(token)
    if request.param == "external":
        for model in (DshModelCall, DshMonthlyUsage, DshAdminOperation, DshUserPolicy):
            model.__table__.drop(engine, checkfirst=True)
    engine.dispose()
    with Session() as probe:
        for name, listeners in previous.items():
            for listener in set(getattr(probe.dispatch, name)) - listeners:
                event.remove(Session, name, listener)
    tenant_filter._initialized = initialized


def register(session, op="a", expected=0, actor=90, models=None, limit=100):
    return DshPolicyRepository(session).register_update(
        operation_id=op,
        user_id=20,
        actor_user_id=actor,
        expected_version=expected,
        model_id=2 if models is None else models[0],
        monthly_token_limit=limit,
        enabled=True,
    )


def finish(session, op="a", now=NOW):
    operations = DshOperationRepository(session)
    lease = operations.claim(op, now=now, lease_seconds=30)
    policy = DshPolicyRepository(session)
    policy.commit_update(op, lease.lease_generation, now=now)
    policy.mark_ready(op, lease.lease_generation, now=now)
    return policy.complete_update(op, lease.lease_generation, now=now)


def test_atomic_rollback_and_idempotent_first_update(sql_store):
    with Session(sql_store) as session:
        with pytest.raises(RuntimeError), session.begin():
            register(session)
            raise RuntimeError("simulated crash")
    with Session(sql_store) as session, session.begin():
        assert DshPolicyRepository(session).get(20) is None
        assert DshOperationRepository(session).get("a") is None
        register(session)
        finish(session)
    with Session(sql_store) as session, session.begin():
        assert register(session).status == "SUCCEEDED"
        policy = DshPolicyRepository(session).get(20)
        assert (policy.version, policy.allowed_model_ids, policy.monthly_token_limit) == (1, [2], 100)
        assert policy.pending_operation_id is None
        assert policy.quota_sync_state == "READY"


def test_intent_conflicts_and_owner_exclusivity(sql_store):
    with Session(sql_store) as session, session.begin():
        register(session)
        with pytest.raises(DshOperationConflictError):
            register(session, actor=91)
        with pytest.raises(DshOperationConflictError):
            register(session, limit=99)
        with pytest.raises(DshOperationInProgressError):
            register(session, op="b")
        finish(session)
        with pytest.raises(DshOperationConflictError):
            register(session, op="b")


def test_lease_takeover_fences_old_worker_and_preserves_snapshot(sql_store):
    with Session(sql_store) as session, session.begin():
        register(session)
        operations = DshOperationRepository(session)
        first = operations.claim("a", now=NOW, lease_seconds=1).lease_generation
        with pytest.raises(DshOperationInProgressError):
            operations.claim("a", now=NOW, lease_seconds=1)
        second = operations.claim("a", now=NOW + timedelta(seconds=2), lease_seconds=30).lease_generation
        policy = DshPolicyRepository(session)
        with pytest.raises(DshOperationConflictError):
            policy.commit_update("a", first, now=NOW + timedelta(seconds=2))
        policy.commit_update("a", second, now=NOW + timedelta(seconds=2))
        snapshot = operations.get("a").after_values.copy()
        policy.commit_update("a", second, now=NOW + timedelta(seconds=3))
        assert operations.get("a").after_values == snapshot
        assert policy.get(20).version == 1
        policy.mark_ready("a", second, now=NOW + timedelta(seconds=3))
        policy.complete_update("a", second, now=NOW + timedelta(seconds=3))
        with pytest.raises(DshOperationConflictError):
            operations.set_phase("a", first, "OLD_WORKER", now=NOW + timedelta(seconds=3))


def test_sequential_history_retains_actor_and_versions(sql_store):
    with Session(sql_store) as session, session.begin():
        register(session)
        finish(session)
        register(session, op="b", expected=1, actor=91, models=[2], limit=200)
        finish(session, op="b")
        history = DshOperationRepository(session).list_for_user(20)
        assert [op.operation_id for op in history] == ["a", "b"]
        assert history[0].before_values == {"version": 0, "model_id": 2, "monthly_token_limit": 0, "enabled": False}
        assert history[0].after_values["version"] == history[1].before_values["version"] == 1
        assert history[0].actor_user_id == 90 and history[1].actor_user_id == 91
        assert history[0].committed_at <= history[0].effective_at


def test_two_tenants_and_reused_session_do_not_leak(sql_store):
    with Session(sql_store) as session, session.begin():
        register(session)
        token = set_current_tenant_id(3)
        try:
            assert DshPolicyRepository(session).get(20) is None
            assert DshOperationRepository(session).get("a") is None
            register(session, op="b", actor=91)
            assert DshPolicyRepository(session).get(20).tenant_id == 3
        finally:
            current_tenant_id.reset(token)
        assert DshPolicyRepository(session).get(20).pending_operation_id == "a"


def test_failed_uncommitted_operation_releases_only_its_owner(sql_store):
    with Session(sql_store) as session, session.begin():
        register(session)
        ops = DshOperationRepository(session)
        generation = ops.claim("a", now=NOW, lease_seconds=30).lease_generation
        DshPolicyRepository(session).fail_uncommitted("a", generation, code="permission_revoked", now=NOW)
        register(session, op="b")
        assert DshPolicyRepository(session).get(20).pending_operation_id == "b"
        assert ops.get("a").status == "FAILED"


def test_unscoped_and_expired_lease_refuse_mutation(sql_store):
    with Session(sql_store) as session, session.begin():
        register(session)
        generation = DshOperationRepository(session).claim("a", now=NOW, lease_seconds=1).lease_generation
        with pytest.raises(DshOperationConflictError):
            DshPolicyRepository(session).commit_update("a", generation, now=NOW + timedelta(seconds=1))
        token = current_tenant_id.set(None)
        try:
            with pytest.raises(DshOperationConflictError):
                DshPolicyRepository(session).get(20)
        finally:
            current_tenant_id.reset(token)


def test_external_sql_first_configuration_race(dsh_database_url, monkeypatch):
    """Opt-in real MySQL/DM8 concurrency; missing isolated store fails explicitly."""
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from uuid import uuid4

    from sqlalchemy.exc import DBAPIError

    monkeypatch.setattr(tenant_filter, "_force_import_all_models", lambda: None)
    tenant_filter.register_tenant_filter_events()
    tenant_filter._tenant_aware_tables.update(
        {"dsh_user_policy", "dsh_admin_operation", "dsh_model_call", "dsh_monthly_usage"}
    )
    engine = create_engine(dsh_database_url, pool_pre_ping=True)
    if engine.dialect.name not in {"mysql", "dm", "dm8"}:
        raise ValueError("External race test requires MySQL or DM8")
    DshUserPolicy.__table__.create(engine, checkfirst=True)
    DshAdminOperation.__table__.create(engine, checkfirst=True)
    user_id = uuid4().int % (2**50) + 1
    barrier = Barrier(2)

    def attempt(operation_id):
        token = set_current_tenant_id(2)
        try:
            barrier.wait(timeout=10)
            for retry in range(3):
                try:
                    with Session(engine) as session, session.begin():
                        DshPolicyRepository(session).register_update(
                            operation_id=operation_id,
                            user_id=user_id,
                            actor_user_id=90,
                            expected_version=0,
                            model_id=2,
                            monthly_token_limit=100,
                            enabled=True,
                        )
                    return "REGISTERED"
                except DshOperationInProgressError:
                    return "CONFLICT"
                except DBAPIError:
                    if retry == 2:
                        raise
            raise AssertionError("unreachable")
        finally:
            current_tenant_id.reset(token)

    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(attempt, str(uuid4())) for _ in range(2)]
            assert sorted(future.result(timeout=30) for future in futures) == ["CONFLICT", "REGISTERED"]
    finally:
        # Keep isolated database evidence available for inspection; no destructive cleanup.
        engine.dispose()


def test_new_user_proof_requires_current_owner_fence_and_empty_history(sql_store):
    from bisheng.dsh.domain.models.model_call import DshModelCall
    from bisheng.dsh.domain.models.monthly_usage import DshMonthlyUsage

    DshMonthlyUsage.__table__.create(sql_store, checkfirst=True)
    DshModelCall.__table__.create(sql_store, checkfirst=True)
    with Session(sql_store) as session, session.begin():
        register(session)
        generation = DshOperationRepository(session).claim("a", now=NOW).lease_generation
        repository = DshPolicyRepository(session)
        assert repository.new_user_proof("a", generation, now=NOW)["history_empty"] is True
        with pytest.raises(DshOperationConflictError):
            repository.new_user_proof("a", generation + 1, now=NOW)
        session.add(DshMonthlyUsage(user_id=20, tenant_id=2, model_id=4, usage_month="2026-09", billing_timezone="UTC"))
        session.flush()
        assert repository.new_user_proof("a", generation, now=NOW) is None


def test_model_configuration_identity_is_preserved_in_sql_and_intent(sql_store):
    first = [
        DshModelQuotaConfig(model_id=2, monthly_token_limit=100),
        DshModelQuotaConfig(model_id=5, monthly_token_limit=200),
    ]
    with Session(sql_store) as session, session.begin():
        repository = DshPolicyRepository(session)
        repository.register_update(
            operation_id="pair",
            user_id=20,
            actor_user_id=90,
            expected_version=0,
            model_id=2,
            monthly_token_limit=100,
            enabled=True,
        )
        with pytest.raises(DshOperationConflictError):
            repository.register_update(
                operation_id="pair",
                user_id=20,
                actor_user_id=90,
                expected_version=0,
                model_id=2,
                monthly_token_limit=200,
                enabled=True,
            )
        finish(session, "pair")
    with Session(sql_store) as session:
        policy = DshPolicyRepository(session).get(20)
        assert policy.model_configs == first[:1]
        assert all(isinstance(item, DshModelQuotaConfig) for item in policy.model_configs)
        assert policy.allowed_model_ids == [2]
        assert "monthly_token_limit" not in policy.model_dump()
        assert "allowed_model_ids" not in policy.model_dump()


def test_model_configs_reject_ambiguous_or_unbounded_inputs():
    from pydantic import ValidationError

    from bisheng.dsh.domain.schemas.contracts import DshUserPolicyInput

    for models in (
        [{"model_id": 2, "monthly_token_limit": 1}, {"model_id": 2, "monthly_token_limit": 2}],
        [{"model_id": 2, "monthly_token_limit": -1}],
        [{"model_id": 2, "monthly_token_limit": True}],
        [{"model_id": 2, "monthly_token_limit": 1, "rpm": 60}],
    ):
        with pytest.raises(ValidationError):
            DshUserPolicyInput(operation_id="strict", expected_version=0, models=models)
    with pytest.raises(ValidationError):
        DshUserPolicyInput(operation_id="old", expected_version=0, models=[2], monthly_token_limit=100)

"""T113 internal slice: real impact and confirmation under one owned SP.

覆盖 AC: AC-70, AC-72, AC-73, AC-76, AC-77
Only persisted Coverage is an isolated same-session native test adapter.
"""

import asyncio
import importlib
import json
from copy import deepcopy
from dataclasses import FrozenInstanceError, asdict
from datetime import datetime, timedelta

import pytest
from sqlalchemy import select, text, update
from sqlalchemy.exc import IntegrityError
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.errcode.knowledge import (
    KnowledgeOperationPlanConflictError,
    ReferenceCoverageNotReadyError,
    ResourceReferenceInvalidError,
)
from bisheng.common.errcode.llm_tenant import LLMModelNotAccessibleError, LLMModelSharedReadonlyError
from bisheng.core.context.tenant import management_tenant_scope, tenant_execution_scope
from bisheng.core.database import tenant_filter
from bisheng.database.models.tenant import Tenant
from bisheng.knowledge.domain.models.knowledge_operation_plan import KnowledgeOperationPlan
from bisheng.llm.domain.models.llm_server import LLMModel, LLMServer
from bisheng.llm.domain.repositories.model_delete_plan_repository import ModelDeletePlanRepository, _hash
from bisheng.llm.domain.schemas import LLMModelCreateReq, LLMServerCreateReq
from bisheng.permission.application.identity import (
    PermissionActor,
    reset_current_permission_actor,
    set_current_permission_actor,
)
from bisheng.resource_reference.application.contracts import TransactionIdentity
from test.knowledge_unification import test_llm_refs as native

model_owner_tenant = native.model_owner_tenant
removal_session = native.removal_session
impact = native.impact
NOW = datetime(2026, 11, 9, 10)
SECRET = "provider-key-must-never-enter-confirmation"


def application(references, plans=None, **kwargs):
    module = importlib.import_module("bisheng.llm.application.model_delete_plan")
    return module.ModelDeletePlanApplication(references=references, plans=plans, **kwargs)


def web(user, *, home=101):
    user.tenant_id, user.token_version = home, 3
    user._runtime_credential_reference = {
        "kind": "web_session",
        "user_id": user.user_id,
        "tenant_id": home,
        "token_version": 3,
        "expires_at": "2099-11-09T11:00:00",
    }
    return user


def request(retained=(11,), *, server_id=1):
    models = [
        LLMModelCreateReq(
            id=ident,
            name=f"model-{ident}",
            model_name=f"vendor-{ident}",
            model_type="llm",
            online=False,
            config={"model_key": SECRET},
        )
        for ident in retained
    ]
    models.extend(
        LLMModelCreateReq(id=ident, name=f"new-{index}", model_name=f"new-{index}", model_type="asr_rt")
        for index, ident in enumerate((None, 0))
    )
    return LLMServerCreateReq(
        id=server_id,
        name="provider",
        description="changed provider",
        type="openai",
        limit_flag=True,
        limit=9,
        share_to_children=False,
        config={"api_key": SECRET},
        models=models,
    )


@pytest.fixture
async def ready(impact, monkeypatch):
    session, references, _ = impact
    await session.run_sync(lambda active: KnowledgeOperationPlan.__table__.create(active.connection(), checkfirst=True))
    monkeypatch.setattr(
        tenant_filter, "_tenant_aware_tables", tenant_filter._tenant_aware_tables | {"knowledge_operation_plan"}
    )
    session.add(LLMServer(id=5, tenant_id=101, name="empty", type="openai"))
    native.seed(session, slots=3)
    await session.commit()
    # Start a real caller write TX in SQLite too; no production BEGIN workaround.
    await session.execute(update(Tenant).where(Tenant.id == 101).values(tenant_name="unrelated caller write"))
    return session, references, ModelDeletePlanRepository(clock=lambda: NOW)


async def plan_count(session):
    return len((await session.execute(select(KnowledgeOperationPlan.id))).all())


async def loaded(session, plans, result, command):
    data = result.inspection
    row = (
        await session.execute(
            select(KnowledgeOperationPlan).where(KnowledgeOperationPlan.id == result.confirmation.confirmation_id)
        )
    ).scalar_one()
    actual = await plans.aget_model_delete_plan_for_execution(
        session,
        confirmation_id=row.id,
        operation=row.operation,
        actor_reference=row.actor_reference,
        command_digest=_hash(command),
        plan_digest=result.confirmation.plan_digest,
    )
    assert actual is row and row.impact["inbound_digest"] == data.inbound_digest
    assert row.target_revisions == {
        **{f"model:{target.target_id}": revision for target, revision in data.target_revisions},
        f"server:{data.server_id}": data.server_revision,
    }
    return row


async def test_original_native_core_and_plan_repository_remain_a_working_control(ready):
    session, references, plans = ready
    with native.actor() as user:
        web(user)
        inspection = await references.ainspect_removed_models(
            session, identity=user, server_id=1, retained_model_ids=(), delete_server=True
        )
        confirmation = await plans.acreate_model_delete_plan(
            session,
            operation="model_delete_server",
            actor_reference={
                "tenant_id": 101,
                "actor_user_id": 7,
                "credential_reference": deepcopy(user._runtime_credential_reference),
                "data_scope": "all_visible",
            },
            command_digest=_hash({"operation": "model_delete_server", "server_id": 1}),
            targets=inspection.targets,
            target_revisions={
                **{f"model:{t.target_id}": r for t, r in inspection.target_revisions},
                "server:1": inspection.server_revision,
            },
            inbound_digest=inspection.inbound_digest,
            coverage_epoch=inspection.coverage_epoch,
            inventory_hash=inspection.inventory_hash,
            expires_at=NOW + timedelta(seconds=300),
        )
    assert confirmation.operation == "model_delete_server" and await plan_count(session) == 1


@pytest.mark.parametrize(
    "kind,retained,expected",
    [
        ("update", (11, 12, 13, 14), {"15"}),
        ("update", (11,), {"12", "13", "14", "15"}),
        ("delete", (), {"11", "12", "13", "14", "15"}),
        ("empty", (), set()),
    ],
)
async def test_actual_core_once_then_exact_plan_insert_with_full_request_hash_and_original_revisions(
    ready, monkeypatch, kind, retained, expected
):
    session, references, plans = ready
    app = application(references, plans)
    caller = TransactionIdentity.capture(session)
    inspect, create = references.ainspect_removed_models, plans.acreate_model_delete_plan
    calls, writes = [], []

    async def checked(*args, **kwargs):
        assert session.sync_session.get_nested_transaction() is not None
        calls.append((kwargs["server_id"], tuple(kwargs["retained_model_ids"]), kwargs["delete_server"]))
        return await inspect(*args, **kwargs)

    async def created(*args, **kwargs):
        writes.append(1)
        return await create(*args, **kwargs)

    monkeypatch.setattr(references, "ainspect_removed_models", checked)
    monkeypatch.setattr(plans, "acreate_model_delete_plan", created)
    with native.actor() as user:
        web(user)
        if kind == "update":
            server = request(retained)
            command = {"operation": "model_update_server", "server": server.model_dump(mode="json")}
            result = await app.aplan_removed_update(session, identity=user, server=server)
        else:
            ident = 5 if kind == "empty" else 1
            command = {"operation": "model_delete_server", "server_id": ident}
            result = await app.aplan_server_delete(session, identity=user, server_id=ident)
    assert len(calls) == len(writes) == 1
    assert calls[0][1] == retained and calls[0][2] is (kind != "update")
    assert {target.target_id for target in result.inspection.targets} == expected
    assert result.confirmation.expires_at == NOW + timedelta(seconds=300)
    assert not hasattr(result, "__dict__") and SECRET not in repr(result)
    with pytest.raises(FrozenInstanceError):
        result.inspection = None
    caller.assert_current(session)
    row = await loaded(session, plans, result, command)
    assert row.parameters == {"command_digest": _hash(command)} and row.source_revisions == {}
    assert row.actor_reference["credential_reference"]["tenant_id"] == 101
    assert set(row.actor_reference) == {"tenant_id", "actor_user_id", "credential_reference", "data_scope"}
    assert SECRET not in json.dumps(row.model_dump(mode="json"))
    assert SECRET not in json.dumps(asdict(result), default=str)
    assert row.operation_id is None and row.consumed_at is None
    await session.rollback()
    assert await plan_count(session) == 0


async def test_mutating_caller_dto_during_actual_inspection_cannot_change_the_frozen_command(ready, monkeypatch):
    session, references, plans = ready
    app, server = application(references, plans), request()
    original = deepcopy(server.model_dump(mode="json"))
    inspect = references.ainspect_removed_models

    async def mutate(*args, **kwargs):
        server.models.clear()
        server.config["api_key"] = "replacement"
        return await inspect(*args, **kwargs)

    monkeypatch.setattr(references, "ainspect_removed_models", mutate)
    with native.actor() as user:
        result = await app.aplan_removed_update(session, identity=web(user), server=server)
    await loaded(session, plans, result, {"operation": "model_update_server", "server": original})
    assert {target.target_id for target in result.inspection.targets} == {"12", "13", "14", "15"}


@pytest.mark.parametrize("retained", [(11, 12, 13, 14, 15), (11, 11), (-1,), (44,)])
async def test_no_actual_removal_or_unowned_retained_model_cannot_create_confirmation(ready, retained):
    session, references, plans = ready
    with (
        native.actor() as user,
        pytest.raises((KnowledgeOperationPlanConflictError, ResourceReferenceInvalidError, ValueError)),
    ):
        await application(references, plans).aplan_removed_update(session, identity=web(user), server=request(retained))
    assert await plan_count(session) == 0


@pytest.mark.parametrize("server_id,error", [(2, LLMModelSharedReadonlyError), (3, LLMModelNotAccessibleError)])
async def test_actual_owner_scope_and_shared_root_remain_readonly(ready, server_id, error):
    session, references, plans = ready
    with native.actor() as user, pytest.raises(error):
        await application(references, plans).aplan_server_delete(session, identity=web(user), server_id=server_id)
    assert await plan_count(session) == 0


async def test_actual_nonadministrator_cannot_create_a_plan(ready):
    session, references, plans = ready
    with native.actor(admin=False) as user, pytest.raises(LLMModelSharedReadonlyError):
        await application(references, plans).aplan_server_delete(session, identity=web(user), server_id=1)
    assert await plan_count(session) == 0


@pytest.mark.parametrize("failure", ["missing", "not_ready", "query"])
async def test_real_coverage_absence_or_failure_is_not_an_empty_confirmation(ready, monkeypatch, failure):
    session, references, plans = ready
    if failure == "missing":
        references.coverage_factory = None
    elif failure == "not_ready":
        row = (await session.execute(select(native.KnowledgeUnificationRun))).scalar_one()
        row.source_coverage = {}
        await session.flush()
    else:

        async def broken(*_args, **_kwargs):
            raise OSError("native coverage storage unavailable")

        ledger = references.coverage_factory(session).global_port
        monkeypatch.setattr(ledger, "aget_global_status", broken)
    with native.actor() as user, pytest.raises(ReferenceCoverageNotReadyError):
        await application(references, plans).aplan_server_delete(
            session, identity=web(user), server_id=5 if failure == "missing" else 1
        )
    assert await plan_count(session) == 0


@pytest.mark.parametrize("phase", ["core", "create"])
@pytest.mark.parametrize("change", ["credential", "actor", "pin", "nested", "tenant"])
async def test_successful_callback_drift_cannot_leave_a_plan_when_outer_caller_commits(
    ready, monkeypatch, phase, change
):
    session, references, plans = ready
    app, scopes, tokens = application(references, plans), [], []
    target = references if phase == "core" else plans
    method_name = "ainspect_removed_models" if phase == "core" else "acreate_model_delete_plan"
    method = getattr(target, method_name)
    with native.actor() as user:
        web(user)

        async def drift(*args, **kwargs):
            result = await method(*args, **kwargs)
            if change == "credential":
                user._runtime_credential_reference["token_version"] += 1
            elif change == "actor":
                tokens.append(
                    set_current_permission_actor(
                        PermissionActor(
                            user_id=7,
                            tenant_id=101,
                            tenant_admin_tenant_ids=frozenset({101}),
                            data_scope="personal_only",
                        )
                    )
                )
            elif change == "nested":
                await session.begin_nested()
            else:
                scope = management_tenant_scope(101) if change == "pin" else tenant_execution_scope(202)
                scope.__enter__()
                scopes.append(scope)
            return result

        monkeypatch.setattr(target, method_name, drift)
        try:
            with pytest.raises((KnowledgeOperationPlanConflictError, ReferenceCoverageNotReadyError)):
                await app.aplan_server_delete(session, identity=user, server_id=1)
        finally:
            for scope in reversed(scopes):
                scope.__exit__(None, None, None)
            for token in reversed(tokens):
                reset_current_permission_actor(token)
    await session.commit()
    assert await plan_count(session) == 0
    assert (
        await session.execute(select(Tenant.tenant_name).where(Tenant.id == 101))
    ).scalar_one() == "unrelated caller write"


@pytest.mark.parametrize("failure", ["late", "sql"])
async def test_tail_flush_failure_rolls_back_own_savepoint_without_rolling_back_the_caller(ready, monkeypatch, failure):
    session, references, plans = ready
    app = application(references, plans)
    create = plans.acreate_model_delete_plan
    if failure == "sql":
        await session.execute(
            text(
                "CREATE TRIGGER reject_model_plan BEFORE INSERT ON knowledge_operation_plan BEGIN SELECT RAISE(ABORT, 'plan insert rejected'); END"
            )
        )
    else:

        async def failed(*args, **kwargs):
            await create(*args, **kwargs)
            raise RuntimeError("after real plan flush")

        monkeypatch.setattr(plans, "acreate_model_delete_plan", failed)
    with native.actor() as user, pytest.raises((RuntimeError, IntegrityError)):
        await app.aplan_server_delete(session, identity=web(user), server_id=1)
    await session.commit()
    assert await plan_count(session) == 0
    assert (
        await session.execute(select(Tenant.tenant_name).where(Tenant.id == 101))
    ).scalar_one() == "unrelated caller write"


async def test_actual_task_cancellation_after_real_flush_does_not_leak_a_plan(ready, monkeypatch):
    session, references, plans = ready
    app, flushed, blocked = application(references, plans), asyncio.Event(), asyncio.Event()
    create = plans.acreate_model_delete_plan

    async def stalled(*args, **kwargs):
        result = await create(*args, **kwargs)
        flushed.set()
        await blocked.wait()
        return result

    monkeypatch.setattr(plans, "acreate_model_delete_plan", stalled)
    with native.actor() as user:
        task = asyncio.create_task(app.aplan_server_delete(session, identity=web(user), server_id=1))
        await asyncio.wait_for(flushed.wait(), 10)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    await session.commit()
    assert await plan_count(session) == 0
    assert (
        await session.execute(select(Tenant.tenant_name).where(Tenant.id == 101))
    ).scalar_one() == "unrelated caller write"


async def test_requires_active_native_caller_transaction_and_does_not_flush_pending_business(ready):
    session, references, plans = ready
    app = application(references, plans)
    pending = LLMModel(id=77, tenant_id=101, server_id=1, model_name="caller pending", model_type="llm")
    session.add(pending)
    with native.actor() as user, pytest.raises((ValueError, KnowledgeOperationPlanConflictError)):
        await app.aplan_server_delete(session, identity=web(user), server_id=1)
    assert pending in session.new
    session.expunge(pending)
    async with AsyncSession(session.bind) as fresh:
        with native.actor() as user, pytest.raises((ValueError, ReferenceCoverageNotReadyError)):
            await app.aplan_server_delete(fresh, identity=web(user), server_id=1)
        assert not fresh.in_transaction()


async def test_original_home_web_identity_and_narrow_scope_survive_explicit_management_pin(ready):
    session, references, plans = ready
    app = application(references, plans)
    token = set_current_permission_actor(
        PermissionActor(user_id=7, tenant_id=1, super_admin=True, data_scope="personal_only")
    )
    try:
        with native.actor(super_admin=True) as user, management_tenant_scope(101):
            web(user, home=1)
            token2 = set_current_permission_actor(
                PermissionActor(user_id=7, tenant_id=1, super_admin=True, data_scope="personal_only")
            )
            try:
                result = await app.aplan_server_delete(session, identity=user, server_id=1)
            finally:
                reset_current_permission_actor(token2)
        row = (await session.execute(select(KnowledgeOperationPlan))).scalar_one()
        assert result.inspection.check_complete
        assert row.actor_reference["tenant_id"] == row.actor_reference["management_tenant_id"] == 101
        assert row.actor_reference["credential_reference"]["tenant_id"] == 1
        assert row.actor_reference["data_scope"] == "personal_only"
    finally:
        reset_current_permission_actor(token)

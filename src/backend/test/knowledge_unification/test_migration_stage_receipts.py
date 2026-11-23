"""Native completed-stage admission retains current facts and original identities."""

import asyncio
import json
from contextlib import suppress
from types import SimpleNamespace

import pytest
import sqlalchemy as sa
from loguru import logger

from bisheng.common.errcode.base import BaseErrorCode
from bisheng.core.context.tenant import bypass_tenant_filter, tenant_execution_scope
from bisheng.knowledge.application.unification_conversion import UnificationSQLConversionApplication
from bisheng.knowledge.application.unification_permissions import PermissionPublicationApplication
from bisheng.knowledge.application.unification_upgrade_executor import UpgradeExecutor
from bisheng.knowledge.domain.models.knowledge import Knowledge
from bisheng.knowledge.domain.models.knowledge_unification_run import KnowledgeUnificationRun
from test.knowledge_unification.test_permission_publication_application import (
    app,
)
from test.knowledge_unification.test_permission_publication_application import (
    complete as complete,
)
from test.knowledge_unification.test_permission_publication_application import (
    native as native,
)
from test.knowledge_unification.test_permission_publication_application import (
    published_input as published_input,
)
from test.knowledge_unification.test_permission_publication_application import (
    raw_resource_native as raw_resource_native,
)
from test.knowledge_unification.test_permission_publication_application import (
    resource_native as resource_native,
)
from test.knowledge_unification.test_permission_publication_application import (
    transport as transport,
)


async def test_completed_permission_admission_skips_execution_but_reads_current_graph(published_input, monkeypatch):
    value = published_input
    first = await app(value).arun_permissions(**value.input, operator_id=7, reuse_completed=True)
    writes, scans = value.store.writes, value.store.scans

    async def forbidden(*args, **kwargs):
        raise AssertionError("completed stage must not enter its business execution chain")

    monkeypatch.setattr(UnificationSQLConversionApplication, "_plan", forbidden)
    monkeypatch.setattr(PermissionPublicationApplication, "arun", forbidden)
    assert await app(value).arun_permissions(**value.input, operator_id=7, reuse_completed=True) == first
    assert value.store.writes == writes and value.store.scans == scans + 1
    value.store.tuples.add(("user:999", "member", "tenant:202"))
    with pytest.raises(BaseErrorCode):
        await app(value).arun_permissions(**value.input, operator_id=7, reuse_completed=True)
    assert value.store.writes == writes


async def test_sql_admission_without_permission_completion_skips_plan_and_rejects_business_drift(
    published_input, monkeypatch
):
    value = published_input
    first = await app(value).arun(**value.input, reuse_completed=True)

    async def forbidden(*args, **kwargs):
        raise AssertionError("completed SQL must use its durable result directory")

    monkeypatch.setattr(UnificationSQLConversionApplication, "_plan", forbidden)
    assert await app(value).arun(**value.input, reuse_completed=True) == first
    async with value.database.engine.begin() as connection:
        await connection.execute(sa.update(Knowledge).where(Knowledge.id == 9000).values(user_id=999))
    with pytest.raises(BaseErrorCode):
        await app(value).arun(**value.input, reuse_completed=True)
    assert value.store.writes == 0


@pytest.mark.parametrize("published", [False, True])
async def test_resume_preview_is_read_only_and_reconciles_real_sql_and_complete_graph(published_input, published):
    value = published_input
    if published:
        await app(value).arun_permissions(**value.input, operator_id=7, reuse_completed=True)
    async with value.database.engine.connect() as connection:
        before = tuple((await connection.execute(sa.select(KnowledgeUnificationRun.__table__))).mappings())
    writes = value.store.writes
    application = app(value)
    report = await application.apreview_resume(
        frozen=value.frozen,
        inputs={name: value.input[name] for name in ("environment", "backup_ref", "schema_ref")},
        operator_id=7,
    )
    assert report["complete"] and not report["diagnostics"]
    assert report["checks"] == {"sql_resume": "passed", "permission_resume": "passed"}
    assert value.store.writes == writes
    async with value.database.engine.connect() as connection:
        assert tuple((await connection.execute(sa.select(KnowledgeUnificationRun.__table__))).mappings()) == before
    if published:
        value.store.tuples.add(("user:999", "member", "tenant:202"))
    else:
        async with value.database.engine.begin() as connection:
            await connection.execute(sa.update(Knowledge).where(Knowledge.id == 9000).values(user_id=999))
    report = await application.apreview_resume(
        frozen=value.frozen,
        inputs={name: value.input[name] for name in ("environment", "backup_ref", "schema_ref")},
        operator_id=7,
    )
    assert not report["complete"] and report["diagnostics"]
    assert value.store.writes == writes


@pytest.mark.parametrize("after", [False, True])
@pytest.mark.parametrize("published_input", [{"roots": 205}], indirect=True)
async def test_resume_preview_verifies_native_partial_sql_and_permission_prefixes(published_input, after):
    value = published_input
    value.sessions.fail_at = value.sessions.commits + 1
    value.sessions.after = after
    with pytest.raises(BaseErrorCode):
        await app(value).arun(**value.input, reuse_completed=True)
    value.sessions.fail_at = None
    inputs = {name: value.input[name] for name in ("environment", "backup_ref", "schema_ref")}
    report = await app(value).apreview_resume(frozen=value.frozen, inputs=inputs)
    assert report["complete"], report
    assert any(row["processed"] < row["total"] for row in report["sql"])
    value.store.fail_write, value.store.after = 1, after
    with pytest.raises(BaseErrorCode):
        await app(value).arun_permissions(**value.input, operator_id=7, reuse_completed=True)
    writes = value.store.writes
    report = await app(value).apreview_resume(frozen=value.frozen, inputs=inputs)
    assert report["complete"], report
    assert value.store.writes == writes


async def test_resume_preview_marks_unreceipted_prepare_as_not_evaluated(published_input, monkeypatch):
    from bisheng.permission.application.f118_permission_publish import F118PermissionPublisher

    value = published_input

    async def fail_prepare(*args, **kwargs):
        raise RuntimeError("prepare outcome unavailable")

    monkeypatch.setattr(F118PermissionPublisher, "aprepare", fail_prepare)
    with pytest.raises(BaseErrorCode):
        await app(value).arun_permissions(**value.input, operator_id=7, reuse_completed=True)
    report = await app(value).apreview_resume(
        frozen=value.frozen, inputs={name: value.input[name] for name in ("environment", "backup_ref", "schema_ref")}
    )
    assert not report["complete"] and report["checks"]["permission_resume"] == "not_evaluated"
    assert report["diagnostics"] == [
        {
            "stage": "permission_resume",
            "classification": "not_evaluated",
            "reason": "permission_prepare_pending_unresolved",
        }
    ]


@pytest.mark.parametrize("published", [False, True])
async def test_failed_run_preview_uses_detached_effective_phase_and_cannot_enter_mutators(published_input, published):
    from bisheng.knowledge.domain.repositories.unification_run_repository import KnowledgeUnificationRunRepository

    value = published_input
    if published:
        await app(value).arun_permissions(**value.input, operator_id=7, reuse_completed=True)
    phase = "converting" if published else "baseline_frozen"
    tenant = value.frozen.tenant_ids[0]
    with tenant_execution_scope(tenant):
        async with value.sessions() as session, session.begin():
            row = await KnowledgeUnificationRunRepository().aget(
                session, **{key: value.input[key] for key in ("run_id", "writer_contract_version")}
            )
            await KnowledgeUnificationRunRepository().afail(
                session,
                run_id=row.run_id,
                writer_contract_version=row.writer_contract_version,
                baseline_hash=row.baseline_hash,
                plan_hash=row.plan_hash,
                expected_phase=row.phase,
                error_code=10998,
                error_reason="test_failed_resume",
            )
    application = UnificationSQLConversionApplication(
        artifact_store=value.artifacts.store, session_factory=value.sessions, read_only_resume=True
    )
    with tenant_execution_scope(tenant):
        async with value.sessions() as session, session.begin():
            original = await KnowledgeUnificationRunRepository().aget(
                session, run_id=value.frozen.run_id, writer_contract_version=value.frozen.writer_contract_version
            )
            effective = await application._scope_run(session, value.frozen)
            assert original.phase == "failed" and effective.phase == phase
            assert effective not in session and not session.dirty
            assert original.checkpoints["_failed_from_phase"] == phase
    inputs = {key: value.input[key] for key in ("environment", "backup_ref", "schema_ref")}
    assert (await application.apreview_resume(frozen=value.frozen, inputs=inputs))["complete"]
    for name in ("arun", "arun_permissions", "arun_references"):
        arguments = value.input | ({"operator_id": 7} if name != "arun" else {})
        with pytest.raises(BaseErrorCode) as caught:
            await getattr(application, name)(**arguments)
        assert caught.value.kwargs["reason"].endswith("readonly_resume_cannot_mutate")
    with tenant_execution_scope(tenant):
        async with value.sessions() as session, session.begin():
            assert (
                await KnowledgeUnificationRunRepository().aget(
                    session, run_id=value.frozen.run_id, writer_contract_version=value.frozen.writer_contract_version
                )
            ).phase == "failed"


@pytest.mark.parametrize("published_input", [{"roots": 205}], indirect=True)
async def test_result_tail_is_bounded_and_old_batches_remain_shared(published_input):
    value = published_input
    await app(value).arun(**value.input, reuse_completed=True)
    async with value.sessions() as session, session.begin():
        rows = (await session.execute(sa.select(KnowledgeUnificationRun))).scalars().all()
        for row in rows:
            checkpoints = row.checkpoints["converting"]
            tail = json.loads(checkpoints["sql_results_v1"]["cursor"])
            assert len(tail["commands"]) <= 200
            assert checkpoints["sql_conversion"] == tail["sql_checkpoint"]
            assert checkpoints["sql_conversion"]["cursor"] is None or checkpoints["sql_conversion"][
                "cursor"
            ].startswith("sql-v1:")
            assert checkpoints["sql_admission_v1"]["complete"]
            if tail["start"]:
                assert tail["predecessor"] is not None


async def test_guard_runs_in_same_native_transaction_before_sql_effect(published_input):
    value = published_input
    seen = []

    async def guard(session, run):
        assert session.in_transaction()
        seen.append((run.tenant_id, run.phase))
        raise RuntimeError("old executor token rejected")

    application = UnificationSQLConversionApplication(
        artifact_store=value.artifacts.store, session_factory=value.sessions, transaction_guard=guard
    )
    with pytest.raises(BaseErrorCode):
        await application.arun(**value.input, reuse_completed=True)
    assert seen and value.store.writes == 0


@pytest.mark.parametrize("after,cancel", [(False, False), (True, False), (True, True)])
@pytest.mark.parametrize("published_input", [{"roots": 205}], indirect=True)
async def test_sql_tail_and_effect_share_unknown_commit_boundary(published_input, after, cancel):
    value = published_input
    value.sessions.fail_at = value.sessions.commits + 1
    value.sessions.after, value.sessions.cancel = after, cancel
    with pytest.raises(asyncio.CancelledError if cancel else BaseErrorCode):
        await app(value).arun(**value.input, reuse_completed=True)
    value.sessions.fail_at = None
    assert (await app(value).arun(**value.input, reuse_completed=True)).sql_complete
    assert (await app(value).arun(**value.input, reuse_completed=True)).sql_complete
    assert value.store.writes == 0


async def test_legacy_complete_sql_and_permissions_are_verified_once_then_bound(published_input, monkeypatch):
    value = published_input
    original = await app(value).arun_permissions(**value.input, operator_id=7)
    writes = value.store.writes
    assert await app(value).arun_permissions(**value.input, operator_id=7, reuse_completed=True) == original

    async def forbidden(*args, **kwargs):
        raise AssertionError("legacy completion already has a verified admission")

    monkeypatch.setattr(UnificationSQLConversionApplication, "_plan", forbidden)
    monkeypatch.setattr(PermissionPublicationApplication, "arun", forbidden)
    assert await app(value).arun_permissions(**value.input, operator_id=7, reuse_completed=True) == original
    assert value.store.writes == writes


async def test_real_executor_guards_bind_native_sql_and_external_publication(published_input):
    value = published_input

    class Lease:
        async def ensure(self):
            return None

    executor = UpgradeExecutor(
        SimpleNamespace(sessions=value.sessions, engine=value.database.engine),
        run_id=value.frozen.run_id,
        writer_contract_version=value.frozen.writer_contract_version,
        lease=Lease(),
    )
    await executor.start(value.frozen.tenant_ids)
    try:
        application = UnificationSQLConversionApplication(
            artifact_store=value.artifacts.store,
            session_factory=value.sessions,
            transaction_guard=executor.transaction_guard,
            external_guard=executor,
        )
        assert (await application.arun_permissions(**value.input, operator_id=7, reuse_completed=True)).complete
        await executor.finish_attempt()
    finally:
        if executor._watcher is not None:
            executor._watcher.cancel()
            with suppress(asyncio.CancelledError):
                await executor._watcher


async def test_unidentified_writer_cannot_bypass_active_attempt_but_readonly_inspection_can(published_input):
    value = published_input

    class Lease:
        async def ensure(self):
            return None

    executor = UpgradeExecutor(
        SimpleNamespace(sessions=value.sessions, engine=value.database.engine),
        run_id=value.frozen.run_id,
        writer_contract_version=value.frozen.writer_contract_version,
        lease=Lease(),
    )
    await executor.start(value.frozen.tenant_ids)
    try:
        with pytest.raises(BaseErrorCode) as caught:
            await app(value).arun_permissions(**value.input, operator_id=7)
        assert caught.value.kwargs["reason"].endswith("executor_identity_required")
        assert value.store.writes == 0
        readonly = UnificationSQLConversionApplication(
            artifact_store=value.artifacts.store, session_factory=value.sessions, read_only_resume=True
        )
        assert (
            await readonly.apreview_resume(
                frozen=value.frozen,
                inputs={key: value.input[key] for key in ("environment", "backup_ref", "schema_ref")},
            )
        )["complete"]
        guarded = UnificationSQLConversionApplication(
            artifact_store=value.artifacts.store,
            session_factory=value.sessions,
            transaction_guard=executor.transaction_guard,
            external_guard=executor,
        )
        assert (await guarded.arun_permissions(**value.input, operator_id=7, reuse_completed=True)).complete
        await executor.finish_attempt()
        writes = value.store.writes
        assert (await app(value).arun_permissions(**value.input, operator_id=7)).complete
        assert value.store.writes == writes
    finally:
        executor._watcher.cancel()
        with suppress(asyncio.CancelledError):
            await executor._watcher


async def test_readonly_preview_external_failure_never_logs_provider_text_or_sql_binds(published_input, monkeypatch):
    from bisheng.permission.application.f118_permission_publish import F118PermissionPublisher

    value, messages, calls = published_input, [], []
    secret = "secret-provider-credential SELECT business_payload='private-bind'"

    async def external_scan_failure(_publisher):
        calls.append(True)
        raise RuntimeError(secret)

    monkeypatch.setattr(F118PermissionPublisher, "ascan", external_scan_failure)
    sink = logger.add(messages.append, level="WARNING", format="{message}\n{exception}", backtrace=True, diagnose=True)
    try:
        application = UnificationSQLConversionApplication(
            artifact_store=value.artifacts.store, session_factory=value.sessions, read_only_resume=True
        )
        report = await application.apreview_resume(
            frozen=value.frozen, inputs={key: value.input[key] for key in ("environment", "backup_ref", "schema_ref")}
        )
    finally:
        logger.remove(sink)
    assert calls and report["checks"] == {"sql_resume": "passed", "permission_resume": "blocked"}
    assert not report["complete"] and report["diagnostics"]
    assert messages and "RuntimeError" in "".join(messages)
    output = json.dumps(report) + "".join(messages)
    assert "secret-provider-credential" not in output and "private-bind" not in output
    assert value.store.writes == 0


async def test_guard_carries_all_tenants_through_native_reference_certificate(published_input):
    value = published_input

    class Lease:
        async def ensure(self):
            return None

    executor = UpgradeExecutor(
        SimpleNamespace(sessions=value.sessions, engine=value.database.engine),
        run_id=value.frozen.run_id,
        writer_contract_version=value.frozen.writer_contract_version,
        lease=Lease(),
    )
    await executor.start(value.frozen.tenant_ids)
    try:
        application = UnificationSQLConversionApplication(
            artifact_store=value.artifacts.store,
            session_factory=value.sessions,
            transaction_guard=executor.transaction_guard,
            external_guard=executor,
        )
        assert (await application.arun_references(**value.input, operator_id=7, reuse_completed=True)).complete
        await executor.finish_attempt()
        async with value.sessions() as session, session.begin():
            with bypass_tenant_filter():
                rows = (await session.execute(sa.select(KnowledgeUnificationRun))).scalars().all()
            assert {row.tenant_id for row in rows} == set(value.frozen.tenant_ids)
            for row in rows:
                assert row.phase == "completed"
                latest = executor.repository._latest(row)
                assert latest[2]["closed"] and latest[2]["pending"] is None
    finally:
        if executor._watcher is not None:
            executor._watcher.cancel()
            with suppress(asyncio.CancelledError):
                await executor._watcher


async def test_unknown_native_request_is_not_adopted_by_a_new_executor(published_input):
    value = published_input

    class Lease:
        async def ensure(self):
            return None

    runtime = SimpleNamespace(sessions=value.sessions, engine=value.database.engine)
    executor = UpgradeExecutor(
        runtime, run_id=value.frozen.run_id, writer_contract_version=value.frozen.writer_contract_version, lease=Lease()
    )
    await executor.start(value.frozen.tenant_ids)
    value.store.fail_write, value.store.after = 1, True
    try:
        application = UnificationSQLConversionApplication(
            artifact_store=value.artifacts.store,
            session_factory=value.sessions,
            transaction_guard=executor.transaction_guard,
            external_guard=executor,
        )
        with pytest.raises(BaseErrorCode):
            await application.arun_permissions(**value.input, operator_id=7, reuse_completed=True)
        with pytest.raises(BaseErrorCode):
            await executor.finish_attempt()
        replacement = UpgradeExecutor(
            runtime,
            run_id=value.frozen.run_id,
            writer_contract_version=value.frozen.writer_contract_version,
            lease=Lease(),
        )
        with pytest.raises(BaseErrorCode):
            await replacement.start(value.frozen.tenant_ids)
    finally:
        if executor._watcher is not None:
            executor._watcher.cancel()
            with suppress(asyncio.CancelledError):
                await executor._watcher

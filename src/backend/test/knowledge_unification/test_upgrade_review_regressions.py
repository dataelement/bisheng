"""Native regressions for upgrade admission and executor review findings.

Only control-lock transport is replaced for SQLite; stage effects, receipts,
source checks and Run transitions are the native owners.
"""

import asyncio
from contextlib import asynccontextmanager, suppress
from types import SimpleNamespace

import pytest
import sqlalchemy as sa

from bisheng.common.errcode.base import BaseErrorCode
from bisheng.common.errcode.knowledge import KnowledgeOperationPlanConflictError
from bisheng.core.context.tenant import bypass_tenant_filter, tenant_execution_scope
from bisheng.database.models.assistant import Assistant
from bisheng.knowledge.application.unification_conversion import UnificationSQLConversionApplication
from bisheng.knowledge.application.unification_upgrade import UnificationUpgradeApplication
from bisheng.knowledge.application.unification_upgrade_executor import UpgradeExecutor
from bisheng.knowledge.application.unification_upgrade_materials import UpgradeMaterials
from bisheng.knowledge.domain.models.knowledge_unification_executor_lock import KnowledgeUnificationExecutorLock as Lock
from bisheng.knowledge.domain.models.knowledge_unification_run import KnowledgeUnificationRun as Run
from bisheng.knowledge.domain.repositories.unification_executor_repository import UnificationExecutorRepository
from bisheng.knowledge.domain.repositories.unification_run_repository import KnowledgeUnificationRunRepository
from bisheng.knowledge.domain.repositories.unification_upgrade_repository import UpgradeRunRepository
from test.knowledge_unification import test_migration_cli as original
from test.knowledge_unification import test_upgrade_new_run as fresh

complete, native = original.complete, original.native
raw_resource_native, resource_native = original.raw_resource_native, original.resource_native
transport, published_input, no_real_network = original.transport, original.published_input, original.no_real_network


class Lease:
    async def ensure(self):
        return None


async def stop(executor):
    if executor._watcher is not None:
        executor._watcher.cancel()
        with suppress(asyncio.CancelledError):
            await executor._watcher


@pytest.mark.parametrize("published_input", [{"reference_seed": original.seed_cli_operator}], indirect=True)
@pytest.mark.parametrize("damage", ["missing", "corrupt"])
async def test_first_bootstrap_rejects_unusable_material_without_lock_seed(
    published_input, tmp_path, monkeypatch, damage
):
    value, acquired = published_input, []
    async with value.database.engine.begin() as connection:
        await connection.run_sync(lambda conn: Lock.__table__.create(conn, checkfirst=True))
    if damage == "corrupt":
        preview = await original.entry().arun(
            original.arguments(value, materials_dir=tmp_path), runtime_factory=original.runtime(value)
        )
        (tmp_path / "objects" / (preview["flow_ref"]["sha256"] + ".json")).write_bytes(b"{}")

    @asynccontextmanager
    async def observed_acquire(_repository, engine):
        acquired.append(True)
        async with engine.begin() as connection:
            await connection.execute(sa.insert(Lock.__table__).values(id="f118-global", tenant_id=1))
        yield Lease()

    @asynccontextmanager
    async def runtime(_arguments):
        yield SimpleNamespace(
            store=value.artifacts.store, sessions=value.sessions, engine=value.database.engine, inventory=None
        )

    monkeypatch.setattr(UnificationExecutorRepository, "acquire", observed_acquire)
    with pytest.raises(BaseErrorCode):
        await original.entry().arun(
            original.arguments(value, "--apply", "--operator-id", "7", materials_dir=tmp_path), runtime_factory=runtime
        )
    assert not acquired
    async with value.database.engine.connect() as connection:
        assert not (await connection.execute(sa.select(Lock.id))).all()


@pytest.mark.parametrize("published_input", [{"reference_seed": original.seed_cli_operator}], indirect=True)
async def test_failed_frozen_cli_preview_is_readonly_and_apply_resumes_original_run(published_input, tmp_path):
    value = published_input
    await original.entry().arun(
        original.arguments(value, materials_dir=tmp_path), runtime_factory=original.runtime(value)
    )
    with tenant_execution_scope(value.frozen.tenant_ids[0]):
        async with value.sessions() as session, session.begin():
            await KnowledgeUnificationRunRepository().afail(
                session,
                run_id=value.frozen.run_id,
                writer_contract_version=value.frozen.writer_contract_version,
                baseline_hash=value.frozen.baseline_ref["sha256"],
                plan_hash=value.frozen.plan_ref["sha256"],
                expected_phase="baseline_frozen",
                error_code=10998,
                error_reason="review_regression",
            )
    preview = await original.entry().arun(
        original.arguments(value, materials_dir=tmp_path), runtime_factory=original.runtime(value)
    )
    assert preview["can_apply"]
    with tenant_execution_scope(value.frozen.tenant_ids[0]):
        async with value.sessions() as session, session.begin():
            assert (
                await KnowledgeUnificationRunRepository().aget(
                    session, run_id=value.frozen.run_id, writer_contract_version=value.frozen.writer_contract_version
                )
            ).phase == "failed"
    result = await original.entry().arun(
        original.arguments(value, "--apply", "--operator-id", "7", materials_dir=tmp_path),
        runtime_factory=original.runtime(value),
    )
    assert result["ready"] and result["complete"]


@pytest.mark.parametrize("published_input", [{"reference_seed": original.seed_cli_operator}], indirect=True)
async def test_unknown_external_attempt_is_not_green_in_dry_run(published_input, tmp_path):
    value = published_input
    executor = UpgradeExecutor(
        SimpleNamespace(sessions=value.sessions, engine=value.database.engine),
        run_id=value.frozen.run_id,
        writer_contract_version=value.frozen.writer_contract_version,
        lease=Lease(),
    )
    await executor.start(value.frozen.tenant_ids)
    try:
        ticket = await executor.begin(kind="permission_prepare", identity={"tenant_id": 1, "request_sha256": "a" * 64})
        await executor.finish(ticket, outcome="unknown")
        report = await original.entry().arun(
            original.arguments(value, materials_dir=tmp_path), runtime_factory=original.runtime(value)
        )
        assert not report["can_apply"]
        assert report["diagnostics"] == [
            {"reason": "migration_executor_recovery_required", "classification": "blocked"}
        ]
        assert value.store.writes == 0
    finally:
        await stop(executor)


@pytest.mark.parametrize("published_input", [{"freeze": False, "reference_seed": fresh.seed_actor}], indirect=True)
async def test_bound_original_source_drift_rejects_before_sql_or_fga_effects(published_input, tmp_path, monkeypatch):
    value = published_input
    await value.database.insert(
        Assistant, [{"id": "review-assistant", "tenant_id": 101, "user_id": 7, "model_name": "11", "status": 0}]
    )
    assert (
        await original.entry().arun(fresh.args(value, tmp_path, "--dry-run"), runtime_factory=fresh.runtime(value))
    )["can_apply"]
    method = UnificationSQLConversionApplication.arun_references

    async def interrupt(*args, **kwargs):
        raise RuntimeError("review stopped after native freeze")

    monkeypatch.setattr(UnificationSQLConversionApplication, "arun_references", interrupt)
    with pytest.raises(RuntimeError, match="native freeze"):
        await original.entry().arun(
            fresh.args(value, tmp_path, "--apply", "--operator-id", "7"), runtime_factory=fresh.runtime(value)
        )
    monkeypatch.setattr(UnificationSQLConversionApplication, "arun_references", method)
    async with value.database.engine.begin() as connection:
        await connection.execute(
            sa.update(Assistant.__table__).where(Assistant.id == "review-assistant").values(model_name="999")
        )
    writes, fga_before = [], value.store.writes

    def capture(_conn, _cursor, statement, _params, _context, _many):
        if statement.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")):
            writes.append(statement)

    sa.event.listen(value.database.engine.sync_engine, "before_cursor_execute", capture)
    try:
        with pytest.raises(BaseErrorCode):
            await original.entry().arun(
                fresh.args(value, tmp_path, "--apply", "--operator-id", "7"), runtime_factory=fresh.runtime(value)
            )
    finally:
        sa.event.remove(value.database.engine.sync_engine, "before_cursor_execute", capture)
    assert not writes and value.store.writes == fga_before


@pytest.mark.parametrize("published_input", [{"freeze": False, "reference_seed": fresh.seed_actor}], indirect=True)
async def test_stale_executor_cannot_bind_preparing_after_a_new_generation(published_input):
    value = published_input
    runtime = SimpleNamespace(sessions=value.sessions, engine=value.database.engine)
    identity = {key: value.input[key] for key in ("run_id", "writer_contract_version")}
    old, new = (UpgradeExecutor(runtime, **identity, lease=Lease()) for _ in range(2))
    await old.start((1, 101, 202))
    await new.start((1, 101, 202))
    try:
        with tenant_execution_scope(1):
            async with value.sessions() as session, session.begin():
                state = await UpgradeRunRepository().aload_state(session, **identity)
        owner = UnificationUpgradeApplication(runtime, None)
        with pytest.raises(BaseErrorCode) as caught:
            await owner._history_and_freeze(
                SimpleNamespace(**identity, operator_id=7),
                old,
                state,
                {"object_key": "unread", "sha256": "a" * 64},
                {},
                "test",
            )
        assert caught.value.kwargs["reason"] == "migration_executor_attempt_changed"
        async with value.sessions() as session, session.begin():
            with bypass_tenant_filter():
                rows = (await session.execute(sa.select(Run))).scalars().all()
            assert all("flow_identity_v1" not in row.checkpoints.get("preparing", {}) for row in rows)
    finally:
        await stop(old)
        await stop(new)


@pytest.mark.parametrize(
    "error",
    [
        RuntimeError("secret-provider-credential"),
        KnowledgeOperationPlanConflictError(reason="bounded_reason", msg="secret-provider-credential"),
        asyncio.CancelledError("secret-provider-credential"),
    ],
)
def test_cli_failure_or_cancel_report_omits_provider_text(monkeypatch, capsys, error):
    module = original.entry()

    async def failed(_arguments):
        raise error

    monkeypatch.setattr(module, "arun", failed)
    assert module.main(["--run-id", "review-redaction", "--dry-run"]) != 0
    captured = capsys.readouterr()
    assert "secret-provider-credential" not in captured.out + captured.err


@pytest.mark.parametrize("published_input", [{"reference_seed": original.seed_cli_operator}], indirect=True)
async def test_report_disk_failure_does_not_publish_candidate_or_enable_a_later_apply(
    published_input, tmp_path, monkeypatch
):
    value, statements = published_input, []

    def capture(_conn, _cursor, statement, _params, _context, _many):
        if statement.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")):
            statements.append(statement)

    write_report = UpgradeMaterials.write_report

    def disk_full(_materials, _report):
        raise OSError(28, "simulated report device full")

    sa.event.listen(value.database.engine.sync_engine, "before_cursor_execute", capture)
    try:
        monkeypatch.setattr(UpgradeMaterials, "write_report", disk_full)
        with pytest.raises(OSError):
            await original.entry().arun(
                original.arguments(value, "--dry-run", materials_dir=tmp_path), runtime_factory=original.runtime(value)
            )
        materials = UpgradeMaterials(tmp_path, run_id=value.frozen.run_id)
        assert materials.active(required=False) is None
        assert not list(materials.reconciliation_candidates())
        monkeypatch.setattr(UpgradeMaterials, "write_report", write_report)
        with pytest.raises(BaseErrorCode) as caught:
            await original.entry().arun(
                original.arguments(value, "--apply", "--operator-id", "7", materials_dir=tmp_path),
                runtime_factory=original.runtime(value),
            )
        assert caught.value.kwargs["reason"] == "migration_upgrade_dry_run_required"
    finally:
        sa.event.remove(value.database.engine.sync_engine, "before_cursor_execute", capture)
    assert not statements and value.store.writes == 0


@pytest.mark.parametrize(
    "published_input",
    [
        {"freeze": False, "reference_seed": fresh.seed_actor},
        {"reference_seed": original.seed_cli_operator},
    ],
    indirect=True,
)
@pytest.mark.parametrize("apply", [False, True])
async def test_verify_requires_completed_run_before_any_effect(published_input, tmp_path, apply):
    value, statements = published_input, []
    runtime = fresh.runtime(value) if value.options.get("freeze") is False else original.runtime(value)
    arguments = (
        fresh.args
        if value.options.get("freeze") is False
        else (lambda value, directory, *extra: original.arguments(value, *extra, materials_dir=directory))
    )
    assert (await original.entry().arun(arguments(value, tmp_path, "--dry-run"), runtime_factory=runtime))["can_apply"]
    objects, fga_writes = dict(value.artifacts.objects), value.store.writes

    def capture(_conn, _cursor, statement, _params, _context, _many):
        if statement.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")):
            statements.append(statement)

    sa.event.listen(value.database.engine.sync_engine, "before_cursor_execute", capture)
    try:
        with pytest.raises(BaseErrorCode) as caught:
            await original.entry().arun(
                arguments(value, tmp_path, "--apply" if apply else "--dry-run", "--verify", "--operator-id", "7"),
                runtime_factory=runtime,
            )
        assert caught.value.kwargs["reason"].endswith("verify_requires_completed")
    finally:
        sa.event.remove(value.database.engine.sync_engine, "before_cursor_execute", capture)
    assert not statements and value.store.writes == fga_writes and value.artifacts.objects == objects


@pytest.mark.parametrize("published_input", [{"reference_seed": original.seed_cli_operator}], indirect=True)
async def test_verify_completed_run_preserves_certificate_and_business_state(published_input, tmp_path):
    value, statements = published_input, []
    await original.entry().arun(
        original.arguments(value, "--dry-run", materials_dir=tmp_path), runtime_factory=original.runtime(value)
    )
    result = await original.entry().arun(
        original.arguments(value, "--apply", "--operator-id", "7", materials_dir=tmp_path),
        runtime_factory=original.runtime(value),
    )
    assert result["ready"]
    objects, fga_writes = dict(value.artifacts.objects), value.store.writes

    def capture(_conn, _cursor, statement, _params, _context, _many):
        if statement.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")):
            statements.append(statement)

    sa.event.listen(value.database.engine.sync_engine, "before_cursor_execute", capture)
    try:
        verified = await original.entry().arun(
            original.arguments(value, "--apply", "--verify", "--operator-id", "7", materials_dir=tmp_path),
            runtime_factory=original.runtime(value),
        )
    finally:
        sa.event.remove(value.database.engine.sync_engine, "before_cursor_execute", capture)
    assert verified["ready"] and verified["coverage_epoch"] == result["coverage_epoch"]
    assert not statements and value.store.writes == fga_writes and value.artifacts.objects == objects


@pytest.mark.parametrize("published_input", [{"reference_seed": original.seed_cli_operator}], indirect=True)
@pytest.mark.parametrize("forbid_control", [False, True])
async def test_legacy_completed_first_unified_verify_is_readonly_including_remote_store(
    published_input, tmp_path, monkeypatch, forbid_control
):
    from test.knowledge_unification.test_permission_publication_application import app

    value, statements, remote_puts, acquired = published_input, [], [], []
    legacy = await app(value).arun_references(**value.input, operator_id=7)
    assert legacy.complete
    with tenant_execution_scope(1):
        async with value.sessions() as session, session.begin():
            state = await UpgradeRunRepository().aload_state(
                session, run_id=value.frozen.run_id, writer_contract_version=value.frozen.writer_contract_version
            )
    assert state.completed and state.binding is None and not state.reconciliation_refs
    objects, fga_writes = dict(value.artifacts.objects), value.store.writes
    native_put = value.artifacts.store.storage.put_object

    async def observed_put(**kwargs):
        remote_puts.append(kwargs["object_name"])
        return await native_put(**kwargs)

    @asynccontextmanager
    async def control():
        acquired.append(True)
        if forbid_control:
            raise AssertionError("completed strict verification entered write control")
        yield Lease()

    @asynccontextmanager
    async def runtime(_arguments):
        yield SimpleNamespace(
            store=value.artifacts.store,
            sessions=value.sessions,
            engine=value.database.engine,
            executor_lock=control,
            inventory=None,
        )

    def capture(_conn, _cursor, statement, _params, _context, _many):
        if statement.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")):
            statements.append(statement)

    monkeypatch.setattr(value.artifacts.store.storage, "put_object", observed_put)
    sa.event.listen(value.database.engine.sync_engine, "before_cursor_execute", capture)
    try:
        preview = await original.entry().arun(
            original.arguments(value, "--dry-run", materials_dir=tmp_path), runtime_factory=runtime
        )
        assert preview["can_apply"] and not remote_puts and not acquired
        result = await original.entry().arun(
            original.arguments(value, "--verify", "--apply", "--operator-id", "7", materials_dir=tmp_path),
            runtime_factory=runtime,
        )
    finally:
        sa.event.remove(value.database.engine.sync_engine, "before_cursor_execute", capture)
    assert result["ready"] and result["coverage_epoch"] == legacy.coverage_epoch
    assert not statements and value.store.writes == fga_writes
    assert not remote_puts, remote_puts
    assert not acquired and value.artifacts.objects == objects

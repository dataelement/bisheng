"""Operational entry uses actual frozen artifacts and original M3→M4 execution."""

import importlib
import json
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest
import sqlalchemy as sa

from bisheng.knowledge.domain.models.knowledge_unification_run import KnowledgeUnificationRun as Run
from test.knowledge_unification.test_migration_cli_runtime import (
    native_runtime as native_runtime,
)
from test.knowledge_unification.test_migration_references_application import (
    complete as complete,
)
from test.knowledge_unification.test_migration_references_application import (
    native as native,
)
from test.knowledge_unification.test_migration_references_application import (
    no_real_network as no_real_network,
)
from test.knowledge_unification.test_migration_references_application import (
    published_input as published_input,
)
from test.knowledge_unification.test_migration_references_application import (
    raw_resource_native as raw_resource_native,
)
from test.knowledge_unification.test_migration_references_application import (
    resource_native as resource_native,
)
from test.knowledge_unification.test_migration_references_application import (
    transport as transport,
)


def entry():
    return importlib.import_module("scripts.unify_knowledge_spaces")


def arguments(value, *extra, legacy=False, materials_dir=None):
    return (
        entry()
        .parser()
        .parse_args(
            [
                "--run-id",
                value.input["run_id"],
                "--environment",
                value.input["environment"],
                *(["--materials-dir", str(materials_dir)] if materials_dir is not None else []),
                *(
                    [
                        "--backup-ref",
                        json.dumps(value.input["backup_ref"]),
                        "--schema-ref",
                        json.dumps(value.input["schema_ref"]),
                    ]
                    if legacy
                    else []
                ),
                *extra,
            ]
        )
    )


def runtime(value):
    class Lease:
        async def ensure(self):
            return None

    @asynccontextmanager
    async def executor_lock():
        yield Lease()

    @asynccontextmanager
    async def open_runtime(*args, **kwargs):
        yield SimpleNamespace(
            store=value.artifacts.store,
            sessions=value.sessions,
            inventory=None,
            engine=value.database.engine,
            executor_lock=executor_lock,
        )

    return open_runtime


async def seed_cli_operator(database):
    # Reuse the native new-Run test's SQLite identity adaptation and actual
    # active actor seed before the frozen fixture baseline is captured.
    from test.knowledge_unification.test_upgrade_new_run import seed_actor

    await seed_actor(database)


async def test_default_preview_is_read_only_and_reports_actual_frozen_scope(published_input, tmp_path):
    value, writes = published_input, []

    def observe(connection, cursor, statement, parameters, context, many):
        if statement.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")):
            writes.append(statement)

    sa.event.listen(value.database.engine.sync_engine, "before_cursor_execute", observe)
    try:
        result = await entry().arun(arguments(value, materials_dir=tmp_path), runtime_factory=runtime(value))
    finally:
        sa.event.remove(value.database.engine.sync_engine, "before_cursor_execute", observe)
    assert result["mode"] == "dry-run" and result["tenant_ids"] == list(value.frozen.tenant_ids)
    assert result["ready"] is False and not writes and value.store.writes == 0
    assert result["validation_scope"] == "frozen_resume" and result["preflight_complete"] and result["can_apply"]
    value.sessions.assert_closed()


@pytest.mark.parametrize("published_input", [{"reference_seed": seed_cli_operator}], indirect=True)
async def test_apply_and_same_run_resume_reach_real_certificate(published_input, tmp_path):
    value = published_input
    await entry().arun(arguments(value, materials_dir=tmp_path), runtime_factory=runtime(value))
    args = arguments(value, "--apply", "--operator-id", "7", materials_dir=tmp_path)
    result = await entry().arun(args, runtime_factory=runtime(value))
    assert result["ready"] is True and result["coverage_epoch"] > 0
    assert result["invalid_manifest_ref"] == value.frozen.plan_ref
    args.resume = True
    resumed = await entry().arun(args, runtime_factory=runtime(value))
    stable = (
        "run_id",
        "writer_contract_version",
        "baseline_hash",
        "plan_hash",
        "tenant_ids",
        "coverage_epoch",
        "source_proofs",
        "stages",
        "complete",
        "ready",
    )
    assert {key: resumed[key] for key in stable} == {key: result[key] for key in stable}
    assert resumed["counts_scope"] == "history_actions_in_this_command" and resumed["auto_repair"] == 0
    assert resumed["retained_warning"] == 0 and resumed["report_path"]
    async with value.sessions() as session, session.begin():
        assert (
            await session.execute(sa.select(Run.phase).where(Run.run_id == value.frozen.run_id))
        ).scalar_one() == "completed"


@pytest.mark.parametrize("published_input", [{"reference_seed": seed_cli_operator}], indirect=True)
async def test_explicit_permission_stage_does_not_certify_references(published_input, tmp_path):
    from bisheng.common.errcode.knowledge import ReferenceCoverageNotReadyError
    from bisheng.knowledge.application.unification_coverage import production_coverage_factory

    value = published_input
    args = arguments(value, "--apply", "--operator-id", "7", "--permissions-only", materials_dir=tmp_path)
    result = await entry().arun(args, runtime_factory=runtime(value))
    assert result["mode"] == "apply_permissions" and result["permissions_complete"] is True
    assert result["ready"] is False and result["reference_backfill_executed"] is False
    async with value.sessions() as session, session.begin():
        row = (await session.execute(sa.select(Run).where(Run.run_id == value.frozen.run_id))).scalar_one()
        assert row.phase == "converting" and row.coverage_epoch is None and row.source_coverage == {}
        with pytest.raises(ReferenceCoverageNotReadyError):
            await production_coverage_factory(session).arequire_global_ready()
    args.resume = True
    assert await entry().arun(args, runtime_factory=runtime(value)) == result
    args.permissions_only = False
    await entry().arun(arguments(value, materials_dir=tmp_path), runtime_factory=runtime(value))
    assert (await entry().arun(args, runtime_factory=runtime(value)))["ready"] is True


async def test_permission_stage_requires_explicit_apply(published_input, tmp_path):
    from bisheng.common.errcode.knowledge import KnowledgeOperationPlanConflictError

    with pytest.raises(KnowledgeOperationPlanConflictError) as caught:
        await entry().arun(
            arguments(published_input, "--permissions-only", materials_dir=tmp_path),
            runtime_factory=runtime(published_input),
        )
    assert caught.value.kwargs["reason"] == "migration_cli_permissions_only_requires_apply"


def test_cli_requires_explicit_apply_and_valid_operator():
    module = entry()
    args = module.parser().parse_args(
        [
            "--run-id",
            "native",
            "--environment",
            "test",
            "--backup-ref",
            json.dumps({"object_key": "native/material", "sha256": "a" * 64}),
            "--schema-ref",
            json.dumps({"object_key": "native/material", "sha256": "a" * 64}),
        ]
    )
    assert not args.apply and not args.resume
    with pytest.raises(SystemExit):
        module.parser().parse_args(
            [
                "--run-id",
                "native",
                "--environment",
                "test",
                "--backup-ref",
                json.dumps({"object_key": "native/material", "sha256": "a" * 64}),
                "--schema-ref",
                json.dumps({"object_key": "native/material", "sha256": "a" * 64}),
                "--apply",
                "--operator-id",
                "-1",
            ]
        )


@pytest.mark.parametrize("published_input", [{"reference_seed": seed_cli_operator}], indirect=True)
async def test_apply_without_run_calls_actual_native_m2_before_original_chain(published_input, tmp_path):
    value = published_input
    # Start from the actual pre-conversion SQL state, with no frozen Run.
    # Immutable fixture objects remain harmless content-addressed evidence.
    async with value.sessions() as session, session.begin():
        await session.execute(sa.delete(Run.__table__))
    value.store.enforce_closed = False  # M2's original read TX intentionally spans its read-only evidence IO.

    native_runtime = current_inventory_runtime(value)
    preview = await entry().arun(arguments(value, materials_dir=tmp_path), runtime_factory=native_runtime)
    assert preview["can_apply"]
    result = await entry().arun(
        arguments(value, "--apply", "--operator-id", "7", materials_dir=tmp_path), runtime_factory=native_runtime
    )
    assert result["ready"] is True and result["complete"] is True


def current_inventory_runtime(value):
    from test.knowledge_unification.test_upgrade_new_run import runtime as native_history_runtime

    return native_history_runtime(value)


@pytest.mark.parametrize("published_input", [{"reference_seed": seed_cli_operator}], indirect=True)
async def test_new_run_preview_performs_complete_inventory_without_persisting(published_input, tmp_path):
    value, writes = published_input, []
    async with value.sessions() as session, session.begin():
        await session.execute(sa.delete(Run.__table__))
    value.store.enforce_closed = False  # M2 preflight owns the original read-only inventory transaction.
    objects_before, tuples_before = dict(value.artifacts.objects), set(value.store.tuples)

    def observe(connection, cursor, statement, parameters, context, many):
        if statement.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")):
            writes.append(statement)

    sa.event.listen(value.database.engine.sync_engine, "before_cursor_execute", observe)
    try:
        result = await entry().arun(
            arguments(value, materials_dir=tmp_path), runtime_factory=current_inventory_runtime(value)
        )
    finally:
        sa.event.remove(value.database.engine.sync_engine, "before_cursor_execute", observe)
    assert result["validation_scope"] == "repaired_inventory" and result["preflight_complete"] and result["can_apply"]
    assert result["tenant_ids"] == [1, 101, 202]
    assert result["frozen"] is False and result["ready"] is False
    from bisheng.knowledge.application.unification_upgrade_materials import UpgradeMaterials

    flow = UpgradeMaterials(tmp_path, run_id=value.input["run_id"]).read_object(
        result["flow_ref"], kind="upgrade_flow"
    )["records"][0]
    assert flow["baseline_ref"] and flow["plan_ref"]
    assert not writes and value.artifacts.objects == objects_before
    assert value.store.tuples == tuples_before and value.store.writes == 0
    assert value.store.requests  # The real pinned permission reader participated in the complete inventory.
    async with value.sessions() as session, session.begin():
        assert (await session.execute(sa.select(sa.func.count()).select_from(Run.__table__))).scalar_one() == 0
    value.sessions.assert_closed()


@pytest.mark.parametrize("published_input", [{"reference_seed": seed_cli_operator}], indirect=True)
async def test_new_run_preview_reports_actual_data_blocker_instead_of_only_listing_tenants(published_input, tmp_path):
    from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile

    value = published_input
    async with value.sessions() as session, session.begin():
        await session.execute(sa.delete(Run.__table__))
        await session.execute(
            # An unknown parent folder is automatically removed; a cyclic
            # ancestry is ambiguous and must remain a concrete dry-run block.
            sa.update(KnowledgeFile.__table__)
            .where(KnowledgeFile.id == 1)
            .values(knowledge_id=999999, file_type=0, file_level_path="1")
        )
    value.store.enforce_closed = False
    objects_before = dict(value.artifacts.objects)
    result = await entry().arun(
        arguments(value, materials_dir=tmp_path), runtime_factory=current_inventory_runtime(value)
    )
    assert not result["can_apply"] and not result["preflight_complete"]
    assert any(item["reason"].endswith("ambiguous_parent_path") for item in result["diagnostics"]), result
    assert value.artifacts.objects == objects_before and value.store.writes == 0
    async with value.sessions() as session, session.begin():
        assert (await session.execute(sa.select(sa.func.count()).select_from(Run.__table__))).scalar_one() == 0
    value.sessions.assert_closed()


async def test_new_run_preview_requires_full_inventory_port(published_input, tmp_path):
    value = published_input
    async with value.sessions() as session, session.begin():
        await session.execute(sa.delete(Run.__table__))
    result = await entry().arun(arguments(value, materials_dir=tmp_path), runtime_factory=runtime(value))
    assert not result["can_apply"] and not result["preflight_complete"]
    assert any(item["reason"].endswith("read_pinned_history_client_required") for item in result["diagnostics"]), result


@pytest.mark.parametrize("published_input", [{"reference_seed": seed_cli_operator}], indirect=True)
async def test_new_run_preview_rejects_freeze_committed_between_its_two_transactions(
    published_input, monkeypatch, tmp_path
):
    from bisheng.core.context.tenant import bypass_tenant_filter
    from bisheng.knowledge.application.unification_inventory import UnificationInventoryApplication

    value = published_input
    # Save a real committed frozen Run, then make the CLI's first transaction
    # observe its absence. The competing writer restores it only after that
    # transaction has closed and before the full inventory starts reading.
    async with value.sessions() as session, session.begin():
        with bypass_tenant_filter():
            original_rows = [dict(row) for row in (await session.execute(sa.select(Run.__table__))).mappings()]
        await session.execute(sa.delete(Run.__table__))
    value.store.enforce_closed = False
    original_preview = UnificationInventoryApplication.arun

    async def competing_freeze(self, session, **kwargs):
        async with value.sessions() as competing, competing.begin():
            await competing.execute(sa.insert(Run.__table__), original_rows)
        return await original_preview(self, session, **kwargs)

    monkeypatch.setattr(UnificationInventoryApplication, "arun", competing_freeze)

    objects_before = dict(value.artifacts.objects)
    result = await entry().arun(
        arguments(value, materials_dir=tmp_path), runtime_factory=current_inventory_runtime(value)
    )
    assert not result["can_apply"]
    assert any(item["reason"] == "migration_inventory_preview_requires_new_run" for item in result["diagnostics"])
    assert value.artifacts.objects == objects_before and value.store.writes == 0
    value.sessions.assert_closed()


async def test_resume_preview_still_requires_original_frozen_run(published_input, tmp_path):
    from bisheng.common.errcode.knowledge import KnowledgeOperationPlanConflictError

    value = published_input
    async with value.sessions() as session, session.begin():
        await session.execute(sa.delete(Run.__table__))
    with pytest.raises(KnowledgeOperationPlanConflictError) as caught:
        await entry().arun(arguments(value, "--resume", materials_dir=tmp_path), runtime_factory=runtime(value))
    assert caught.value.kwargs["reason"] == "migration_cli_resume_requires_frozen_run"


@pytest.mark.parametrize("published_input", [{"reference_seed": seed_cli_operator}], indirect=True)
async def test_new_run_preview_scans_current_tenants_without_old_backup_materials(published_input, tmp_path):
    from bisheng.database.models.tenant import Tenant

    value = published_input
    async with value.sessions() as session, session.begin():
        await session.execute(sa.delete(Run.__table__))
        await session.execute(
            sa.insert(Tenant.__table__).values(id=303, tenant_code="after-original-run", tenant_name="New tenant")
        )
    value.store.enforce_closed = False
    objects_before = dict(value.artifacts.objects)
    result = await entry().arun(
        arguments(value, materials_dir=tmp_path), runtime_factory=current_inventory_runtime(value)
    )
    assert result["preflight_complete"] is True and result["tenant_ids"] == [1, 101, 202, 303]
    assert value.artifacts.objects == objects_before and value.store.writes == 0


async def test_actual_cli_inventory_runtime_needs_no_vector_configuration_or_clients(native_runtime, monkeypatch):
    import sys

    from bisheng.knowledge.application.unification_inventory import UnificationInventoryApplication

    def forbidden(*args, **kwargs):
        raise AssertionError("migration inventory must not open ES or Milvus")

    monkeypatch.setitem(
        sys.modules,
        "bisheng.knowledge.application.unification_physical",
        SimpleNamespace(PhysicalInventoryReader=SimpleNamespace(aopen=forbidden)),
    )
    # The native runtime fixture deliberately has no vector configuration.
    async with entry()._runtime(None) as runtime:
        async with runtime.inventory(None) as inventory:
            assert isinstance(inventory, UnificationInventoryApplication)
    native_runtime.eager.assert_not_awaited()


def test_cli_needs_no_dba_evidence_inputs():
    args = entry().parser().parse_args(["--run-id", "upgrade-310b1", "--environment", "test"])
    assert args.backup_ref is None and args.schema_ref is None
    assert not args.apply and not args.resume


@pytest.mark.parametrize("published_input", [{"reference_seed": seed_cli_operator}], indirect=True)
async def test_legacy_run_recovers_original_fields_without_reading_dba_proofs(published_input, tmp_path):
    value = published_input
    for name in ("backup_ref", "schema_ref"):
        del value.artifacts.objects[value.input[name]["object_key"]]
    objects_before = dict(value.artifacts.objects)
    result = await entry().arun(arguments(value, "--resume", materials_dir=tmp_path), runtime_factory=runtime(value))
    assert result["frozen"] and result["validation_scope"] == "frozen_resume" and result["can_apply"]
    assert value.artifacts.objects == objects_before and value.store.writes == 0
    result = await entry().arun(
        arguments(value, "--apply", "--resume", "--operator-id", "7", materials_dir=tmp_path),
        runtime_factory=runtime(value),
    )
    assert result["ready"] and result["complete"]


@pytest.mark.parametrize("changed", ["backup_ref", "schema_ref", "environment"])
async def test_legacy_run_still_rejects_changed_explicit_identity(published_input, changed, tmp_path):
    from bisheng.common.errcode.knowledge import KnowledgeOperationPlanConflictError

    args = arguments(published_input, legacy=True, materials_dir=tmp_path)
    if changed == "environment":
        args.environment = "another-environment"
    else:
        setattr(args, changed, getattr(args, changed) | {"sha256": "f" * 64})
    with pytest.raises(KnowledgeOperationPlanConflictError) as caught:
        await entry().arun(args, runtime_factory=runtime(published_input))
    assert caught.value.kwargs["reason"] == (
        "migration_upgrade_environment_assertion_changed"
        if changed == "environment"
        else "migration_upgrade_material_assertion_changed"
    )
    assert published_input.store.writes == 0


async def test_new_run_refuses_legacy_descriptor_flags(published_input, tmp_path):
    from bisheng.common.errcode.knowledge import KnowledgeOperationPlanConflictError

    value = published_input
    async with value.sessions() as session, session.begin():
        await session.execute(sa.delete(Run.__table__))
    with pytest.raises(KnowledgeOperationPlanConflictError) as caught:
        await entry().arun(
            arguments(value, legacy=True, materials_dir=tmp_path), runtime_factory=current_inventory_runtime(value)
        )
    assert caught.value.kwargs["reason"] == "migration_cli_legacy_descriptors_require_frozen_run"


@pytest.mark.parametrize("published_input", [{"reference_seed": seed_cli_operator}], indirect=True)
async def test_new_run_interrupted_after_freeze_resumes_without_dba_inputs(published_input, monkeypatch, tmp_path):
    from bisheng.core.context.tenant import bypass_tenant_filter
    from bisheng.knowledge.application.unification_conversion import UnificationSQLConversionApplication

    value = published_input
    async with value.sessions() as session, session.begin():
        await session.execute(sa.delete(Run.__table__))
    for name in ("backup_ref", "schema_ref"):
        del value.artifacts.objects[value.input[name]["object_key"]]
    value.store.enforce_closed = False
    preview = await entry().arun(
        arguments(value, materials_dir=tmp_path), runtime_factory=current_inventory_runtime(value)
    )
    assert preview["can_apply"]

    async def interrupted(*args, **kwargs):
        raise RuntimeError("interrupted after durable M2 freeze")

    with monkeypatch.context() as patch:
        patch.setattr(UnificationSQLConversionApplication, "arun_references", interrupted)
        with pytest.raises(RuntimeError, match="durable M2 freeze"):
            await entry().arun(
                arguments(value, "--apply", "--operator-id", "7", materials_dir=tmp_path),
                runtime_factory=current_inventory_runtime(value),
            )
    async with value.sessions() as session, session.begin():
        with bypass_tenant_filter():
            original = (
                await session.execute(sa.select(Run.baseline_hash, Run.plan_hash).order_by(Run.tenant_id))
            ).all()
    assert len(original) == 3
    result = await entry().arun(
        arguments(value, "--apply", "--resume", "--operator-id", "7", materials_dir=tmp_path),
        runtime_factory=current_inventory_runtime(value),
    )
    assert result["complete"] and result["ready"]
    async with value.sessions() as session, session.begin():
        with bypass_tenant_filter():
            current = (await session.execute(sa.select(Run.baseline_hash, Run.plan_hash).order_by(Run.tenant_id))).all()
    assert current == original

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


def arguments(value, *extra):
    return (
        entry()
        .parser()
        .parse_args(
            [
                "--run-id",
                value.input["run_id"],
                "--environment",
                value.input["environment"],
                "--backup-ref",
                json.dumps(value.input["backup_ref"]),
                "--schema-ref",
                json.dumps(value.input["schema_ref"]),
                *extra,
            ]
        )
    )


def runtime(value):
    @asynccontextmanager
    async def open_runtime(*args, **kwargs):
        yield SimpleNamespace(store=value.artifacts.store, sessions=value.sessions, inventory=None)

    return open_runtime


async def test_default_preview_is_read_only_and_reports_actual_frozen_scope(published_input):
    value, writes = published_input, []

    def observe(connection, cursor, statement, parameters, context, many):
        if statement.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")):
            writes.append(statement)

    sa.event.listen(value.database.engine.sync_engine, "before_cursor_execute", observe)
    try:
        result = await entry().arun(arguments(value), runtime_factory=runtime(value))
    finally:
        sa.event.remove(value.database.engine.sync_engine, "before_cursor_execute", observe)
    assert result["mode"] == "preview" and result["tenant_ids"] == list(value.frozen.tenant_ids)
    assert result["ready"] is False and not writes and value.store.writes == 0
    assert result["validation_scope"] == "frozen_run" and result["preflight_complete"] is False
    value.sessions.assert_closed()


async def test_apply_and_same_run_resume_reach_real_certificate(published_input):
    value = published_input
    args = arguments(value, "--apply", "--operator-id", "7")
    result = await entry().arun(args, runtime_factory=runtime(value))
    assert result["ready"] is True and result["coverage_epoch"] > 0
    assert result["invalid_manifest_ref"] == value.frozen.plan_ref
    args.resume = True
    assert await entry().arun(args, runtime_factory=runtime(value)) == result
    async with value.sessions() as session, session.begin():
        assert (
            await session.execute(sa.select(Run.phase).where(Run.run_id == value.frozen.run_id))
        ).scalar_one() == "completed"


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


async def test_apply_without_run_calls_actual_native_m2_before_original_chain(published_input):
    from test.knowledge_unification import test_migration_inventory_application as m2

    value = published_input
    # Start from the actual pre-conversion SQL state, with no frozen Run.
    # Immutable fixture objects remain harmless content-addressed evidence.
    async with value.sessions() as session, session.begin():
        await session.execute(sa.delete(Run.__table__))
    value.store.enforce_closed = False  # M2's original read TX intentionally spans its read-only evidence IO.

    @asynccontextmanager
    async def native_runtime(args):
        @asynccontextmanager
        async def inventory(session):
            yield m2.application(
                importlib.import_module("bisheng.knowledge.application.unification_inventory"), value.artifacts
            )

        yield SimpleNamespace(store=value.artifacts.store, sessions=value.sessions, inventory=inventory)

    result = await entry().arun(arguments(value, "--apply", "--operator-id", "7"), runtime_factory=native_runtime)
    assert result["ready"] is True and result["complete"] is True


def current_inventory_runtime(value):
    from test.knowledge_unification import test_migration_inventory_application as m2

    @asynccontextmanager
    async def native_runtime(args):
        @asynccontextmanager
        async def inventory(session):
            yield m2.application(
                importlib.import_module("bisheng.knowledge.application.unification_inventory"), value.artifacts
            )

        yield SimpleNamespace(store=value.artifacts.store, sessions=value.sessions, inventory=inventory)

    return native_runtime


async def test_new_run_preview_performs_complete_inventory_without_persisting(published_input):
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
        result = await entry().arun(arguments(value), runtime_factory=current_inventory_runtime(value))
    finally:
        sa.event.remove(value.database.engine.sync_engine, "before_cursor_execute", observe)
    assert result["validation_scope"] == "current_inventory" and result["preflight_complete"] is True
    assert result["tenant_ids"] == [1, 101, 202]
    assert result["frozen"] is False and result["ready"] is False
    assert result["baseline_ref"] is None and result["plan_ref"] is None
    assert not writes and value.artifacts.objects == objects_before
    assert value.store.tuples == tuples_before and value.store.writes == 0
    assert value.store.requests  # The real pinned permission reader participated in the complete inventory.
    async with value.sessions() as session, session.begin():
        assert (await session.execute(sa.select(sa.func.count()).select_from(Run.__table__))).scalar_one() == 0
    value.sessions.assert_closed()


async def test_new_run_preview_reports_actual_data_blocker_instead_of_only_listing_tenants(published_input):
    from bisheng.common.errcode.knowledge import KnowledgeOperationPlanConflictError
    from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile

    value = published_input
    async with value.sessions() as session, session.begin():
        await session.execute(sa.delete(Run.__table__))
        await session.execute(
            sa.update(KnowledgeFile.__table__).where(KnowledgeFile.id == 1).values(knowledge_id=999999)
        )
    value.store.enforce_closed = False
    objects_before = dict(value.artifacts.objects)
    with pytest.raises(KnowledgeOperationPlanConflictError) as caught:
        await entry().arun(arguments(value), runtime_factory=current_inventory_runtime(value))
    assert caught.value.kwargs["reason"] == "unification_resource_file_parent_invalid"
    assert value.artifacts.objects == objects_before and value.store.writes == 0
    async with value.sessions() as session, session.begin():
        assert (await session.execute(sa.select(sa.func.count()).select_from(Run.__table__))).scalar_one() == 0
    value.sessions.assert_closed()


async def test_new_run_preview_requires_full_inventory_port(published_input):
    from bisheng.common.errcode.knowledge import KnowledgeOperationPlanConflictError

    value = published_input
    async with value.sessions() as session, session.begin():
        await session.execute(sa.delete(Run.__table__))
    with pytest.raises(KnowledgeOperationPlanConflictError) as caught:
        await entry().arun(arguments(value), runtime_factory=runtime(value))
    assert caught.value.kwargs["reason"] == "migration_cli_native_inventory_ports_required"


async def test_new_run_preview_rejects_freeze_committed_between_its_two_transactions(published_input, monkeypatch):
    from bisheng.common.errcode.knowledge import KnowledgeOperationPlanConflictError
    from bisheng.core.context.tenant import bypass_tenant_filter
    from bisheng.knowledge.domain.repositories.unification_run_repository import KnowledgeUnificationRunRepository
    from test.knowledge_unification import test_migration_inventory_application as m2

    value = published_input
    # Save a real committed frozen Run, then make the CLI's first transaction
    # observe its absence. The competing writer restores it only after that
    # transaction has closed and before the full inventory starts reading.
    async with value.sessions() as session, session.begin():
        with bypass_tenant_filter():
            original_rows = [dict(row) for row in (await session.execute(sa.select(Run.__table__))).mappings()]
        await session.execute(sa.delete(Run.__table__))
    value.store.enforce_closed = False
    observations = []
    original_get = KnowledgeUnificationRunRepository.aget_global_freeze

    async def observe_freeze(self, session, **kwargs):
        result = await original_get(self, session, **kwargs)
        observations.append(result is not None)
        return result

    monkeypatch.setattr(KnowledgeUnificationRunRepository, "aget_global_freeze", observe_freeze)

    @asynccontextmanager
    async def racing_runtime(args):
        @asynccontextmanager
        async def inventory(session):
            async with value.sessions() as competing, competing.begin():
                await competing.execute(sa.insert(Run.__table__), original_rows)
            yield m2.application(
                importlib.import_module("bisheng.knowledge.application.unification_inventory"), value.artifacts
            )

        yield SimpleNamespace(store=value.artifacts.store, sessions=value.sessions, inventory=inventory)

    objects_before = dict(value.artifacts.objects)
    with pytest.raises(KnowledgeOperationPlanConflictError) as caught:
        await entry().arun(arguments(value), runtime_factory=racing_runtime)
    assert caught.value.kwargs["reason"] == "migration_inventory_preview_requires_new_run"
    assert observations == [False, True]
    assert value.artifacts.objects == objects_before and value.store.writes == 0
    value.sessions.assert_closed()


async def test_resume_preview_still_requires_original_frozen_run(published_input):
    from bisheng.common.errcode.knowledge import KnowledgeOperationPlanConflictError

    value = published_input
    async with value.sessions() as session, session.begin():
        await session.execute(sa.delete(Run.__table__))
    with pytest.raises(KnowledgeOperationPlanConflictError) as caught:
        await entry().arun(arguments(value, "--resume"), runtime_factory=runtime(value))
    assert caught.value.kwargs["reason"] == "migration_cli_resume_requires_frozen_run"


async def test_new_run_preview_does_not_relabel_old_backup_materials_for_new_tenants(published_input):
    from bisheng.common.errcode.knowledge import KnowledgeOperationPlanConflictError
    from bisheng.database.models.tenant import Tenant

    value = published_input
    async with value.sessions() as session, session.begin():
        await session.execute(sa.delete(Run.__table__))
        await session.execute(
            sa.insert(Tenant.__table__).values(id=303, tenant_code="after-original-run", tenant_name="New tenant")
        )
    value.store.enforce_closed = False
    objects_before = dict(value.artifacts.objects)
    with pytest.raises(KnowledgeOperationPlanConflictError) as caught:
        await entry().arun(arguments(value), runtime_factory=current_inventory_runtime(value))
    assert caught.value.kwargs["reason"] == "migration_inventory_material_manifest_identity"
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

"""§122: real reserved Catalog SQL, with immutable original provenance."""

import importlib
from dataclasses import replace
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import sqlalchemy as sa

from bisheng.common.errcode.permission import PermissionMigrationBlockedError
from bisheng.core.openfga.authorization_model_f048 import (
    authorization_model_checksum,
    build_authorization_model_f048,
    required_relations_checksum,
)
from bisheng.permission.application import control_state
from bisheng.permission.application.catalog_api import SqlCatalogState
from bisheng.permission.domain.models import (
    AuthorizationModelRelease,
    PermissionAction,
    PermissionActionResourceScope,
    PermissionCatalogRelease,
    PermissionModel,
    PermissionModelAction,
)
from bisheng.permission.domain.repositories.f118_migration_snapshot_repository import (
    PermissionMigrationSnapshotRepository,
)
from bisheng.permission.domain.services.model_policy import CustomModelSelection
from bisheng.permission.migration import f048_runtime_storage, f118_verify
from bisheng.permission.migration import f118_plan as plans
from test.knowledge_unification import test_perm_migration_snapshot as native
from test.knowledge_unification.test_perm_control_snapshot import session_factory as session_factory
from test.knowledge_unification.test_permission_floor_retirement_signing import legacy_catalog

TABLES = (
    AuthorizationModelRelease,
    PermissionCatalogRelease,
    PermissionAction,
    PermissionActionResourceScope,
    PermissionModel,
    PermissionModelAction,
)


@pytest.fixture
def prepared(session_factory, monkeypatch, tenant_context):
    tenant_context(101)
    monkeypatch.setattr(f048_runtime_storage, "get_async_db_session", session_factory)
    monkeypatch.setattr(control_state, "get_async_db_session", session_factory)

    async def make(*, same_schema=False, count=None, operator=7):
        customs = None
        if count is not None:
            customs = tuple(
                CustomModelSelection(
                    f"custom-{index:05}",
                    f"权限模型-{index:05}",
                    ("download", "use"),
                    active=index % 2 == 0,
                )
                for index in range(count - 4)
            )
        before = legacy_catalog(customs=customs)
        before = replace(
            before,
            models=tuple(replace(row, legacy_source_key="legacy:" + row.model_key) for row in before.models),
        )
        model = build_authorization_model_f048()
        checksum = authorization_model_checksum(model)
        if same_schema:
            before = replace(
                before,
                authorization=replace(
                    before.authorization,
                    model_checksum=checksum,
                    required_relations_checksum=required_relations_checksum(model),
                ),
            )
        monkeypatch.setattr(native, "baseline", lambda _: before)
        async with session_factory() as session:
            engine = session.bind

        # Real parent BEGIN: SQLite legacy mode otherwise commits the first
        # released SAVEPOINT even when the logical caller TX later rolls back.
        @sa.event.listens_for(engine.sync_engine, "begin")
        def begin(connection):
            connection.exec_driver_sql("BEGIN")

        async with session_factory() as session, session.begin():
            await native.seed_catalog(session)
        async with session_factory() as session, session.begin():
            acquired = await PermissionMigrationSnapshotRepository().aload_catalog_baseline(session, environment="test")
            assert acquired == before
            engine = session.bind
        plan = plans.build_catalog_retirement_plan(
            run_id="formal-catalog-stage",
            writer_contract_version="f118-v1",
            before=acquired,
            target_model_checksum=checksum,
            namespace_type_mappings=(("knowledge_library", "knowledge_space"),),
        )
        planner = plans.ResourceRetirementPlanner(catalog_plan=plan)
        remote = SimpleNamespace(
            store_id=before.authorization.store_id,
            list_authorization_models=AsyncMock(return_value=[]),
            write_authorization_model=AsyncMock(return_value="native-target-model"),
        )
        publisher = f048_runtime_storage.OpenFGAMigrationModelPublisher(
            source_client=remote, environment="test", predecessor_model_id=before.authorization.model_id
        )
        target_model_id = await publisher.aget_or_publish(store_id=remote.store_id, model=model, checksum=checksum)
        async with session_factory() as session:
            target = (
                await session.execute(
                    sa.select(AuthorizationModelRelease).where(AuthorizationModelRelease.model_id == target_model_id)
                )
            ).scalar_one()
            target_id = target.id
            assert target.status == ("ACTIVE" if same_schema else "STAGED")
        state = SqlCatalogState(session_factory=session_factory)
        key = "f118-catalog-native-reservation"
        reservation = await state.reserve_draft(
            base_release_id=before.release.id,
            operator_id=operator,
            idempotency_key=key,
            expires_at=datetime.now() + timedelta(days=1),
        )
        return SimpleNamespace(
            factory=session_factory,
            state=state,
            before=before,
            plan=plan,
            planner=planner,
            target=target_id,
            draft=reservation.release_id,
            key=key,
            operator=operator,
            engine=engine,
            remote=remote,
        )

    return make


@pytest.fixture
async def ready(prepared):
    return await prepared()


@pytest.fixture
def module():
    return importlib.import_module("bisheng.permission.domain.repositories.f118_catalog_write_repository")


def arguments(value):
    return {
        "permission_planner": value.planner,
        "draft_id": value.draft,
        "target_authorization_release_id": value.target,
        "operator_id": value.operator,
        "idempotency_key": value.key,
    }


async def raw(session):
    return {
        model.__tablename__: tuple(
            dict(row)
            for row in (await session.execute(sa.select(*model.__table__.c).order_by(model.__table__.c.id))).mappings()
        )
        for model in TABLES
    }


def capture(value):
    statements = []

    def record(_c, _cur, statement, parameters, context, many):
        statements.append((statement, parameters, context, many))

    sa.event.listen(value.engine.sync_engine, "before_cursor_execute", record)
    return statements, lambda: sa.event.remove(value.engine.sync_engine, "before_cursor_execute", record)


def dml(statements):
    return [row for row in statements if row[0].lstrip().split()[0].upper() in {"INSERT", "UPDATE", "DELETE"}]


@pytest.mark.parametrize("same_schema,operator", [(False, 7), (True, 0)])
async def test_actual_reserved_catalog_preserves_all_provenance_and_replays_without_writes(
    prepared, module, same_schema, operator
):
    value = await prepared(same_schema=same_schema, operator=operator)
    writer = module.F118CatalogWriteRepository()
    async with value.factory() as session, session.begin():
        previous = await raw(session)
        await writer.averify_before(session, expected=value.before)
        result = await writer.astage_catalog(session, **arguments(value))
        assert result.release.status == "DRAFT" and not result.release.write_fenced
        assert result.authorization.status == ("ACTIVE" if same_schema else "STAGED")
        assert result.release.required_authorization_model_release_id == value.target
        assert result.actions == value.plan.after_actions
        expected = {row.model_key: row for row in value.plan.after_models}
        assert {row.id for row in result.models}.isdisjoint({row.id for row in value.before.models})
        assert all(replace(row, id=expected[row.model_key].id) == expected[row.model_key] for row in result.models)
        assert any(row.retired_use_level_floor == 3 for row in result.models)
        actual = await raw(session)
        assert actual["authorization_model_release"] == previous["authorization_model_release"]
        for name, rows in previous.items():
            for row in rows:
                if name == "permission_catalog_release" and row["id"] == value.draft:
                    after = next(item for item in actual[name] if item["id"] == row["id"])
                    assert {
                        k: v
                        for k, v in after.items()
                        if k not in {"checksum", "required_authorization_model_release_id"}
                    } == {
                        k: v for k, v in row.items() if k not in {"checksum", "required_authorization_model_release_id"}
                    }
                else:
                    assert row in actual[name]
        assert not session.identity_map and not session.new and not session.dirty
    loaded = await value.state.load_snapshot(value.draft)
    assert loaded.action_release.checksum == value.plan.action_checksum
    assert loaded.model_release.checksum == value.plan.model_checksum
    statements, remove = capture(value)
    try:
        async with value.factory() as session, session.begin():
            assert await writer.astage_catalog(session, **arguments(value)) == result
            assert await writer.averify_staged_catalog(session, **arguments(value)) == result
        assert not dml(statements)
    finally:
        remove()
    assert value.remote.write_authorization_model.await_count == (0 if same_schema else 1)
    # Native final-state fixture checks the existing online checksum SSOT only;
    # the production Repository never performs this publication.
    async with value.factory() as session, session.begin():
        await session.execute(
            sa.update(PermissionCatalogRelease)
            .where(PermissionCatalogRelease.id == value.before.release.id)
            .values(status="RETIRED")
        )
        await session.execute(
            sa.update(PermissionCatalogRelease)
            .where(PermissionCatalogRelease.id == value.draft)
            .values(status="CURRENT")
        )
        if not same_schema:
            await session.execute(
                sa.update(AuthorizationModelRelease)
                .where(AuthorizationModelRelease.id == value.target)
                .values(status="ACTIVE")
            )
    assert (await control_state.SqlPermissionControlState().current_catalog()).checksum == result.release.checksum
    async with value.factory() as session, session.begin():
        current = await PermissionMigrationSnapshotRepository().aload_catalog_baseline(session, environment="test")
    assert f118_verify.verify_catalog_retirement(plan=value.plan, actual=current).complete


@pytest.mark.parametrize("field", ["checksum", "draft_owner_id", "model_checksum", "legacy_source_key"])
async def test_complete_before_facts_are_exactly_rechecked(ready, module, field):
    value = ready
    expected = value.before
    if field in {"checksum", "draft_owner_id"}:
        expected = replace(
            expected, release=replace(expected.release, **{field: "a" * 64 if field == "checksum" else 99})
        )
    elif field == "model_checksum":
        expected = replace(expected, authorization=replace(expected.authorization, model_checksum="e" * 64))
    else:
        expected = replace(expected, models=(replace(expected.models[0], legacy_source_key=None), *expected.models[1:]))
    async with value.factory() as session, session.begin():
        with pytest.raises(PermissionMigrationBlockedError):
            await module.F118CatalogWriteRepository().averify_before(session, expected=expected)


@pytest.mark.parametrize(
    "changes",
    [
        {"operator_id": True},
        {"operator_id": -1},
        {"operator_id": 99},
        {"draft_id": True},
        {"draft_id": 9999},
        {"target_authorization_release_id": True},
        {"target_authorization_release_id": 9999},
        {"idempotency_key": ""},
        {"idempotency_key": "x" * 65},
        {"idempotency_key": "other-run"},
        {"permission_planner": object()},
    ],
)
async def test_bare_ids_or_invalid_typed_arguments_never_admit_a_reservation(ready, module, changes):
    args = arguments(ready) | changes
    statements, remove = capture(ready)
    try:
        async with ready.factory() as session, session.begin():
            with pytest.raises(PermissionMigrationBlockedError):
                await module.F118CatalogWriteRepository().astage_catalog(session, **args)
        assert not dml(statements)
    finally:
        remove()


@pytest.mark.parametrize(
    "changes",
    [
        {"status": "CURRENT"},
        {"status": "PROJECTING"},
        {"status": "COMMITTED"},
        {"predecessor_id": None},
        {"version": 0},
        {"release_key": "forged"},
        {"draft_owner_id": 99},
        {"write_fenced": True},
        {"commit_checksum": "a" * 64},
        {"projection_checkpoint": 1},
        {"published_at": datetime(2020, 1, 1)},
        {"expires_at": datetime(2020, 1, 1)},
        {"checksum": "e" * 64},
        {"required_authorization_model_release_id": None},
    ],
)
async def test_initial_reservation_must_be_genuine_empty_and_unpublished(ready, module, changes):
    value = ready
    if changes.get("required_authorization_model_release_id", 1) is None:
        changes = {"required_authorization_model_release_id": value.target}
    async with value.factory() as session, session.begin():
        await session.execute(
            sa.update(PermissionCatalogRelease).where(PermissionCatalogRelease.id == value.draft).values(**changes)
        )
    statements, remove = capture(value)
    try:
        async with value.factory() as session, session.begin():
            with pytest.raises(PermissionMigrationBlockedError):
                await module.F118CatalogWriteRepository().astage_catalog(session, **arguments(value))
        assert not dml(statements)
    finally:
        remove()


@pytest.mark.parametrize(
    "changes",
    [
        {"environment": "other"},
        {"store_id": "foreign-store"},
        {"model_checksum": "e" * 64},
        {"predecessor_model_id": "foreign-model"},
        {"status": "ACTIVE"},
        {"required_relations_checksum": "invalid"},
        {"model_id": ""},
        {"openfga_version": ""},
    ],
)
async def test_different_schema_requires_actual_complete_target_staged_pin(ready, module, changes):
    async with ready.factory() as session, session.begin():
        await session.execute(
            sa.update(AuthorizationModelRelease).where(AuthorizationModelRelease.id == ready.target).values(**changes)
        )
    async with ready.factory() as session, session.begin():
        with pytest.raises(PermissionMigrationBlockedError):
            await module.F118CatalogWriteRepository().astage_catalog(session, **arguments(ready))
        assert not (
            await session.execute(
                sa.select(PermissionAction.id).where(PermissionAction.catalog_release_id == ready.draft)
            )
        ).all()


@pytest.mark.parametrize(
    "corruption", ["half", "extra", "legacy", "floor", "scope", "link", "checksum", "binding", "expired"]
)
async def test_partial_or_corrupt_staged_payload_is_never_repaired(ready, module, corruption):
    value = ready
    writer = module.F118CatalogWriteRepository()
    if corruption != "half":
        async with value.factory() as session, session.begin():
            await writer.astage_catalog(session, **arguments(value))
    async with value.factory() as session, session.begin():
        if corruption in {"half", "extra"}:
            session.add(PermissionAction(catalog_release_id=value.draft, code="unexpected", name="extra", level=1))
        elif corruption in {"legacy", "floor"}:
            await session.execute(
                sa.update(PermissionModel)
                .where(PermissionModel.catalog_release_id == value.draft, PermissionModel.model_key == "mixed-use")
                .values(
                    **({"legacy_source_key": None} if corruption == "legacy" else {"retired_use_level_floor": None})
                )
            )
        elif corruption in {"scope", "link"}:
            table = PermissionActionResourceScope if corruption == "scope" else PermissionModelAction
            parents = sa.select(PermissionAction.id if corruption == "scope" else PermissionModel.id).where(
                (PermissionAction.catalog_release_id if corruption == "scope" else PermissionModel.catalog_release_id)
                == value.draft
            )
            column = table.action_id if corruption == "scope" else table.model_id
            ident = (
                await session.execute(sa.select(table.id).where(column.in_(parents)).order_by(table.id).limit(1))
            ).scalar_one()
            await session.execute(sa.delete(table).where(table.id == ident))
        else:
            changes = (
                {"checksum": "e" * 64}
                if corruption == "checksum"
                else {"required_authorization_model_release_id": value.before.authorization.id}
                if corruption == "binding"
                else {"expires_at": datetime(2020, 1, 1)}
            )
            await session.execute(
                sa.update(PermissionCatalogRelease).where(PermissionCatalogRelease.id == value.draft).values(**changes)
            )
    if corruption == "legacy":
        assert (await value.state.load_snapshot(value.draft)).model_release.checksum == value.plan.model_checksum
    statements, remove = capture(value)
    try:
        async with value.factory() as session, session.begin():
            if corruption == "expired":
                await writer.astage_catalog(session, **arguments(value))
            else:
                with pytest.raises(PermissionMigrationBlockedError):
                    await writer.astage_catalog(session, **arguments(value))
        assert not dml(statements)
    finally:
        remove()

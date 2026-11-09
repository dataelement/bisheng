"""§122: caller transaction isolation, tail failures, and real by-ID facts."""

import asyncio

import pytest
import sqlalchemy as sa

from bisheng.common.errcode.permission import PermissionMigrationBlockedError
from bisheng.core.context.tenant import bypass_tenant_filter, current_tenant_id, set_current_tenant_id
from bisheng.permission.domain.models import (
    AuthorizationModelRelease,
    PermissionAction,
    PermissionModel,
)
from bisheng.permission.domain.repositories.f118_migration_snapshot_repository import (
    PermissionMigrationSnapshotRepository,
)
from test.knowledge_unification.test_permission_catalog_write_repository import (
    arguments,
    capture,
    dml,
    raw,
)
from test.knowledge_unification.test_permission_catalog_write_repository import (
    module as module,
)
from test.knowledge_unification.test_permission_catalog_write_repository import (
    prepared as prepared,
)
from test.knowledge_unification.test_permission_catalog_write_repository import (
    ready as ready,
)
from test.knowledge_unification.test_permission_catalog_write_repository import (
    session_factory as session_factory,
)


async def test_by_id_raw_reader_keeps_draft_and_staged_status_without_touching_current(ready, module):
    async with ready.factory() as session, session.begin():
        raw_before = await raw(session)
        result = await PermissionMigrationSnapshotRepository().aload_catalog_release(session, release_id=ready.draft)
        assert result.release.status == "DRAFT" and result.authorization.status == "ACTIVE"
        assert result.actions == result.models == ()
        assert result.release.required_authorization_model_release_id == ready.before.authorization.id
        assert await raw(session) == raw_before


@pytest.mark.parametrize(
    "failure_point", ["permission_action_resource_scope", "permission_model", "permission_model_action", "header"]
)
@pytest.mark.parametrize("cancel", [False, True])
async def test_late_failure_or_cancel_rolls_back_own_savepoint_when_outer_catches_and_commits(
    ready, module, failure_point, cancel, monkeypatch
):
    writer = module.F118CatalogWriteRepository()
    async with ready.factory() as session, session.begin():
        # A native unrelated change before the Repository remains caller-owned.
        await session.execute(
            sa.update(AuthorizationModelRelease)
            .where(AuthorizationModelRelease.id == ready.target)
            .values(activated_at=sa.func.current_timestamp())
        )
        original = await raw(session)
        execute = session.execute
        triggered = False

        async def faulty(statement, *args, **kwargs):
            nonlocal triggered
            result = await execute(statement, *args, **kwargs)
            table = getattr(getattr(statement, "table", None), "name", "")
            match = (getattr(statement, "is_insert", False) and table == failure_point) or (
                failure_point == "header"
                and getattr(statement, "is_update", False)
                and table == "permission_catalog_release"
            )
            if match and not triggered:
                triggered = True
                raise asyncio.CancelledError() if cancel else RuntimeError("native-after-sql")
            return result

        monkeypatch.setattr(session, "execute", faulty)
        with pytest.raises(asyncio.CancelledError if cancel else RuntimeError):
            await writer.astage_catalog(session, **arguments(ready))
        assert triggered and session.in_transaction()
        monkeypatch.setattr(session, "execute", execute)
        assert await raw(session) == original
    async with ready.factory() as session, session.begin():
        assert await raw(session) == original


@pytest.mark.parametrize("drift", ["tenant", "nested", "dirty", "auth"])
async def test_every_await_checks_native_context_and_final_auth_is_rechecked(ready, module, drift, monkeypatch):
    async with ready.factory() as session, session.begin():
        original = await raw(session)
        execute = session.execute
        fired = False
        token = None
        nested = None

        async def change(statement, *args, **kwargs):
            nonlocal fired, token, nested
            result = await execute(statement, *args, **kwargs)
            table = getattr(getattr(statement, "table", None), "name", "")
            if not fired and getattr(statement, "is_insert", False) and table == "permission_model":
                fired = True
                if drift == "tenant":
                    token = set_current_tenant_id(202)
                elif drift == "nested":
                    nested = await session.begin_nested()
                elif drift == "dirty":
                    session.add(PermissionAction(catalog_release_id=ready.draft, code="pending", name="pending"))
                else:
                    await execute(
                        sa.update(AuthorizationModelRelease)
                        .where(AuthorizationModelRelease.id == ready.target)
                        .values(store_id="late-foreign")
                    )
            return result

        monkeypatch.setattr(session, "execute", change)
        try:
            with pytest.raises(PermissionMigrationBlockedError):
                await module.F118CatalogWriteRepository().astage_catalog(session, **arguments(ready))
            assert fired
        finally:
            if token is not None:
                current_tenant_id.reset(token)
            if nested is not None and nested.is_active:
                await nested.rollback()
            monkeypatch.setattr(session, "execute", execute)
        assert await raw(session) == original


@pytest.mark.parametrize("mode", ["no_tx", "dirty", "bypass", "wrong_tenant"])
async def test_native_transaction_cleanliness_and_original_tenant_are_required(ready, module, mode):
    async with ready.factory() as session:
        if mode != "no_tx":
            await session.begin()
        if mode == "dirty":
            session.add(PermissionAction(catalog_release_id=ready.draft, code="pending", name="pending"))
        if mode == "bypass":
            with bypass_tenant_filter(), pytest.raises(PermissionMigrationBlockedError):
                await module.F118CatalogWriteRepository().astage_catalog(session, **arguments(ready))
        elif mode == "wrong_tenant":
            token = set_current_tenant_id(None)
            try:
                with pytest.raises(PermissionMigrationBlockedError):
                    await module.F118CatalogWriteRepository().astage_catalog(session, **arguments(ready))
            finally:
                current_tenant_id.reset(token)
        else:
            with pytest.raises(PermissionMigrationBlockedError):
                await module.F118CatalogWriteRepository().astage_catalog(session, **arguments(ready))
        await session.rollback()


async def test_parent_rollback_preserves_original_empty_reservation(ready, module):
    async with ready.factory() as session:
        await session.begin()
        before = await raw(session)
        await module.F118CatalogWriteRepository().astage_catalog(session, **arguments(ready))
        await session.rollback()
    async with ready.factory() as session, session.begin():
        assert await raw(session) == before


async def test_staged_verifier_rejects_empty_and_wrong_reservation_without_writes(ready, module):
    async with ready.factory() as session, session.begin():
        with pytest.raises(PermissionMigrationBlockedError):
            await module.F118CatalogWriteRepository().averify_staged_catalog(session, **arguments(ready))


@pytest.mark.parametrize("same_schema", [False, True])
async def test_never_selects_another_pin_just_because_checksum_matches(prepared, module, same_schema):
    value = await prepared(same_schema=same_schema)
    async with value.factory() as session, session.begin():
        source = await session.get(AuthorizationModelRelease, value.target)
        values = source.model_dump(exclude={"id", "create_time", "update_time"})
        values["model_id"] = "another-real-row"
        session.add(AuthorizationModelRelease(**values))
        await session.flush()
        other = (
            await session.execute(
                sa.select(AuthorizationModelRelease.id).where(AuthorizationModelRelease.model_id == "another-real-row")
            )
        ).scalar_one()
    if same_schema:
        async with value.factory() as session, session.begin():
            with pytest.raises(PermissionMigrationBlockedError):
                await module.F118CatalogWriteRepository().astage_catalog(
                    session, **(arguments(value) | {"target_authorization_release_id": other})
                )
    else:
        # The distinct real STAGED row is a valid explicitly selected target;
        # no hidden lookup may substitute value.target instead.
        async with value.factory() as session, session.begin():
            result = await module.F118CatalogWriteRepository().astage_catalog(
                session, **(arguments(value) | {"target_authorization_release_id": other})
            )
            assert result.authorization.id == other


async def test_target_drift_during_final_before_read_is_rejected_before_return(ready, module, monkeypatch):
    snapshots = PermissionMigrationSnapshotRepository()
    original_read = snapshots.aload_catalog_release
    visits = 0

    async def changing(session, *, release_id):
        nonlocal visits
        result = await original_read(session, release_id=release_id)
        if release_id == ready.before.release.id:
            visits += 1
            if visits == 2:
                await session.execute(
                    sa.update(AuthorizationModelRelease)
                    .where(AuthorizationModelRelease.id == ready.target)
                    .values(store_id="after-final-lock-read")
                )
        return result

    monkeypatch.setattr(snapshots, "aload_catalog_release", changing)
    async with ready.factory() as session, session.begin():
        before = await raw(session)
        with pytest.raises(PermissionMigrationBlockedError):
            await module.F118CatalogWriteRepository(snapshot_repository=snapshots).astage_catalog(
                session, **arguments(ready)
            )
        assert visits == 2 and await raw(session) == before


async def test_verified_stage_is_global_and_accepts_concrete_tenant_other_than_one(ready, module):
    token = set_current_tenant_id(202)
    try:
        async with ready.factory() as session, session.begin():
            result = await module.F118CatalogWriteRepository().astage_catalog(session, **arguments(ready))
            assert result.release.id == ready.draft
    finally:
        current_tenant_id.reset(token)


@pytest.mark.parametrize("table", ["permission_model", "permission_model_action"])
@pytest.mark.parametrize("cancel", [False, True])
async def test_real_second_bulk_page_failure_cannot_leave_any_children(prepared, module, table, cancel, monkeypatch):
    value = await prepared(count=401)
    async with value.factory() as session, session.begin():
        before = await raw(session)
        execute = session.execute
        pages = 0

        async def fail_second(statement, *args, **kwargs):
            nonlocal pages
            result = await execute(statement, *args, **kwargs)
            if getattr(statement, "is_insert", False) and statement.table.name == table:
                pages += 1
                if pages == 2:
                    raise asyncio.CancelledError() if cancel else RuntimeError("after-real-second-bulk-page")
            return result

        monkeypatch.setattr(session, "execute", fail_second)
        with pytest.raises(asyncio.CancelledError if cancel else RuntimeError):
            await module.F118CatalogWriteRepository().astage_catalog(session, **arguments(value))
        monkeypatch.setattr(session, "execute", execute)
        assert pages == 2 and await raw(session) == before
    async with value.factory() as session, session.begin():
        assert await raw(session) == before


@pytest.mark.parametrize("table", [PermissionModel, AuthorizationModelRelease])
async def test_actual_original_sql_drift_is_blocked_before_first_child_write(ready, module, table):
    async with ready.factory() as session, session.begin():
        if table is PermissionModel:
            await session.execute(
                sa.update(table)
                .where(table.catalog_release_id == ready.before.release.id)
                .values(legacy_source_key=None)
            )
        else:
            await session.execute(
                sa.update(table).where(table.id == ready.before.authorization.id).values(model_checksum="e" * 64)
            )
    statements, remove = capture(ready)
    try:
        async with ready.factory() as session, session.begin():
            with pytest.raises(PermissionMigrationBlockedError):
                await module.F118CatalogWriteRepository().astage_catalog(session, **arguments(ready))
        assert not dml(statements)
    finally:
        remove()


@pytest.mark.parametrize("ident", [True, 0, 999999])
async def test_by_id_reader_rejects_bad_or_missing_real_identity(ready, ident):
    async with ready.factory() as session, session.begin():
        with pytest.raises(PermissionMigrationBlockedError):
            await PermissionMigrationSnapshotRepository().aload_catalog_release(session, release_id=ident)


async def test_database_immutable_create_time_drift_fails_closed_and_rolls_back(ready, module):
    async with ready.factory() as session, session.begin():
        await session.execute(
            sa.text(
                f"CREATE TRIGGER force_catalog_time AFTER UPDATE ON permission_catalog_release "
                f"WHEN NEW.id={ready.draft} BEGIN UPDATE permission_catalog_release "
                f"SET create_time='2099-01-01 00:00:00' WHERE id=NEW.id; END"
            )
        )
    async with ready.factory() as session, session.begin():
        before = await raw(session)
        with pytest.raises(PermissionMigrationBlockedError):
            await module.F118CatalogWriteRepository().astage_catalog(session, **arguments(ready))
        assert await raw(session) == before
    async with ready.factory() as session, session.begin():
        assert await raw(session) == before


async def test_database_managed_update_time_is_allowed_without_clock_tolerance(ready, module):
    async with ready.factory() as session, session.begin():
        await session.execute(
            sa.text(
                f"CREATE TRIGGER managed_catalog_update AFTER UPDATE ON permission_catalog_release "
                f"WHEN NEW.id={ready.draft} BEGIN UPDATE permission_catalog_release "
                f"SET update_time='2099-01-01 00:00:00' WHERE id=NEW.id; END"
            )
        )
    async with ready.factory() as session, session.begin():
        before = await raw(session)
        result = await module.F118CatalogWriteRepository().astage_catalog(session, **arguments(ready))
        after = await raw(session)
        assert result.release.status == "DRAFT"
        draft_before = next(row for row in before["permission_catalog_release"] if row["id"] == ready.draft)
        draft_after = next(row for row in after["permission_catalog_release"] if row["id"] == ready.draft)
        assert draft_after["update_time"].year == 2099
        mutable = {"checksum", "required_authorization_model_release_id", "update_time"}
        assert {key: value for key, value in draft_before.items() if key not in mutable} == {
            key: value for key, value in draft_after.items() if key not in mutable
        }
        assert before["authorization_model_release"] == after["authorization_model_release"]
        original = next(row for row in before["permission_catalog_release"] if row["id"] == ready.before.release.id)
        assert original in after["permission_catalog_release"]

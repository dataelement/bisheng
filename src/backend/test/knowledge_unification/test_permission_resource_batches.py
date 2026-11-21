"""Bounded native permission IO, atomic batch rollback and original Run recovery."""

import asyncio
from math import ceil

import pytest
import sqlalchemy as sa
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.errcode.base import BaseErrorCode
from bisheng.common.errcode.permission import PermissionMigrationBlockedError
from bisheng.core.context.tenant import get_current_tenant_id, tenant_execution_scope
from bisheng.knowledge.application.unification_permissions import (
    PermissionPublicationApplication,
    PermissionPublicationInput,
)
from bisheng.permission.domain.models import ResourcePermissionMode
from bisheng.permission.domain.repositories.f118_migration_snapshot_repository import (
    PermissionMigrationSnapshotRepository,
)
from bisheng.permission.domain.repositories.f118_resource_write_repository import F118ResourceWriteRepository
from test.knowledge_unification.test_perm_migration_snapshot import storage as storage
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


@pytest.mark.parametrize("count", [50, 100])
async def test_batch_reader_matches_individual_buckets_with_constant_select_count(storage, count):
    async with AsyncSession(storage) as session, session.begin():
        session.add_all(
            [
                ResourcePermissionMode(
                    id=i,
                    tenant_id=101,
                    resource_type="knowledge_library",
                    resource_id=str(i),
                    mode="INHERIT",
                    version=1,
                    projection_state="CURRENT",
                )
                for i in range(1000, 1000 + count)
            ]
        )
    requests = tuple(
        (i, (("knowledge_library", str(i)), ("knowledge_space", str(i)))) for i in range(1000, 1000 + count)
    )
    repo = PermissionMigrationSnapshotRepository()
    async with AsyncSession(storage) as session, session.begin():
        expected = tuple(
            [await repo.aload_resource(session, mode_id=ident, resource_keys=keys) for ident, keys in requests]
        )
        selects = []

        def capture(conn, cursor, statement, parameters, context, many):
            if statement.lstrip().upper().startswith("SELECT"):
                selects.append((statement, parameters))

        sa.event.listen(storage.sync_engine, "before_cursor_execute", capture)
        try:
            assert await repo.aload_resources(session, requests=requests) == expected
        finally:
            sa.event.remove(storage.sync_engine, "before_cursor_execute", capture)
        assert len(selects) == 3
        assert all(len(parameters) <= 500 for _, parameters in selects)
        with pytest.raises(PermissionMigrationBlockedError):
            await repo.aload_resources(session, requests=(requests[0], requests[0]))


async def inputs(value):
    application = app(value)
    prepared = await PermissionPublicationInput(
        application=application,
        frozen=value.frozen,
        inputs={key: value.input[key] for key in ("environment", "backup_ref", "schema_ref")},
    ).aload()
    return prepared, await prepared.aplans(101)


@pytest.mark.parametrize("published_input", [{"roots": 105}], indirect=True)
async def test_tail_drift_rolls_back_every_resource_in_the_same_batch(published_input):
    value = published_input
    prepared, plans = await inputs(value)
    batch = plans[:100]
    assert len(batch) == 100
    async with value.database.engine.begin() as connection:
        await connection.exec_driver_sql(
            "CREATE TRIGGER f118_batch_tail AFTER UPDATE OF resource_type ON resource_permission_mode "
            "BEGIN UPDATE permission_grant_assignee SET source_ref='changed' WHERE id=101; END"
        )
    with tenant_execution_scope(101):
        async with value.sessions() as session, session.begin():
            with pytest.raises(PermissionMigrationBlockedError):
                await F118ResourceWriteRepository(permission_planner=prepared.planner).aapply_resources(
                    session, plans=batch
                )
            actual = await PermissionMigrationSnapshotRepository().aload_resources(
                session,
                requests=tuple(
                    (
                        plan.before.mode.id,
                        (
                            (plan.before.resource_type, plan.before.resource_id),
                            (plan.after.resource_type, plan.after.resource_id),
                        ),
                    )
                    for plan in batch
                ),
            )
            assert actual == tuple(plan.before for plan in batch)


@pytest.mark.parametrize("published_input", [{"roots": 205}], indirect=True)
@pytest.mark.parametrize("failed_prefix", [100, 200])
@pytest.mark.parametrize("after,cancel", [(False, False), (True, False), (True, True)])
async def test_batch_checkpoint_unknown_commit_resumes_without_partial_adoption(
    published_input, monkeypatch, after, cancel, failed_prefix
):
    value, fired = published_input, False
    original = PermissionPublicationApplication._commit

    async def fault(self, frozen, key, expected, checkpoint, effect=None):
        nonlocal fired
        if (
            key == "permission_namespace"
            and get_current_tenant_id() == 101
            and checkpoint["processed_count"] == failed_prefix
            and not fired
        ):
            fired = True
            value.sessions.fail_at = value.sessions.commits + 1
            value.sessions.after, value.sessions.cancel = after, cancel
        return await original(self, frozen, key, expected, checkpoint, effect)

    monkeypatch.setattr(PermissionPublicationApplication, "_commit", fault)
    with pytest.raises(asyncio.CancelledError if after and cancel else BaseErrorCode):
        await app(value).arun_permissions(**value.input, operator_id=7)
    assert fired
    with tenant_execution_scope(101):
        async with value.sessions() as session, session.begin():
            count = (
                await session.execute(
                    sa.select(sa.func.count())
                    .select_from(ResourcePermissionMode)
                    .where(ResourcePermissionMode.resource_type == "knowledge_space")
                )
            ).scalar_one()
            assert count == (failed_prefix if after else failed_prefix - 100)
    value.sessions.fail_at = None
    assert (await app(value).arun_permissions(**value.input, operator_id=7)).complete
    writes = value.store.writes
    assert (await app(value).arun_permissions(**value.input, operator_id=7)).complete
    assert value.store.writes == writes


@pytest.mark.parametrize("published_input", [{"roots": 205}], indirect=True)
async def test_namespace_checkpoints_advance_only_at_atomic_batch_boundaries(published_input, monkeypatch):
    value = published_input
    _prepared, plans = await inputs(value)
    original, checkpoints = PermissionPublicationApplication._commit, []

    async def record(self, frozen, key, expected, checkpoint, effect=None):
        if key == "permission_namespace" and get_current_tenant_id() == 101:
            checkpoints.append(checkpoint["processed_count"])
        return await original(self, frozen, key, expected, checkpoint, effect)

    monkeypatch.setattr(PermissionPublicationApplication, "_commit", record)
    assert (await app(value).arun_permissions(**value.input, operator_id=7)).complete
    assert len(checkpoints) == ceil(len(plans) / 100)
    assert checkpoints == [*range(100, len(plans), 100), len(plans)]


@pytest.mark.parametrize("published_input", [{"roots": 105}], indirect=True)
@pytest.mark.parametrize("prefix_count", [1, 99, 100, 101])
async def test_old_single_resource_checkpoint_resumes_with_new_batches(published_input, monkeypatch, prefix_count):
    from bisheng.knowledge.application.unification_permissions import _checksum

    value = published_input
    original = PermissionPublicationApplication._resources

    async def old_prefix(self, frozen, inputs, meta):
        with tenant_execution_scope(101):
            plans = await inputs.aplans(101)
            repository = F118ResourceWriteRepository(permission_planner=inputs.planner)
            checkpoint, seed = None, _checksum(meta)
            for ordinal, plan in enumerate(plans[:prefix_count], 1):

                async def effect(session, plan=plan):
                    return await repository.aapply_resource(session, plan=plan)

                seed = _checksum((seed, plan.checksum))
                value = self._value(meta, ordinal, complete=False, digest=seed)
                await self._commit(frozen, "permission_namespace", checkpoint, value, effect)
                checkpoint = value
        raise RuntimeError("stopped after the old one-resource checkpoint")

    monkeypatch.setattr(PermissionPublicationApplication, "_resources", old_prefix)
    with pytest.raises(BaseErrorCode):
        await app(value).arun_permissions(**value.input, operator_id=7)
    monkeypatch.setattr(PermissionPublicationApplication, "_resources", original)
    assert (await app(value).arun_permissions(**value.input, operator_id=7)).complete

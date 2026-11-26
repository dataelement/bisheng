"""T157/T158: original M3 entry must publish the entire frozen permission plan."""

import pytest
import sqlalchemy as sa

from bisheng.common.errcode.base import BaseErrorCode
from bisheng.knowledge.application.unification_conversion import UnificationSQLConversionApplication
from bisheng.knowledge.domain.models.knowledge_unification_run import KnowledgeUnificationRun as Run
from bisheng.permission.application import control_state, sql_runtime
from bisheng.permission.domain.models import (
    PermissionCatalogRelease,
    PermissionGrant,
    PermissionGrantAssignee,
    ResourcePermissionMode,
)
from bisheng.permission.domain.repositories.f118_migration_snapshot_repository import (
    PermissionMigrationSnapshotRepository,
)
from test.knowledge_unification.permission_publication_native import (
    complete as complete,
)
from test.knowledge_unification.permission_publication_native import (
    native as native,
)
from test.knowledge_unification.permission_publication_native import (
    published_input as published_input,
)
from test.knowledge_unification.permission_publication_native import (
    raw_resource_native as raw_resource_native,
)
from test.knowledge_unification.permission_publication_native import (
    resource_native as resource_native,
)
from test.knowledge_unification.permission_publication_native import (
    transport as transport,
)


def app(value):
    return UnificationSQLConversionApplication(artifact_store=value.artifacts.store, session_factory=value.sessions)


@pytest.mark.parametrize("published_input", [False, True], indirect=True)
async def test_original_m3_entry_reaches_real_current_and_complete_original_run(published_input):
    value = published_input
    original = set(value.store.tuples)
    result = await app(value).arun_permissions(**value.input, operator_id=7)
    assert result.complete and result.run_id == value.frozen.run_id
    value.sessions.assert_closed()
    current = await control_state.SqlPermissionControlState().current_catalog()
    async with value.sessions() as session, session.begin():
        catalog = await PermissionMigrationSnapshotRepository().aload_catalog_baseline(session, environment="test")
        assert catalog.release.id != value.before.release.id
        assert catalog.authorization.model_checksum == current.model_checksum
        assert (
            catalog.authorization.id == value.before.authorization.id
            if value.same
            else catalog.authorization.id != value.before.authorization.id
        )
        mode = (
            await session.execute(sa.select(ResourcePermissionMode).where(ResourcePermissionMode.id == 9000))
        ).scalar_one()
        assert mode.resource_type == "knowledge_space" and mode.version == 1 and mode.operation_id is None
        grants = (await session.execute(sa.select(PermissionGrant).order_by(PermissionGrant.id))).scalars().all()
        assert [row.id for row in grants] == [101, 102]
        assert all(row.resource_type == "knowledge_space" for row in grants)
        sources = (
            (await session.execute(sa.select(PermissionGrantAssignee).order_by(PermissionGrantAssignee.id)))
            .scalars()
            .all()
        )
        assert [row.id for row in sources] == [101, 102] and all(row.version == 1 for row in sources)
        runs = (await session.execute(sa.select(Run).order_by(Run.tenant_id))).scalars().all()
        assert all(row.phase == "converting" and row.source_coverage == {} for row in runs)
        assert any(
            checkpoint.get("complete")
            for row in runs
            for key, checkpoint in row.checkpoints["converting"].items()
            if key.startswith("permission")
        )
    assert ("user:42", "member", "tenant:202") in value.store.tuples
    assert not any(
        row[2] == "knowledge_library:9000" or row[0] == "knowledge_library:9000" for row in value.store.tuples
    )
    old_keys, new_keys = [], []
    for key in ("owner", "inactive-model"):
        old_keys.append(
            sql_runtime.stable_grant_key(
                tenant_id=101, resource_type="knowledge_library", resource_id="9000", model_key=key
            )
        )
        new_keys.append(
            sql_runtime.stable_grant_key(
                tenant_id=101, resource_type="knowledge_space", resource_id="9000", model_key=key
            )
        )
    assert not any(
        row[2] in {"permission_grant:" + key for key in old_keys}
        or row[0] in {"permission_grant:" + key for key in old_keys}
        for row in value.store.tuples
    )
    assert ("user:7", "protected_assignee", "permission_grant:" + new_keys[0]) in value.store.tuples
    assert ("user:7", "ordinary_assignee", "permission_grant:" + new_keys[1]) in value.store.tuples
    assert sum(row == ("user:7", "visible", "knowledge_space:9000") for row in value.store.tuples) == 1
    # Catalog history is retained; only its active pointer changes.
    assert any(row in value.store.tuples for row in original if row[2].startswith("permission_model_release:before~"))
    writes = value.store.writes
    assert await app(value).arun_permissions(**value.input, operator_id=7) == result
    assert value.store.writes == writes
    assert value.store.scans <= 8


@pytest.mark.parametrize("corrupt", ["extra_live", "missing_live", "unknown_namespace", "artifact_tail"])
async def test_real_before_or_complete_artifact_mismatch_blocks_before_publishing(published_input, corrupt):
    value = published_input
    if corrupt == "extra_live":
        value.store.tuples.add(("user:99", "member", "tenant:202"))
    elif corrupt == "missing_live":
        value.store.tuples.remove(("user:7", "visible", "knowledge_library:9000"))
    elif corrupt == "unknown_namespace":
        # Re-freeze the same actual live unknown edge, so this is a semantic
        # namespace/schema rejection, not a fabricated hash mismatch.
        assert ("user:7", "unknown_relation", "knowledge_library:9000") in value.store.tuples
    else:
        key = next(
            key
            for key, body in reversed(tuple(value.artifacts.objects.items()))
            if b'"section":"permission_namespace"' in body
        )
        value.artifacts.objects[key] = b"broken late page"
    before = value.store.writes
    with pytest.raises(BaseErrorCode):
        await app(value).arun_permissions(**value.input, operator_id=7)
    assert value.store.writes == before
    async with value.sessions() as session, session.begin():
        current = (
            await session.execute(
                sa.select(PermissionCatalogRelease).where(PermissionCatalogRelease.status == "CURRENT")
            )
        ).scalar_one()
        assert current.id == value.before.release.id


@pytest.mark.parametrize("after,cancel", [(False, False), (True, False), (True, True)])
async def test_unknown_actual_fga_write_stops_and_fresh_original_entry_recovers(published_input, after, cancel):
    value = published_input
    value.store.fail_write, value.store.after, value.store.cancel = 1, after, cancel
    import asyncio

    with pytest.raises(asyncio.CancelledError if cancel else BaseErrorCode):
        await app(value).arun_permissions(**value.input, operator_id=7)
    value.sessions.assert_closed()
    async with value.sessions() as session, session.begin():
        current = (
            await session.execute(
                sa.select(PermissionCatalogRelease).where(PermissionCatalogRelease.status == "CURRENT")
            )
        ).scalar_one()
        assert current.id == value.before.release.id
    value.store.fail_write = None
    assert (await app(value).arun_permissions(**value.input, operator_id=7)).complete
    value.sessions.assert_closed()

"""T681: native, read-only, bounded acquisition of original permission rows.

SQLite validates actual queries and sequential isolation, not MySQL locking.
No FGA/model publication, middleware or downtime probe is invoked.
"""

import importlib
from dataclasses import asdict
from math import ceil

import pytest
from sqlalchemy import event, update
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.errcode.permission import PermissionMigrationBlockedError
from bisheng.core.context.tenant import (
    bypass_tenant_filter,
    current_tenant_id,
    set_current_tenant_id,
    tenant_execution_scope,
)
from bisheng.core.database import tenant_filter
from bisheng.permission.domain.models import (
    AuthorizationModelRelease,
    PermissionAction,
    PermissionActionResourceScope,
    PermissionCatalogRelease,
    PermissionGrant,
    PermissionGrantAssignee,
    PermissionModel,
    PermissionModelAction,
    PermissionProjectionOperation,
    PermissionVisibleSourceProjection,
    ResourcePermissionMode,
)
from bisheng.permission.migration import f118_plan
from test.knowledge_unification.test_perm_migration import baseline, resource

TABLES = [
    AuthorizationModelRelease,
    PermissionCatalogRelease,
    PermissionAction,
    PermissionActionResourceScope,
    PermissionModel,
    PermissionModelAction,
    PermissionGrant,
    PermissionGrantAssignee,
    ResourcePermissionMode,
    PermissionProjectionOperation,
    PermissionVisibleSourceProjection,
]


@pytest.fixture
def snapshot_repo():
    return importlib.import_module(
        "bisheng.permission.domain.repositories.f118_migration_snapshot_repository"
    ).PermissionMigrationSnapshotRepository()


@pytest.fixture
async def storage(monkeypatch):
    names = {model.__tablename__ for model in TABLES if "tenant_id" in model.__table__.c}
    monkeypatch.setattr(tenant_filter, "_force_import_all_models", lambda: None)
    monkeypatch.setattr(tenant_filter, "_discover_tenant_aware_tables", lambda: names)
    monkeypatch.setattr(tenant_filter, "_tenant_aware_tables", tenant_filter._tenant_aware_tables | names)
    tenant_filter.register_tenant_filter_events()
    token = set_current_tenant_id(101)
    engine = create_async_engine("sqlite+aiosqlite://")
    try:
        async with engine.begin() as connection:
            await connection.run_sync(
                lambda conn: SQLModel.metadata.create_all(conn, tables=[model.__table__ for model in TABLES])
            )
        yield engine
    finally:
        current_tenant_id.reset(token)
        await engine.dispose()


async def seed_catalog(session, *, model_count=None):
    before = baseline(f118_plan)
    session.add(AuthorizationModelRelease(**asdict(before.authorization)))
    session.add(PermissionCatalogRelease(**asdict(before.release)))
    action_ids = {}
    scope_id = 1
    for index, action in enumerate(before.actions, 1):
        action_ids[action.code] = index
        values = asdict(action)
        types = values.pop("resource_types")
        session.add(PermissionAction(id=index, catalog_release_id=1, **values))
        for kind in sorted(types):
            session.add(PermissionActionResourceScope(id=scope_id, action_id=index, resource_type=kind))
            scope_id += 1
    relation_id = 1
    for model in before.models:
        values = asdict(model)
        codes = values.pop("selected_action_codes")
        del values["effective_action_codes"]
        values["visibility_only_resource_types"] = list(values["visibility_only_resource_types"])
        session.add(PermissionModel(catalog_release_id=1, **values))
        for code in codes:
            session.add(PermissionModelAction(id=relation_id, model_id=model.id, action_id=action_ids[code]))
            relation_id += 1
    for ident in range(len(before.models) + 1, (model_count or len(before.models)) + 1):
        session.add(
            PermissionModel(
                id=ident,
                catalog_release_id=1,
                model_key=f"custom-{ident}",
                name=f"Custom {ident}",
                normalized_name=f"custom {ident}",
                kind="CUSTOM",
                derived_level=1,
                active=ident % 2 == 0,
                visibility_only_resource_types=None,
                visibility_level=None,
                allow_same_level=False,
            )
        )
        session.add(PermissionModelAction(id=relation_id, model_id=ident, action_id=action_ids["use"]))
        relation_id += 1
    await session.flush()
    return before


async def seed_rows(session):
    original = resource(f118_plan)
    session.add(ResourcePermissionMode(**asdict(original.mode)))
    for grant in original.grants:
        session.add(PermissionGrant(**asdict(grant)))
    for source in original.assignees:
        session.add(PermissionGrantAssignee(**asdict(source)))
    for row in original.visible_sources:
        session.add(PermissionVisibleSourceProjection(id=row.id, **row.source.model_dump()))
    await session.flush()
    return original


async def pages(repo, method, session, *, limit=2):
    result, after = [], None
    while True:
        batch = await getattr(repo, method)(session, after_id=after, limit=limit)
        if not batch:
            return result
        assert len(batch) <= limit
        result.extend(batch)
        after = batch[-1].id


async def test_actual_old_use_catalog_and_authorization_pin_are_read_without_current_runtime_derivation(
    snapshot_repo, storage
):
    async with AsyncSession(storage) as session:
        before = await seed_catalog(session)
        observed = await snapshot_repo.aload_catalog_baseline(session, environment="test")
        assert observed.release == before.release and observed.authorization == before.authorization
        assert {action.code for action in observed.actions} == {action.code for action in before.actions}
        assert "use" in {action.code for action in observed.actions}
        for expected in before.models:
            actual = next(model for model in observed.models if model.model_key == expected.model_key)
            assert actual.id == expected.id and actual.active == expected.active
            assert set(actual.selected_action_codes) == set(expected.selected_action_codes)
            assert set(actual.effective_action_codes) == set(expected.effective_action_codes)
        plan = f118_plan.build_catalog_retirement_plan(
            run_id="formal-run", writer_contract_version="f118-v1", before=observed, target_model_checksum="f" * 64
        )
        assert "use" not in {action.code for action in plan.after_actions}


async def test_catalog_models_and_links_are_batched_beyond_the_old_5001_cap_without_cartesian_queries(
    snapshot_repo, storage
):
    async with AsyncSession(storage) as session:
        await seed_catalog(session, model_count=5003)
        statements = []
        event.listen(
            session.sync_session,
            "do_orm_execute",
            lambda state: statements.append(state.statement) if state.is_select else None,
        )
        observed = await snapshot_repo.aload_catalog_baseline(session, environment="test")
        assert len(observed.models) == 5003 and len({model.id for model in observed.models}) == 5003
        assert all("use" in model.selected_action_codes for model in observed.models)
        # One bounded model-range query and one link batch per <=200 models;
        # never issue a complete catalog query for every model/assignee.
        assert len(statements) <= 2 * ceil(5003 / 200) + 10
        model_scans = [query for query in statements if str(query).startswith("SELECT permission_model.id,")]
        assert model_scans and all(query._limit_clause is not None for query in model_scans)


async def test_four_actual_pk_pages_keep_inactive_and_retired_rows_and_original_source_identity(snapshot_repo, storage):
    async with AsyncSession(storage) as session:
        original = await seed_rows(session)
        session.add(
            PermissionGrant(
                id=12,
                tenant_id=101,
                resource_type="knowledge_space",
                resource_id="40",
                model_key="inactive-use",
                state="INACTIVE",
                projection_state="CURRENT",
            )
        )
        old = original.visible_sources[0].source.model_dump()
        old.update(contribution_fingerprint="e" * 64, state="RETIRED")
        session.add(PermissionVisibleSourceProjection(id=9, **old))
        await session.flush()
        grants = await pages(snapshot_repo, "alist_grants", session)
        sources = await pages(snapshot_repo, "alist_assignees", session)
        modes = await pages(snapshot_repo, "alist_resource_modes", session)
        visible = await pages(snapshot_repo, "alist_visible_sources", session)
        assert [row.id for row in grants] == [11, 12] and {row.state for row in grants} == {"ACTIVE", "INACTIVE"}
        assert tuple(sources) == original.assignees and len(modes) == 1
        assert {row.source.state for row in visible} == {"ACTIVE", "RETIRED"}
        assert visible[-1].id == 9
        assert sources[1].protected and sources[0].source_fingerprint == original.assignees[0].source_fingerprint


@pytest.mark.parametrize("broken", ["missing_grant", "foreign_grant"])
async def test_actual_assignee_parent_chain_is_not_hidden_by_a_join_or_tenant_filter(snapshot_repo, storage, broken):
    async with AsyncSession(storage) as session:
        original = await seed_rows(session)
        parent = 404
        if broken == "foreign_grant":
            parent = 202
            with tenant_execution_scope(202):
                session.add(
                    PermissionGrant(
                        id=parent,
                        tenant_id=202,
                        resource_type="tool",
                        resource_id="foreign",
                        model_key="viewer",
                        state="ACTIVE",
                        projection_state="CURRENT",
                    )
                )
                await session.flush()
        await session.execute(
            update(PermissionGrantAssignee)
            .where(PermissionGrantAssignee.tenant_id == 101, PermissionGrantAssignee.id == original.assignees[0].id)
            .values(grant_id=parent)
        )
        with pytest.raises(PermissionMigrationBlockedError):
            await snapshot_repo.alist_assignees(session)


async def test_foreign_tenant_rows_are_not_adopted_by_any_of_the_four_pagers(snapshot_repo, storage):
    async with AsyncSession(storage) as session:
        await seed_rows(session)
        await session.commit()
        with tenant_execution_scope(202):
            for name in ("alist_grants", "alist_assignees", "alist_resource_modes", "alist_visible_sources"):
                assert await getattr(snapshot_repo, name)(session) == ()


async def test_every_read_preserves_pending_owner_writes_and_rejects_bypass_or_missing_tenant(snapshot_repo, storage):
    async with AsyncSession(storage) as session:
        await seed_catalog(session)
        await session.commit()
        pending = PermissionGrant(
            tenant_id=None, resource_type="tool", resource_id="pending", model_key="viewer", state="ACTIVE"
        )
        session.add(pending)
        flushes = []
        event.listen(session.sync_session, "before_flush", lambda *args: flushes.append(True))
        methods = [lambda: snapshot_repo.aload_catalog_baseline(session, environment="test")]
        methods.extend(
            lambda name=name: getattr(snapshot_repo, name)(session)
            for name in ("alist_grants", "alist_assignees", "alist_resource_modes", "alist_visible_sources")
        )
        for method in methods:
            await method()
            assert pending in session.new and pending.tenant_id is None and not flushes
            with bypass_tenant_filter(), pytest.raises(PermissionMigrationBlockedError):
                await method()
        token = set_current_tenant_id(None)
        try:
            with pytest.raises(PermissionMigrationBlockedError):
                await snapshot_repo.alist_grants(session)
        finally:
            current_tenant_id.reset(token)


@pytest.mark.parametrize("limit,after", [(0, None), (201, None), (True, None), (10, -1), (10, True), (10, "1")])
async def test_seek_bounds_are_checked_before_sql(snapshot_repo, storage, limit, after):
    async with AsyncSession(storage) as session:
        for name in ("alist_grants", "alist_assignees", "alist_resource_modes", "alist_visible_sources"):
            with pytest.raises((ValueError, PermissionMigrationBlockedError)):
                await getattr(snapshot_repo, name)(session, limit=limit, after_id=after)


@pytest.mark.parametrize(
    "change", ["environment", "auth_missing", "auth_inactive", "action_parent", "duplicate_current"]
)
async def test_catalog_pin_and_cross_release_model_action_parent_fail_closed(snapshot_repo, storage, change):
    async with AsyncSession(storage) as session:
        await seed_catalog(session)
        if change == "auth_missing":
            await session.execute(update(PermissionCatalogRelease).values(required_authorization_model_release_id=404))
        elif change == "auth_inactive":
            await session.execute(update(AuthorizationModelRelease).values(status="RETIRED"))
        elif change == "action_parent":
            await session.execute(
                update(PermissionModelAction).where(PermissionModelAction.id == 1).values(action_id=404)
            )
        elif change == "duplicate_current":
            session.add(
                PermissionCatalogRelease(
                    id=2,
                    release_key="another",
                    version=2,
                    checksum="d" * 64,
                    required_authorization_model_release_id=10,
                    draft_owner_id=7,
                    idempotency_key="another",
                    status="CURRENT",
                )
            )
            await session.flush()
        with pytest.raises(PermissionMigrationBlockedError):
            await snapshot_repo.aload_catalog_baseline(
                session, environment="other" if change == "environment" else "test"
            )

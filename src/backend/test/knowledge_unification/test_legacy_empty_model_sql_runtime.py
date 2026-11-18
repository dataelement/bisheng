"""Actual SQL roster and CURRENT readers retain only evidenced empty sources."""

from contextlib import asynccontextmanager
from dataclasses import asdict, replace
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import update
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.errcode.permission import PermissionPublishNotReadyError
from bisheng.permission.application import control_state
from bisheng.permission.application.runtime import F048PermissionRuntime
from bisheng.permission.domain.models import (
    AuthorizationModelRelease,
    PermissionAction,
    PermissionActionResourceScope,
    PermissionCatalogRelease,
    PermissionGrant,
    PermissionGrantAssignee,
    PermissionModel,
    PermissionModelAction,
    PermissionVisibleSourceProjection,
    ResourcePermissionMode,
)
from bisheng.permission.domain.repositories.grant_repository import GrantRepository, ResourcePermissionModeRepository
from bisheng.permission.domain.schemas import VerifiedPermissionTarget
from bisheng.permission.domain.services.visibility_projection_service import VisibilityProjectionCompiler
from bisheng.permission.migration import f118_plan as plans
from test.knowledge_unification.test_legacy_empty_model_compat import catalog, original_resource
from test.knowledge_unification.test_perm_migration import after_catalog
from test.knowledge_unification.test_perm_migration_snapshot import storage as storage


@pytest.fixture
async def prepared(storage, monkeypatch):
    @asynccontextmanager
    async def sessions():
        async with AsyncSession(storage, expire_on_commit=False) as session:
            yield session

    original, grant = original_resource()
    plan = plans.build_catalog_retirement_plan(
        run_id="legacy-empty", writer_contract_version="f118-v1", before=catalog(), target_model_checksum="f" * 64
    )
    current = after_catalog(plan)
    async with sessions() as session, session.begin():
        session.add(AuthorizationModelRelease(**asdict(current.authorization)))
        session.add(PermissionCatalogRelease(**asdict(current.release)))
        action_ids = {}
        for ident, action in enumerate(current.actions, 1):
            values = asdict(action)
            scopes = values.pop("resource_types")
            session.add(PermissionAction(id=ident, catalog_release_id=current.release.id, **values))
            action_ids[action.code] = ident
            for offset, scope in enumerate(sorted(scopes), 1):
                session.add(
                    PermissionActionResourceScope(id=ident * 100 + offset, action_id=ident, resource_type=scope)
                )
        link = 1
        for model in current.models:
            values = asdict(model)
            selected = values.pop("selected_action_codes")
            values.pop("effective_action_codes")
            session.add(PermissionModel(catalog_release_id=current.release.id, **values))
            for code in selected:
                session.add(PermissionModelAction(id=link, model_id=model.id, action_id=action_ids[code]))
                link += 1
        session.add(ResourcePermissionMode(**asdict(original.mode)))
        session.add(PermissionGrant(**asdict(original.grants[0])))
        for source in original.assignees:
            session.add(PermissionGrantAssignee(**asdict(source)))
        for source in original.visible_sources:
            session.add(PermissionVisibleSourceProjection(id=source.id, **source.source.model_dump()))
    monkeypatch.setattr(control_state, "get_async_db_session", sessions)
    monkeypatch.setattr(control_state, "GrantRepository", lambda: GrantRepository(session_factory=sessions))
    monkeypatch.setattr(
        control_state,
        "ResourcePermissionModeRepository",
        lambda: ResourcePermissionModeRepository(session_factory=sessions),
    )
    target = VerifiedPermissionTarget.from_business_service(
        tenant_id=101, resource_type="channel", resource_id="channel-1", resource_version=1, context_version="test"
    )
    return sessions, target, grant


async def test_current_catalog_round_trips_without_guessing_a_tier(prepared):
    _, _, grant = prepared
    current = await control_state.SqlPermissionControlState().current_catalog()
    model = next(row.snapshot for row in current.models if row.snapshot.model_key == "legacy-empty")
    assert model == grant.model
    assert model.derived_level is model.visibility_level is None


async def test_actual_source_cursor_preserves_existing_empty_sources(prepared):
    _, target, grant = prepared
    state = control_state.SqlPermissionControlState()
    first, more = await state.load_source_page(target=target, mode="CUSTOM", models=(grant.model,), after_id=0, limit=1)
    second, ended = await state.load_source_page(
        target=target, mode="CUSTOM", models=(grant.model,), after_id=first[0].source_id, limit=1
    )
    assert more and not ended
    assert [first[0].source_id, second[0].source_id] == [101, 102]
    assert first[0].model_level is second[0].model_level is None


async def test_inherited_empty_source_requires_the_ancestors_own_evidence(prepared):
    sessions, _, grant = prepared
    inherited = replace(grant, resource_type="folder", resource_id="55")
    async with sessions() as session, session.begin():
        await session.execute(
            update(ResourcePermissionMode)
            .where(ResourcePermissionMode.id == 7)
            .values(
                resource_type="knowledge_file",
                resource_id="44",
                mode="INHERIT",
                parent_type="folder",
                parent_id="55",
            )
        )
        session.add(
            ResourcePermissionMode(
                id=8,
                tenant_id=101,
                resource_type="folder",
                resource_id="55",
                mode="CUSTOM",
                version=1,
                projection_state="CURRENT",
            )
        )
        await session.execute(
            update(PermissionGrant).where(PermissionGrant.id == 11).values(resource_type="folder", resource_id="55")
        )
        for ident, source in enumerate(grant.sources, 1):
            proof = VisibilityProjectionCompiler._compile_source(101, inherited, source)
            await session.execute(
                update(PermissionVisibleSourceProjection)
                .where(PermissionVisibleSourceProjection.id == ident)
                .values(
                    resource_type="folder",
                    resource_id="55",
                    tuple_fingerprint=proof.tuple_fingerprint,
                )
            )
    target = VerifiedPermissionTarget.from_business_service(
        tenant_id=101,
        resource_type="knowledge_file",
        resource_id="44",
        resource_version=1,
        context_version="test",
        parent_type="folder",
        parent_id="55",
    )
    rows, more = await control_state.SqlPermissionControlState().load_source_page(
        target=target, mode="INHERIT", models=(grant.model,), after_id=0, limit=10
    )
    assert not more and len(rows) == 1
    assert rows[0].source_id == 101 and rows[0].scope == "INHERITED" and rows[0].inherited_from == "folder:55"


@pytest.mark.parametrize(
    "change",
    [
        {"state": "RETIRED"},
        {"source_version": 2},
        {"tuple_fingerprint": "0" * 64},
        {"projected_subject": "user:other"},
        {"resource_id": "other"},
    ],
)
async def test_sql_roster_fails_closed_for_missing_or_changed_visibility_proof(prepared, change):
    sessions, target, grant = prepared
    async with sessions() as session, session.begin():
        await session.execute(
            update(PermissionVisibleSourceProjection).where(PermissionVisibleSourceProjection.id == 1).values(**change)
        )
    with pytest.raises(PermissionPublishNotReadyError) as caught:
        await control_state.SqlPermissionControlState().load_source_page(
            target=target, mode="CUSTOM", models=(grant.model,), after_id=0, limit=1
        )
    assert caught.value.kwargs["reason"] == "legacy_visibility_source_unavailable"


async def test_effective_visibility_summary_includes_preserved_sources_only_for_visible(prepared):
    _, target, _ = prepared
    state = control_state.SqlPermissionControlState()
    current = await state.current_catalog()
    runtime = object.__new__(F048PermissionRuntime)
    runtime._state = state
    runtime._runtime_catalog = AsyncMock(return_value=current)
    runtime._require_current_target = AsyncMock(return_value=SimpleNamespace(mode="CUSTOM"))
    visible = await runtime.read_effective_action_sources(target=target, action="visible")
    assert {row.source_id for row in visible} == {101, 102}
    assert await runtime.read_effective_action_sources(target=target, action="edit") == ()

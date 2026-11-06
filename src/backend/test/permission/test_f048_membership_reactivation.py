"""Exercise membership reactivation through real SQL state and projection finalizers."""

from dataclasses import asdict, replace
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlmodel import select

from bisheng.common.errcode.permission import PermissionVersionConflictError
from bisheng.permission.application import control_state
from bisheng.permission.application.control_state import SqlGrantMutationState, SqlPermissionControlState
from bisheng.permission.application.runtime import F048PermissionRuntime
from bisheng.permission.application.sql_runtime import SqlProjectionFinalizer, SqlProjectionScopeGuard
from bisheng.permission.domain.models import (
    PermissionGrant,
    PermissionGrantAssignee,
    PermissionVisibleSourceProjection,
    ResourcePermissionMode,
)
from bisheng.permission.domain.repositories.projection_repository import ProjectionRepository
from bisheng.permission.domain.schemas import VerifiedPermissionTarget
from bisheng.permission.domain.services.grant_service import GrantService
from bisheng.permission.domain.services.grant_source_service import (
    GrantModelSnapshot,
    GrantSnapshot,
    GrantSourceService,
)
from bisheng.permission.domain.services.permission_action_service import PermissionActor
from bisheng.permission.domain.services.projection_service import ProjectionService
from bisheng.permission.domain.services.visibility_projection_service import VisibilityProjectionCompiler
from test.permission.test_f048_projection_service import FakeFGAProjection, FakeRecentMarker
from test.permission.test_f048_projection_sql_runtime import session_factory as session_factory
from test.permission.test_f048_projection_sql_runtime import tenant_context as tenant_context


@pytest.mark.parametrize(
    "model_path", [("viewer", None, "viewer", None, "viewer", None), ("viewer", "manager", None, "viewer", None)]
)
@pytest.mark.parametrize(
    "resource_type,source_type", [("knowledge_space", "SPACE_MEMBERSHIP"), ("channel", "CHANNEL_MEMBERSHIP")]
)
async def test_join_leave_rejoin_keeps_versions_and_removes_visibility(
    session_factory, monkeypatch, resource_type, source_type, model_path
):
    monkeypatch.setattr(control_state, "get_async_db_session", session_factory)
    state = SqlPermissionControlState()
    # Catalog publication and Redis are outside this regression; SQL grants,
    # reservation, tuple ledger and both finalizers use production code.
    monkeypatch.setattr(state, "_assert_catalog_writable", AsyncMock())
    owner_visible = ("user:9", "visible", f"{resource_type}:42")
    member_visible = ("user:11", "visible", f"{resource_type}:42")
    fga = FakeFGAProjection({owner_visible})
    projection = ProjectionService(
        repository=ProjectionRepository(session_factory),
        marker=FakeRecentMarker(),
        scope_guard=SqlProjectionScopeGuard(),
        fga=fga,
        finalizer=SqlProjectionFinalizer(),
    )
    sources = GrantSourceService()
    runtime = object.__new__(F048PermissionRuntime)
    runtime._state = state
    runtime._grants = GrantService(source_service=sources, projection=projection, state=SqlGrantMutationState(state))
    viewer = GrantModelSnapshot(model_key="viewer", active=True, action_codes=("visible", "use"), derived_level=1)
    manager = replace(viewer, model_key="manager", derived_level=3)
    owner_model = replace(viewer, model_key="owner", derived_level=4)
    runtime._runtime_catalog = AsyncMock(
        return_value=SimpleNamespace(
            release_id=1,
            store_id="store",
            model_id="model",
            models=(
                SimpleNamespace(snapshot=viewer),
                SimpleNamespace(snapshot=manager),
                SimpleNamespace(snapshot=owner_model),
            ),
        )
    )
    runtime._grant_capabilities = AsyncMock(return_value=())
    actor = PermissionActor(user_id=11, current_tenant_id=7)
    async with session_factory() as session:
        async with session.begin():
            session.add(
                ResourcePermissionMode(
                    tenant_id=7,
                    resource_type=resource_type,
                    resource_id="42",
                    mode="CUSTOM",
                    version=1,
                    projection_state="CURRENT",
                )
            )

    owner = sources.canonicalize_source(
        source_id=102,
        subject_type="user",
        subject_id="9",
        source_type="CREATOR",
        source_ref=f"{resource_type}:42",
        protected=True,
    )
    async with session_factory() as session:
        async with session.begin():
            owner_grant = PermissionGrant(
                tenant_id=7,
                resource_type=resource_type,
                resource_id="42",
                model_key="owner",
                state="ACTIVE",
                projection_state="CURRENT",
            )
            session.add(owner_grant)
            await session.flush()
            await state._upsert_assignee(session, grant_row=owner_grant, source=owner, state="ACTIVE")
            snapshot = GrantSnapshot(
                grant_id="owner",
                tenant_id=7,
                resource_type=resource_type,
                resource_id="42",
                model=owner_model,
                active=True,
                sources=(owner,),
            )
            contribution = (
                VisibilityProjectionCompiler()
                .compile(tenant_id=7, grants=(snapshot,), existing_sources=())
                .active_sources[0]
            )
            session.add(PermissionVisibleSourceProjection(**contribution.model_dump()))

    source = sources.canonicalize_source(
        source_id=1, subject_type="user", subject_id="11", source_type=source_type, source_ref="42:user:11"
    )

    async def target():
        async with session_factory() as session:
            row = (await session.exec(select(ResourcePermissionMode))).one()
        return VerifiedPermissionTarget.from_business_service(
            tenant_id=7,
            resource_type=resource_type,
            resource_id="42",
            resource_version=row.version,
            context_version=f"ctx-{row.version}",
        )

    stable_id = None
    for index, model_key in enumerate(model_path):
        result = await runtime.sync_business_source_model(
            actor=actor,
            target=await target(),
            source=source,
            model_key=model_key,
            idempotency_key=f"membership-{index}",
        )
        assert result is not None
        async with session_factory() as session:
            assignee = (
                await session.exec(select(PermissionGrantAssignee).where(PermissionGrantAssignee.subject_id == "11"))
            ).one()
            visible = list(
                (
                    await session.exec(
                        select(PermissionVisibleSourceProjection).where(
                            PermissionVisibleSourceProjection.projected_subject == "user:11"
                        )
                    )
                ).all()
            )
            assert assignee.version == index + 1
            stable_id = stable_id or assignee.id
            assert assignee.id == stable_id
            if model_key is None:
                assert assignee.state == "INACTIVE"
                assert all(row.state == "RETIRED" for row in visible)
            else:
                assert assignee.state == "ACTIVE"
                active = [row for row in visible if row.state == "ACTIVE"]
                assert len(active) == 1
                assert active[0].model_key == model_key
                assert active[0].source_version == assignee.version
        assert (member_visible in fga.present) == (model_key is not None)
        assert owner_visible in fga.present
        async with session_factory() as session:
            creator = await session.get(PermissionGrantAssignee, owner.source_id)
            assert creator.state == "ACTIVE" and creator.version == 1
        calls = len(fga.calls)
        assert (
            await runtime.sync_business_source_model(
                actor=actor,
                target=await target(),
                source=source,
                model_key=model_key,
                idempotency_key=f"repeat-{index}",
            )
            is None
        )
        assert len(fga.calls) == calls


@pytest.mark.parametrize("source_version,accepted", [(1, False), (2, False), (3, True), (4, False)])
async def test_inactive_assignee_requires_next_version_before_projection(session_factory, source_version, accepted):
    source = GrantSourceService().canonicalize_source(
        source_id=101, subject_type="user", subject_id="11", source_type="SPACE_MEMBERSHIP", source_ref="42:user:11"
    )
    async with session_factory() as session:
        async with session.begin():
            grant = PermissionGrant(
                tenant_id=7,
                resource_type="knowledge_space",
                resource_id="42",
                model_key="viewer",
                state="INACTIVE",
                projection_state="CURRENT",
            )
            session.add(grant)
            await session.flush()
            row = PermissionGrantAssignee(
                tenant_id=7,
                grant_id=grant.id,
                state="INACTIVE",
                **{
                    key: value for key, value in asdict(source).items() if key not in {"source_id", "active", "version"}
                },
                id=101,
                version=2,
            )
            session.add(row)
            await session.flush()
            if accepted:
                restored = await state_upsert(session, grant, replace(source, version=source_version))
                assert restored.version == 3
            else:
                with pytest.raises(PermissionVersionConflictError):
                    await state_upsert(session, grant, replace(source, version=source_version))
                assert row.version == 2 and row.state == "INACTIVE"


async def state_upsert(session, grant, source):
    return await SqlPermissionControlState._upsert_assignee(session, grant_row=grant, source=source, state="PENDING")

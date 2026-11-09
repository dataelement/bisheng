"""Legacy knowledge contracts use actual C3 type and the real F048 decision pipeline."""

from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import StaticPool
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.api.services.f048_permission_runtime import build_f048_resource_composition
from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.core.context.tenant import current_tenant_id, set_current_tenant_id
from bisheng.knowledge.domain.knowledge_rag import KnowledgeRag
from bisheng.knowledge.domain.models import knowledge as models
from bisheng.knowledge.domain.models.knowledge import Knowledge
from bisheng.knowledge.domain.services.knowledge_permission_service import KnowledgePermissionService
from bisheng.permission.application import business_authorization as auth
from bisheng.permission.application.identity import current_permission_actor, set_current_permission_actor
from bisheng.permission.application.runtime import F048PermissionRuntime
from bisheng.permission.domain.models import ResourcePermissionMode
from bisheng.permission.domain.services import data_scope as scopes
from bisheng.permission.domain.services.data_scope import DATA_SCOPE_PERSONAL
from bisheng.permission.domain.services.permission_action_service import PermissionActor
from test.permission.test_data_scope_enforcement import FakeResolver, StubFGA, service


@pytest.fixture
async def real_targets(monkeypatch):
    token = set_current_tenant_id(101)
    engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool)
    async with engine.begin() as connection:
        await connection.run_sync(lambda conn: Knowledge.__table__.create(conn))
        await connection.run_sync(lambda conn: ResourcePermissionMode.__table__.create(conn))

    @asynccontextmanager
    async def sessions():
        async with AsyncSession(engine, expire_on_commit=False) as session:
            yield session

    async with sessions() as session:
        session.add_all(
            [
                Knowledge(id=i, tenant_id=101, type=kind, state=1, user_id=7, name=str(kind), model="11")
                for i, kind in ((11, 0), (12, 1), (13, 3), (14, 2))
            ]
        )
        session.add(Knowledge(id=15, tenant_id=202, type=3, state=1, user_id=7, name="foreign", model="11"))
        session.add_all(
            [
                ResourcePermissionMode(
                    id=i,
                    tenant_id=101,
                    resource_type=kind,
                    resource_id=str(i),
                    mode="CUSTOM",
                    version=1,
                    projection_state="CURRENT",
                )
                for i, kind in ((11, "knowledge_library"), (12, "knowledge_library"), (13, "knowledge_space"))
            ]
        )
        await session.commit()
    monkeypatch.setattr(models, "get_async_db_session", sessions)
    fga = StubFGA()
    decision = service(fga)

    async def version(**kwargs):
        async with sessions() as session:
            row = (
                await session.exec(
                    select(ResourcePermissionMode).where(
                        ResourcePermissionMode.tenant_id == kwargs["tenant_id"],
                        ResourcePermissionMode.resource_type == kwargs["resource_type"],
                        ResourcePermissionMode.resource_id == kwargs["resource_id"],
                    )
                )
            ).one()
            return row.version, "actual-mode-" + str(row.id)

    runtime = F048PermissionRuntime(
        client=SimpleNamespace(),
        state=SimpleNamespace(permission_version=version),
        marker=None,
        decision=decision,
        projection=None,
        sources=None,
        owner=None,
        grants=None,
        modes=None,
        explain=None,
    )
    adapters, registry = build_f048_resource_composition(runtime)

    async def get_registry():
        return registry

    async def get_runtime():
        return runtime

    monkeypatch.setattr(auth, "get_f048_resource_registry", get_registry)
    monkeypatch.setattr(auth, "get_f048_runtime", get_runtime)
    actor = PermissionActor(user_id=7, tenant_id=101)
    actor_token = set_current_permission_actor(actor)
    try:
        yield SimpleNamespace(
            user=UserPayload(user_id=7, tenant_id=101, user_role=[]), fga=fga, adapters=adapters, actor=actor
        )
    finally:
        current_permission_actor.reset(actor_token)
        await engine.dispose()
        current_tenant_id.reset(token)


async def test_mixed_actual_types_use_original_namespace_without_dropping_spaces(real_targets):
    c = real_targets
    result = await KnowledgePermissionService.get_knowledge_action_map_async(c.user, [11, 12, 13], ["visible"])
    assert result == {11: {"visible"}, 12: {"visible"}, 13: {"visible"}}
    objects = [item["object"] for kind, items in c.fga.calls if kind == "batch" for item in items]
    assert any("knowledge_space:13" in item for item in objects)
    assert all("knowledge_library:13" not in item for item in objects)


async def test_single_space_visible_and_rag_use_the_actual_adapter(real_targets):
    c = real_targets
    assert await KnowledgePermissionService.check_action_async(c.user, 13, "visible")
    assert await KnowledgeRag.afilter_usable_knowledge_ids(c.user, [11, 12, 13]) == {11, 12, 13}


async def test_legacy_use_output_key_is_retained_but_runtime_decision_is_visible(real_targets):
    result = await KnowledgePermissionService.get_knowledge_action_map_async(real_targets.user, [13], ["use"])
    assert result == {13: {"use"}}
    assert all(item["relation"] != "use" for kind, items in real_targets.fga.calls if kind == "batch" for item in items)


async def test_actual_typed_actor_and_personal_scope_survive_type_partition(real_targets, monkeypatch):
    c = real_targets
    monkeypatch.setattr(scopes, "_resolver", FakeResolver({"knowledge_library": {"12"}, "knowledge_space": {"13"}}))
    actor = PermissionActor(user_id=7, tenant_id=101, data_scope=DATA_SCOPE_PERSONAL)
    token = set_current_permission_actor(actor)
    try:
        result = await KnowledgePermissionService.get_knowledge_action_map_async(c.user, [11, 12, 13], ["visible"])
        assert result == {11: set(), 12: {"visible"}, 13: {"visible"}}
    finally:
        current_permission_actor.reset(token)


async def test_foreign_missing_and_retired_type_never_get_an_admin_fallback(real_targets):
    # Even the business-loader stage must reject a foreign row before the facade.
    loader = real_targets.adapters["knowledge_library"]._loader
    assert await loader.load_permission_record("knowledge_library", "13") is None
    assert await KnowledgePermissionService.get_knowledge_action_map_async(
        real_targets.user, [14, 15, 999], ["visible"]
    ) == {14: set(), 15: set(), 999: set()}

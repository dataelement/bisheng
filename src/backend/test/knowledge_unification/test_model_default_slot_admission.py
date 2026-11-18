"""F025 native sync/async slot admission preserves the full source guard."""

import json

import pytest
from sqlalchemy import update
from sqlmodel import Session

from bisheng.common.errcode.knowledge import ReferenceCoverageNotReadyError, ResourceReferenceInvalidError
from bisheng.llm.domain.models.llm_server import LLMModel
from bisheng.resource_reference.domain.models.business_reference_set import BusinessReferenceSet
from test.knowledge_unification import test_llm_default_read as reading
from test.knowledge_unification import test_model_default_native_target as native

reads = reading.reads
model_owner_tenant = reading.model_owner_tenant


async def admit(reads, native_sync, key, slots):
    if native_sync:
        return reads.facade.require_default_projection(key, slots)
    return await reads.facade.arequire_default_projection(key, slots)


@pytest.mark.parametrize("native_sync", [True, False])
async def test_same_model_in_multiple_slots_checks_only_selected_type_and_redacts_others(reads, native_sync):
    with Session(reads.engine) as session, session.begin():
        native.seed_default(
            session,
            key="knowledge_llm",
            payload={"source_model_id": 11, "embedding_model_id": 11, "abstract_prompt": "keep"},
        )
    value = await admit(reads, native_sync, "knowledge_llm", ("source_model_id",))
    payload = json.loads(value.payload_json)
    assert payload["source_model_id"] == 11 and payload["embedding_model_id"] is None
    assert payload["abstract_prompt"] == "keep"
    with pytest.raises(ResourceReferenceInvalidError):
        await admit(reads, native_sync, "knowledge_llm", ("embedding_model_id",))
    with pytest.raises(ResourceReferenceInvalidError):
        if native_sync:
            reads.facade.require_default("knowledge_llm")
        else:
            await reads.facade.arequire_default("knowledge_llm")


@pytest.mark.parametrize("native_sync", [True, False])
@pytest.mark.parametrize(
    "field,value,error",
    [
        ("digest", "bad-digest", ReferenceCoverageNotReadyError),
        ("ready", False, ReferenceCoverageNotReadyError),
        ("effective", False, ResourceReferenceInvalidError),
        ("extractor_version", "wrong", ReferenceCoverageNotReadyError),
        ("source_revision", 7, ReferenceCoverageNotReadyError),
    ],
)
async def test_complete_source_guard_still_fails_selected_good_slot(reads, native_sync, field, value, error):
    with Session(reads.engine) as session, session.begin():
        native.seed_default(session, key="knowledge_llm", payload={"source_model_id": 11, "embedding_model_id": 22})
        session.execute(
            update(BusinessReferenceSet)
            .where(
                BusinessReferenceSet.tenant_id == 101,
                BusinessReferenceSet.source_id == "knowledge_llm",
                BusinessReferenceSet.source_version == "current",
            )
            .values(**{field: value})
        )
    with pytest.raises(error):
        await admit(reads, native_sync, "knowledge_llm", ("source_model_id",))


@pytest.mark.parametrize("native_sync", [True, False])
async def test_missing_known_slot_is_empty_unknown_slot_is_denied(reads, native_sync):
    with Session(reads.engine) as session, session.begin():
        native.seed_default(session, key="knowledge_llm", payload={"source_model_id": 11})
    value = await admit(reads, native_sync, "knowledge_llm", ("asr_model_id",))
    assert all(
        reference is None for name, reference in json.loads(value.payload_json).items() if name.endswith("model_id")
    )
    with pytest.raises(ResourceReferenceInvalidError):
        await admit(reads, native_sync, "knowledge_llm", ("invented_model_id",))


@pytest.mark.parametrize("native_sync", [True, False])
async def test_inherited_root_owner_does_not_authorize_child_and_revocation_is_fresh(reads, native_sync):
    class Sharing:
        allowed = frozenset({2})

        def get_shared_server_ids(self, session, tenant_id, server_ids):
            assert tenant_id == 101 and server_ids == (2,)
            return self.allowed

        async def aget_shared_server_ids(self, session, tenant_id, server_ids):
            return self.get_shared_server_ids(session, tenant_id, server_ids)

    sharing = Sharing()
    reads.core.target_owners[next(iter(reads.core.target_owners))].sharing = sharing
    with Session(reads.engine) as session, session.begin():
        native.seed_default(session, tenant_id=1, payload={"model_id": 22})
    value = await admit(reads, native_sync, "evaluation_llm", ("model_id",))
    assert json.loads(value.payload_json)["model_id"] == 22
    sharing.allowed = frozenset()
    with pytest.raises(ResourceReferenceInvalidError):
        await admit(reads, native_sync, "evaluation_llm", ("model_id",))


@pytest.mark.parametrize("native_sync", [True, False])
async def test_offline_selected_slot_fails_without_blocking_other_slot(reads, native_sync):
    with Session(reads.engine) as session, session.begin():
        native.seed_default(session, key="knowledge_llm", payload={"source_model_id": 11, "extract_title_model_id": 22})
        session.execute(update(LLMModel).where(LLMModel.id == 22).values(online=False))
    await admit(reads, native_sync, "knowledge_llm", ("source_model_id",))
    with pytest.raises(ResourceReferenceInvalidError):
        await admit(reads, native_sync, "knowledge_llm", ("extract_title_model_id",))


async def test_native_management_http_keeps_invalid_inheritance_but_candidate_excludes_it(reads, monkeypatch):
    from contextlib import asynccontextmanager

    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient
    from sqlmodel import select
    from sqlmodel.ext.asyncio.session import AsyncSession

    from bisheng.common.dependencies.user_deps import UserPayload
    from bisheng.core.context.tenant import bypass_tenant_filter
    from bisheng.llm.api.router import router
    from bisheng.llm.application import model_default_read, system_model_settings
    from bisheng.llm.domain.models.llm_server import LLMDao, LLMServer
    from bisheng.llm.domain.services.llm import LLMService
    from bisheng.permission.application.identity import (
        PermissionActor,
        reset_current_permission_actor,
        set_current_permission_actor,
    )

    class NoShare:
        def get_shared_server_ids(self, session, tenant_id, server_ids):
            assert tenant_id == 101
            return frozenset()

        async def aget_shared_server_ids(self, session, tenant_id, server_ids):
            return self.get_shared_server_ids(session, tenant_id, server_ids)

    @asynccontextmanager
    async def source_session():
        async with AsyncSession(reads.async_engine) as session:
            yield session

    async def read_models(ids):
        async with AsyncSession(reads.async_engine) as session:
            with bypass_tenant_filter():
                return list((await session.execute(select(LLMModel).where(LLMModel.id.in_(ids)))).scalars())

    async def read_servers(ids):
        async with AsyncSession(reads.async_engine) as session:
            with bypass_tenant_filter():
                return list((await session.execute(select(LLMServer).where(LLMServer.id.in_(ids)))).scalars())

    async def shared(tenant_id, **kwargs):
        assert tenant_id == 101
        return []

    reads.core.target_owners[next(iter(reads.core.target_owners))].sharing = NoShare()
    monkeypatch.setattr(model_default_read, "_runtime", reads.facade)
    monkeypatch.setattr(system_model_settings, "get_async_db_session", source_session)
    monkeypatch.setattr(LLMDao, "aget_model_by_ids", read_models)
    monkeypatch.setattr(LLMDao, "aget_server_by_ids", read_servers)
    monkeypatch.setattr(LLMDao, "aget_shared_server_ids_for_leaf", shared)
    with Session(reads.engine) as session, session.begin():
        native.seed_default(
            session,
            tenant_id=1,
            key="linsight_llm",
            payload={"models": [{"id": "22", "name": "root original"}], "chat_default_model_id": "22"},
        )
    user = UserPayload(user_id=7, user_name="child-admin", tenant_id=101, user_role=[])
    actor = PermissionActor(user_id=7, current_tenant_id=101, tenant_admin_tenant_ids=frozenset({101}))
    token = set_current_permission_actor(actor)
    try:
        app = FastAPI()
        app.include_router(router)
        app.dependency_overrides[UserPayload.get_tenant_admin_user] = lambda: user
        async with AsyncClient(transport=ASGITransport(app), base_url="http://native") as client:
            response = await client.get("/llm/system-settings")
        assert response.status_code == 200
        result = response.json()["data"]
        section = next(section for section in result["sections"] if section["key"] == "linsight_llm")
        assert section["inherited_from_root"]
        assert {reference["model_id"] for reference in section["references"]} == {22}
        assert {reference["status"] for reference in section["references"]} == {"not_shared"}
        candidates = await LLMService.get_workbench_llm_candidates(login_user=user)
        assert candidates.models == [] and candidates.chat_default_model_id is None
    finally:
        reset_current_permission_actor(token)


@pytest.mark.parametrize("native_sync", [True, False])
async def test_selected_foreign_child_model_is_not_authorized_by_source_owner(reads, native_sync):
    with Session(reads.engine) as session, session.begin():
        native.seed_default(session, key="knowledge_llm", payload={"source_model_id": 33, "extract_title_model_id": 11})
    await admit(reads, native_sync, "knowledge_llm", ("extract_title_model_id",))
    with pytest.raises(ResourceReferenceInvalidError):
        await admit(reads, native_sync, "knowledge_llm", ("source_model_id",))

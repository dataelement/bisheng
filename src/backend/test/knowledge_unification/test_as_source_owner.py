"""T362: actual assistant/source/token reads share the caller's SQL transaction."""

import json
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import insert, update
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.assistant.application import reference_source_owner as owner_module
from bisheng.assistant.application.reference_source_owner import AssistantReferenceSourceOwner
from bisheng.assistant.domain.repositories.reference_source_repository import AssistantReferenceSourceRepository
from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.assistant import AssistantNotExistsError
from bisheng.common.errcode.http_error import UnAuthorizedError
from bisheng.common.errcode.knowledge import KnowledgeOperationPlanConflictError, ResourceReferenceInvalidError
from bisheng.core.context.tenant import set_visible_tenant_ids
from bisheng.core.database.tenant_filter import register_tenant_filter_events
from bisheng.database.models.assistant import Assistant, AssistantLink
from bisheng.resource_reference.application.source_contracts import SourceReadRequest, payload_digest
from bisheng.share_link.domain.models.share_link import ShareLink


@pytest.fixture
def source_tenant(tenant_context):
    tenant_context(101)
    visible = set_visible_tenant_ids(frozenset({101, 1}))
    yield
    from bisheng.core.context.tenant import visible_tenant_ids

    visible_tenant_ids.reset(visible)


@pytest.fixture
async def source_db(tmp_path, source_tenant, monkeypatch):
    register_tenant_filter_events()
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'source.db'}")
    async with engine.begin() as connection:
        await connection.run_sync(
            lambda conn: SQLModel.metadata.create_all(
                conn, tables=[Assistant.__table__, AssistantLink.__table__, ShareLink.__table__]
            )
        )
        await connection.execute(
            insert(Assistant),
            [
                {"id": key, "tenant_id": tenant, "user_id": 9, "model_name": "7", "name": key}
                for key, tenant in (("owned", 101), ("root", 1), ("foreign", 202))
            ],
        )
        await connection.execute(
            insert(AssistantLink),
            [
                {"assistant_id": key, "tenant_id": tenant, "knowledge_id": 10}
                for key, tenant in (("owned", 101), ("root", 1), ("foreign", 202))
            ],
        )
        await connection.execute(
            insert(ShareLink),
            [
                {
                    "id": "share-1",
                    "tenant_id": 202,
                    "share_token": "real-token",
                    "resource_id": "conversation",
                    "resource_type": "WORKBENCH_CHAT",
                    "share_mode": "READ_ONLY",
                    "status": "ACTIVE",
                    "create_user_id": "9",
                    "meta_data": {"flowId": "foreign"},
                    "expire_time": 1,
                },
                {
                    "id": "share-2",
                    "tenant_id": 101,
                    "share_token": "wrong-token",
                    "resource_id": "root",
                    "resource_type": "ASSISTANT",
                    "share_mode": "READ_ONLY",
                    "status": "ACTIVE",
                    "create_user_id": "9",
                    "meta_data": None,
                    "expire_time": 0,
                },
            ],
        )
    check = AsyncMock()
    monkeypatch.setattr(owner_module, "require_business_action", check)
    user = UserPayload(user_id=9, user_name="actor", tenant_id=101, user_role=[])
    owner = AssistantReferenceSourceOwner(AssistantReferenceSourceRepository())
    try:
        yield engine, owner, user, check
    finally:
        await engine.dispose()


async def test_actual_snapshot_is_canonical_complete_and_not_an_orm(source_db):
    engine, owner, user, check = source_db
    async with AsyncSession(engine) as session, session.begin():
        snapshot = await owner.aresolve_source(session, SourceReadRequest("assistant", "owned"), user)
        payload = json.loads(snapshot.payload_json)
        assert snapshot.source_key.tenant_id == 101
        assert snapshot.source_key.source_version == "current"
        assert snapshot.configuration_digest == payload_digest(snapshot.payload_json)
        assert payload["assistant"]["model_name"] == "7"
        assert payload["links"][0]["knowledge_id"] == 10
        assert {ref.slot_key for ref in snapshot.references} == {"model_name", "knowledge_list"}
        assert not session.identity_map
        assert not session.new and not session.dirty
        check.assert_awaited_once_with(user, resource_type="assistant", resource_id="owned", action="visible")


async def test_original_principal_denial_is_not_replaced_by_root_shared_flag(source_db):
    engine, owner, user, check = source_db
    check.side_effect = UnAuthorizedError()
    async with AsyncSession(engine) as session, session.begin():
        with pytest.raises(UnAuthorizedError):
            await owner.aresolve_source(session, SourceReadRequest("assistant", "root"), user)
        assert not session.identity_map
        check.assert_awaited_once_with(user, resource_type="assistant", resource_id="root", action="visible")


async def test_foreign_source_needs_exact_active_token_inspect(source_db):
    engine, owner, user, check = source_db
    async with AsyncSession(engine) as session, session.begin():
        with pytest.raises(AssistantNotExistsError):
            await owner.aresolve_source(session, SourceReadRequest("assistant", "foreign"), user)
        snapshot = await owner.aresolve_source(
            session, SourceReadRequest("assistant", "foreign", purpose="inspect", inspect_token="real-token"), user
        )
        assert snapshot.source_key.tenant_id == 202
        assert not session.identity_map
        check.assert_not_awaited()


async def test_token_is_rechecked_after_target_locks_and_revoke_rolls_back(source_db):
    engine, owner, user, _check = source_db
    request = SourceReadRequest("assistant", "foreign", purpose="inspect", inspect_token="real-token")
    async with AsyncSession(engine) as session, session.begin():
        snapshot = await owner.aresolve_source(session, request, user)
        await session.execute(
            update(ShareLink).where(ShareLink.id == "share-1", ShareLink.tenant_id == 202).values(status="INACTIVE")
        )
        with pytest.raises(UnAuthorizedError):
            await owner.arevalidate_source(session, request, user, snapshot)
        await session.rollback()
    async with AsyncSession(engine) as session, session.begin():
        assert (await owner.aresolve_source(session, request, user)).source_key.tenant_id == 202


async def test_wrong_resource_and_untrusted_version_cannot_read_source(source_db):
    engine, owner, user, _check = source_db
    async with AsyncSession(engine) as session, session.begin():
        with pytest.raises(UnAuthorizedError):
            await owner.aresolve_source(
                session, SourceReadRequest("assistant", "foreign", purpose="inspect", inspect_token="wrong-token"), user
            )
        with pytest.raises(ResourceReferenceInvalidError):
            await owner.aresolve_source(session, SourceReadRequest("assistant", "owned", "123"), user)
        with pytest.raises(ResourceReferenceInvalidError):
            await owner.aresolve_source(session, SourceReadRequest("workflow_version", "owned"), user)


async def test_current_read_reauthorizes_and_detects_nonreference_configuration_change(source_db):
    engine, owner, user, check = source_db
    request = SourceReadRequest("assistant", "owned")
    async with AsyncSession(engine) as session, session.begin():
        snapshot = await owner.aresolve_source(session, request, user)
        await session.execute(
            update(Assistant).where(Assistant.id == "owned", Assistant.tenant_id == 101).values(system_prompt="changed")
        )
        with pytest.raises(KnowledgeOperationPlanConflictError):
            await owner.arevalidate_source(session, request, user, snapshot)
        assert check.await_count == 2
        assert not session.identity_map


async def test_current_read_observes_link_change_and_original_permission_revocation(source_db):
    engine, owner, user, check = source_db
    request = SourceReadRequest("assistant", "owned")
    async with AsyncSession(engine) as session, session.begin():
        snapshot = await owner.aresolve_source(session, request, user)
        await session.execute(
            update(AssistantLink)
            .where(AssistantLink.assistant_id == "owned", AssistantLink.tenant_id == 101)
            .values(knowledge_id=20)
        )
        with pytest.raises(KnowledgeOperationPlanConflictError):
            await owner.arevalidate_source(session, request, user, snapshot)
        check.side_effect = UnAuthorizedError()
        with pytest.raises(UnAuthorizedError):
            await owner.arevalidate_source(session, request, user, snapshot)


async def test_no_autoflush_and_no_internal_commit(source_db):
    engine, owner, user, _check = source_db
    async with AsyncSession(engine, autoflush=True) as session, session.begin():
        session.add(Assistant(id="pending", tenant_id=101, user_id=9))
        await owner.aresolve_source(session, SourceReadRequest("assistant", "owned"), user)
        assert len(session.new) == 1
        assert session.in_transaction()
        await session.rollback()
    async with AsyncSession(engine) as session, session.begin():
        with pytest.raises(AssistantNotExistsError):
            await owner.aresolve_source(session, SourceReadRequest("assistant", "pending"), user)

"""T057: restoring inheritance unlinks only this tenant's original override.

覆盖 AC: AC-71, AC-87, AC-88
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import delete, select
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.errcode.knowledge import KnowledgeProcessingConflictError, ReferenceCoverageNotReadyError
from bisheng.common.errcode.llm_tenant import LLMSystemConfigForbiddenError
from bisheng.core.context.tenant import bypass_tenant_filter
from bisheng.llm.application.model_default import ModelDefaultApplication
from bisheng.llm.domain.models.llm_server import LLMModel
from bisheng.llm.domain.models.tenant_system_model_config import TenantSystemModelConfig
from bisheng.llm.domain.repositories.model_default_repository import ModelDefaultRepository
from bisheng.resource_reference.application.contracts import SourceKey
from bisheng.resource_reference.domain.models.business_reference_set import BusinessReferenceSet
from bisheng.resource_reference.domain.models.resource_reference_tombstone import ResourceReferenceTombstone
from test.knowledge_unification import test_llm_defaults as writes
from test.knowledge_unification.test_ref_repo import tenant

business = writes.business
model_owner_tenant = writes.model_owner_tenant


@pytest.mark.parametrize(
    "key,payload",
    [
        ("knowledge_llm", {"source_model_id": 11}),
        ("assistant_llm", {"auto_llm": {"model_id": 11}}),
        ("workflow_llm", {"model_id": 11}),
        ("evaluation_llm", {"model_id": 11}),
        ("linsight_llm", {"models": [{"id": "11", "name": "own"}]}),
    ],
)
async def test_restore_five_keys_preserves_root_other_tenant_and_inactivates_only_own_bindings(business, key, payload):
    async with AsyncSession(business.engine) as session, session.begin():
        await ModelDefaultApplication.asave(session, key, payload, login_user=business.user)
        session.add_all(
            [
                TenantSystemModelConfig(tenant_id=1, key=key, value="{}"),
                TenantSystemModelConfig(tenant_id=202, key=key, value='{"do_not_touch":202}'),
            ]
        )
    async with AsyncSession(business.engine) as session, session.begin():
        resolved = await ModelDefaultApplication.arestore_inheritance(session, key, login_user=business.user)
        assert resolved.inherited_from_root and resolved.source.tenant_id == 1 and resolved.payload_json == "{}"
        assert await ModelDefaultRepository().aget_own(session, key) is None
        source = SourceKey(101, "model_default", key, "current")
        index = await business.runtime.repository.aget_source_set(session, source)
        assert (
            index.ready
            and not index.effective
            and not await business.runtime.repository.alist_source_references(session, source)
        )
    async with AsyncSession(business.engine) as session:
        with bypass_tenant_filter():
            values = {
                (row.tenant_id, row.value) for row in (await session.execute(select(TenantSystemModelConfig))).scalars()
            }
        assert (1, "{}") in values and (202, '{"do_not_touch":202}') in values


async def test_restore_r2_failure_after_delete_rolls_back_override_and_revision(business, monkeypatch):
    async with AsyncSession(business.engine) as session, session.begin():
        await ModelDefaultApplication.asave(session, "evaluation_llm", {"model_id": 11}, login_user=business.user)
    original = business.runtime.aapply_source_bindings

    async def fail(session, prepared):
        await original(session, prepared)
        raise RuntimeError("index save failed")

    monkeypatch.setattr(business.runtime, "aapply_source_bindings", fail)
    with pytest.raises(RuntimeError):
        async with AsyncSession(business.engine) as session, session.begin():
            await ModelDefaultApplication.arestore_inheritance(session, "evaluation_llm", login_user=business.user)
    async with AsyncSession(business.engine) as session:
        assert (await ModelDefaultRepository().aget_own(session, "evaluation_llm")).value
        index = await business.runtime.repository.aget_source_set(
            session, SourceKey(101, "model_default", "evaluation_llm", "current")
        )
        assert index.effective and index.source_revision == 1


async def test_absent_override_does_not_materialize_an_inherited_consumer_source(business):
    async with AsyncSession(business.engine) as session, session.begin():
        session.add(TenantSystemModelConfig(tenant_id=1, key="evaluation_llm", value='{"model_id":22}'))
    async with AsyncSession(business.engine) as session, session.begin():
        result = await ModelDefaultApplication.arestore_inheritance(session, "evaluation_llm", login_user=business.user)
        assert result.inherited_from_root and result.source.tenant_id == 1
        assert not (await session.execute(select(BusinessReferenceSet))).all()


async def test_unindexed_override_is_not_deleted_by_restore(business):
    async with AsyncSession(business.engine) as session, session.begin():
        session.add(TenantSystemModelConfig(tenant_id=101, key="evaluation_llm", value='{"model_id":11}'))
    async with AsyncSession(business.engine) as session:
        with pytest.raises(ReferenceCoverageNotReadyError):
            await ModelDefaultApplication.arestore_inheritance(session, "evaluation_llm", login_user=business.user)
        await session.rollback()
    async with AsyncSession(business.engine) as session:
        assert await ModelDefaultRepository().aget_own(session, "evaluation_llm") is not None


@pytest.mark.parametrize("stage", ["deleting", "deleted"])
async def test_restore_respects_deleting_fence_but_can_unlink_deleted_target(business, stage):
    async with AsyncSession(business.engine) as session, session.begin():
        await ModelDefaultApplication.asave(session, "evaluation_llm", {"model_id": 11}, login_user=business.user)
        session.add(
            ResourceReferenceTombstone(
                tenant_id=101,
                target_tenant_id=101,
                target_type="model",
                target_id="11",
                operation_id="deleting-model",
                operation_type="force_delete_model",
                actor_type="user",
                actor_id="7",
                stage=stage,
            )
        )
        if stage == "deleted":
            await session.execute(delete(LLMModel).where(LLMModel.tenant_id == 101, LLMModel.id == 11))
    async with AsyncSession(business.engine) as session, session.begin():
        if stage == "deleting":
            with pytest.raises(KnowledgeProcessingConflictError):
                await ModelDefaultApplication.arestore_inheritance(session, "evaluation_llm", login_user=business.user)
        else:
            await ModelDefaultApplication.arestore_inheritance(session, "evaluation_llm", login_user=business.user)
            assert await ModelDefaultRepository().aget_own(session, "evaluation_llm") is None


async def test_root_itself_has_no_restore_inheritance_action(business):
    with tenant(1):
        async with AsyncSession(business.engine) as session:
            with pytest.raises(LLMSystemConfigForbiddenError):
                await ModelDefaultApplication.arestore_inheritance(session, "evaluation_llm", login_user=business.user)


async def test_restore_endpoint_uses_original_actor_and_scope_and_one_commit(monkeypatch, business):
    from contextlib import asynccontextmanager

    from bisheng.llm.api import router as api

    active = SimpleNamespace(commit=AsyncMock())

    @asynccontextmanager
    async def session_factory():
        yield active

    result = SimpleNamespace(payload_json='{"model_id":22}', inherited_from_root=True, fallback_blocked=False)
    restore = AsyncMock(return_value=result)
    monkeypatch.setattr(api, "get_async_db_session", session_factory, raising=False)
    monkeypatch.setattr(api.ModelDefaultApplication, "arestore_inheritance", restore)
    monkeypatch.setattr(api, "_assert_can_write_system_config", AsyncMock())
    monkeypatch.setattr(api, "_read_before_snapshot", AsyncMock(return_value={"model_id": 11}))
    monkeypatch.setattr(api, "_audit_system_config_update", AsyncMock())
    response = await api.restore_model_default_inheritance("evaluation_llm", login_user=business.user)
    restore.assert_awaited_once_with(active, "evaluation_llm", login_user=business.user)
    active.commit.assert_awaited_once()
    assert response.data["inherited_from_root"] and response.data["data"]["model_id"] == 22

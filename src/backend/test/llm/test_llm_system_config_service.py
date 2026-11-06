"""F022 defaults retain typed contracts through F118's real source graph.

覆盖 AC: AC-71, AC-79, AC-83, AC-87, AC-88, AC-89, AC-92
Native/async SQLite sessions are isolated; no provider is initialized.
"""

import json

import pytest
from sqlalchemy import update
from sqlmodel import Session
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.errcode.knowledge import ResourceReferenceInvalidError
from bisheng.common.services.config_service import settings
from bisheng.database.models.tenant import Tenant
from bisheng.llm.application import model_default_read
from bisheng.llm.application.model_default import current_model_default_tenant
from bisheng.llm.domain.repositories.model_default_repository import ModelDefaultRepository
from bisheng.llm.domain.schemas import AssistantLLMConfig, EvaluationLLMConfig, KnowledgeLLMConfig
from bisheng.llm.domain.services.llm import LLMService
from bisheng.resource_reference.application.contracts import SourceKey
from test.knowledge_unification import test_llm_default_read as reading
from test.knowledge_unification import test_llm_defaults as writing
from test.knowledge_unification import test_model_default_native_target as native
from test.knowledge_unification.test_ref_repo import tenant

reads = reading.reads
business = writing.business
model_owner_tenant = reading.model_owner_tenant


@pytest.fixture
async def configured(reads, monkeypatch):
    monkeypatch.setattr(model_default_read, "_runtime", reads.facade)
    return reads


def test_explicit_tenant_cannot_override_the_trusted_current_scope(model_owner_tenant):
    with pytest.raises(ResourceReferenceInvalidError):
        current_model_default_tenant(202)
    assert current_model_default_tenant(101) == 101


def test_omitted_tenant_uses_current_context(model_owner_tenant):
    assert current_model_default_tenant() == 101


def test_missing_multitenant_context_refuses_instead_of_falling_back_to_root(monkeypatch):
    monkeypatch.setattr(settings.multi_tenant, "enabled", True)
    with tenant(None), pytest.raises(ResourceReferenceInvalidError):
        current_model_default_tenant()


async def test_aget_knowledge_llm_keeps_typed_values_after_full_source_admission(configured):
    with Session(configured.engine) as session, session.begin():
        native.seed_default(session, key="knowledge_llm", payload={"embedding_model_id": 11})
    cfg = await LLMService.aget_knowledge_llm(tenant_id=101)
    assert isinstance(cfg, KnowledgeLLMConfig) and cfg.embedding_model_id == 11


async def test_aget_knowledge_llm_with_meta_keeps_inherited_envelope(configured):
    with Session(configured.engine) as session, session.begin():
        native.seed_default(session, tenant_id=1, key="knowledge_llm", payload={"embedding_model_id": 22})
    cfg, inherited, blocked = await LLMService.aget_knowledge_llm_with_meta(tenant_id=101)
    assert isinstance(cfg, KnowledgeLLMConfig) and cfg.embedding_model_id == 22
    assert inherited is True and blocked is False


async def test_get_assistant_llm_returns_typed_empty_config_when_no_source_exists(configured):
    cfg = await LLMService.get_assistant_llm(tenant_id=101)
    assert isinstance(cfg, AssistantLLMConfig) and cfg.llm_list == []


async def test_aget_workflow_llm_with_meta_preserves_blocked_root_flag(configured):
    with Session(configured.engine) as session, session.begin():
        native.seed_default(session, tenant_id=1, key="workflow_llm", payload={"model_id": 22})
        session.execute(update(Tenant).where(Tenant.id == 1).values(share_default_to_children=0))
    cfg, inherited, blocked = await LLMService.aget_workflow_llm_with_meta(tenant_id=101)
    assert isinstance(cfg, EvaluationLLMConfig) and cfg.model_id is None
    assert inherited is False and blocked is True


async def test_sync_get_assistant_llm_uses_native_session_and_typed_empty_config(configured):
    with Session(configured.engine) as session, session.begin():
        native.seed_default(session, key="assistant_llm", payload={"llm_list": []})
    with Session(configured.engine) as session:
        cfg = LLMService.sync_get_assistant_llm(tenant_id=101, session=session)
        assert isinstance(cfg, AssistantLLMConfig) and cfg.llm_list == []
        assert session.in_transaction() and not session.identity_map


@pytest.mark.parametrize(
    "method,key,payload,field",
    [
        ("update_knowledge_llm", "knowledge_llm", KnowledgeLLMConfig(embedding_model_id=11), "embedding_model_id"),
        ("update_assistant_llm", "assistant_llm", AssistantLLMConfig(llm_list=[]), "llm_list"),
        ("update_evaluation_llm", "evaluation_llm", EvaluationLLMConfig(model_id=12), "model_id"),
        ("update_workflow_llm", "workflow_llm", EvaluationLLMConfig(model_id=11), "model_id"),
    ],
)
async def test_setters_preserve_schema_values_and_source_tenant_in_original_session(
    business, method, key, payload, field
):
    async with AsyncSession(business.engine) as session:
        result = await getattr(LLMService, method)(payload, tenant_id=101, login_user=business.user, session=session)
        stored = await ModelDefaultRepository().aget_own(session, key)
        index = await business.runtime.repository.aget_source_set(
            session, SourceKey(101, "model_default", key, "current")
        )
        assert type(result) is type(payload)
        assert getattr(result, field) == getattr(payload, field)
        assert stored.tenant_id == 101 and json.loads(stored.value)[field] == payload.model_dump(mode="json")[field]
        assert index.ready and index.effective and index.tenant_id == 101
        assert session.in_transaction()
        await session.rollback()
    async with AsyncSession(business.engine) as check:
        assert await ModelDefaultRepository().aget_own(check, key) is None


async def test_default_tenant_write_keeps_current_context_without_an_explicit_argument(business):
    async with AsyncSession(business.engine) as session:
        await LLMService.update_assistant_llm(
            AssistantLLMConfig(llm_list=[]), login_user=business.user, session=session
        )
        assert (await ModelDefaultRepository().aget_own(session, "assistant_llm")).tenant_id == 101
        await session.rollback()

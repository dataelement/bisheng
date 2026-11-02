"""F115 AC-41/42/44/47/49/50/52: pre-write revalidation, not copy."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest


async def test_web_entry_fixes_scope_to_identity_and_passes_context(monkeypatch):
    from bisheng.core.context.tenant import get_current_tenant_id
    from bisheng.knowledge.api.endpoints import knowledge as api
    from bisheng.knowledge.domain.schemas.knowledge_create_schema import KnowledgeWebCreate
    from bisheng.knowledge.domain.services.knowledge_creation_policy import KnowledgeCreationPolicy

    context = SimpleNamespace(user_id=9, tenant_id=60)
    monkeypatch.setattr(KnowledgeCreationPolicy, "prepare", AsyncMock(return_value=context))

    async def create(request, user, data, *, web_creation_context=None):
        assert get_current_tenant_id() == 60
        assert web_creation_context is context
        return {"id": 1, "tenant_id": 60, "user_id": user.user_id}

    monkeypatch.setattr(api.KnowledgeService, "acreate_knowledge", create)
    result = await api.create_knowledge(
        request=object(),
        login_user=SimpleNamespace(user_id=9, tenant_id=60),
        knowledge=KnowledgeWebCreate(name="New library", model="1", type=0, expected_tenant_id=60),
    )
    assert result.data["tenant_id"] == 60


async def test_revocation_during_model_lookup_prevents_all_creation_writes(monkeypatch):
    from bisheng.common.errcode.permission import PermissionDeniedError
    from bisheng.knowledge.domain.models.knowledge import KnowledgeCreate
    from bisheng.knowledge.domain.services.knowledge_creation_policy import KnowledgeCreationPolicy
    from bisheng.knowledge.domain.services.knowledge_service import KnowledgeDao, KnowledgeService, LLMModelType
    from bisheng.llm.domain import share_fallback

    monkeypatch.setattr(KnowledgeDao, "aget_knowledge_by_name", AsyncMock(return_value=None))
    monkeypatch.setattr(
        share_fallback,
        "aget_model_by_id_with_share_fallback",
        AsyncMock(return_value=SimpleNamespace(model_type=LLMModelType.EMBEDDING.value)),
    )
    check = AsyncMock(side_effect=PermissionDeniedError())
    monkeypatch.setattr(KnowledgeCreationPolicy, "revalidate", check)
    write = AsyncMock()
    monkeypatch.setattr(KnowledgeService, "acreate_knowledge_base", write)
    with pytest.raises(PermissionDeniedError):
        await KnowledgeService.acreate_knowledge(
            object(),
            SimpleNamespace(user_id=9, tenant_id=60),
            KnowledgeCreate(name="Test", model="1", type=0),
            web_creation_context=object(),
        )
    check.assert_awaited_once()
    write.assert_not_called()

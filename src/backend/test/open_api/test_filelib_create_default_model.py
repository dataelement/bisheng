"""v2 ``POST /api/v2/filelib/``: ``model`` is optional for knowledge bases (type 0/1).

When the caller omits ``model``, the endpoint uses the tenant's default
knowledge-base embedding model, which is the same source the platform create
dialog reads (``GET /api/v1/llm/knowledge`` -> ``embedding_model_id``). When the
tenant has no default either, the request still fails with 10901.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

import bisheng.llm.domain.share_fallback as share_fallback
import bisheng.open_endpoints.api.endpoints.filelib as filelib
from bisheng.common.errcode.knowledge import KnowledgeNoEmbeddingError
from bisheng.knowledge.domain.models.knowledge import KnowledgeCreate, KnowledgeTypeEnum
from bisheng.knowledge.domain.services import knowledge_service as ks_module
from bisheng.knowledge.domain.services.knowledge_service import KnowledgeService
from bisheng.knowledge.domain.services.knowledge_space_service import KnowledgeSpaceService
from bisheng.llm.domain.schemas import KnowledgeLLMConfig
from bisheng.llm.domain.services.llm import LLMService

TENANT_ID = 9


@pytest.fixture
def env(monkeypatch):
    operator = SimpleNamespace(user_id=12, user_name="operator", tenant_id=TENANT_ID)
    monkeypatch.setattr(filelib, "get_open_api_operator_async", AsyncMock(return_value=operator))

    knowledge_llm = AsyncMock(return_value=KnowledgeLLMConfig(embedding_model_id=42))
    monkeypatch.setattr(LLMService, "aget_knowledge_llm", knowledge_llm)

    # Let the real acreate_knowledge run its model checks; stop before storage.
    monkeypatch.setattr(ks_module.KnowledgeDao, "aget_knowledge_by_name", AsyncMock(return_value=None))
    lookup = AsyncMock(side_effect=lambda model_id: SimpleNamespace(id=model_id, model_type="embedding"))
    monkeypatch.setattr(share_fallback, "aget_model_by_id_with_share_fallback", lookup)
    created = AsyncMock(side_effect=lambda request, login_user, db_knowledge: db_knowledge)
    monkeypatch.setattr(KnowledgeService, "acreate_knowledge_base", created)
    monkeypatch.setattr(
        KnowledgeService,
        "aconvert_knowledge_read",
        AsyncMock(side_effect=lambda login_user, rows: [{"model": rows[0].model, "type": rows[0].type}]),
    )
    return SimpleNamespace(knowledge_llm=knowledge_llm, lookup=lookup, created=created)


@pytest.mark.parametrize("ktype", [KnowledgeTypeEnum.NORMAL.value, KnowledgeTypeEnum.QA.value])
@pytest.mark.parametrize("model", [None, "", "  "])
async def test_omitted_model_uses_tenant_default(env, ktype, model):
    req = KnowledgeCreate(name="kb", type=ktype, model=model)
    resp = await filelib.create(request=None, knowledge=req, version_repo=None, doc_repo=None)

    assert resp.data == {"model": "42", "type": ktype}
    env.knowledge_llm.assert_awaited_once_with(tenant_id=TENANT_ID)
    env.lookup.assert_awaited_once_with(42)


async def test_explicit_model_is_kept_and_default_not_read(env):
    req = KnowledgeCreate(name="kb", type=0, model=12)
    resp = await filelib.create(request=None, knowledge=req, version_repo=None, doc_repo=None)

    assert resp.data["model"] == "12"
    env.knowledge_llm.assert_not_awaited()
    env.lookup.assert_awaited_once_with(12)


async def test_no_tenant_default_still_raises_10901(env):
    env.knowledge_llm.return_value = KnowledgeLLMConfig(embedding_model_id=None)
    req = KnowledgeCreate(name="kb", type=0)

    with pytest.raises(HTTPException) as caught:
        await filelib.create(request=None, knowledge=req, version_repo=None, doc_repo=None)

    assert caught.value.status_code == KnowledgeNoEmbeddingError.Code == 10901
    env.created.assert_not_awaited()


async def test_default_model_that_is_not_embedding_raises_10901(env):
    env.lookup.side_effect = lambda model_id: SimpleNamespace(id=model_id, model_type="llm")
    req = KnowledgeCreate(name="kb", type=0)

    with pytest.raises(HTTPException) as caught:
        await filelib.create(request=None, knowledge=req, version_repo=None, doc_repo=None)

    assert caught.value.status_code == 10901
    env.created.assert_not_awaited()


async def test_space_does_not_read_knowledge_default(env, monkeypatch):
    async def _space_create(self, **kwargs):
        return SimpleNamespace(
            id=7, model_dump=lambda: {"id": 7, "name": "space", "type": KnowledgeTypeEnum.SPACE.value}
        )

    monkeypatch.setattr(KnowledgeSpaceService, "create_knowledge_space", _space_create)
    monkeypatch.setattr(KnowledgeSpaceService, "_get_effective_actions", AsyncMock(return_value={"visible"}))

    req = KnowledgeCreate(name="space", type=KnowledgeTypeEnum.SPACE.value)
    resp = await filelib.create(request=None, knowledge=req, version_repo=None, doc_repo=None)

    assert resp.data.type == KnowledgeTypeEnum.SPACE.value
    env.knowledge_llm.assert_not_awaited()

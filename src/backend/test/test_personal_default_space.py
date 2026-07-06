import pytest
from unittest.mock import AsyncMock, patch
from bisheng.knowledge.domain.models.knowledge import Knowledge
from bisheng.knowledge.domain.services.knowledge_space_service import KnowledgeSpaceService


def _svc(user_id=7, user_name="张三"):
    svc = KnowledgeSpaceService.__new__(KnowledgeSpaceService)
    svc.login_user = type("U", (), {"user_id": user_id, "user_name": user_name, "tenant_id": 1})()
    svc.request = None
    return svc


def test_personal_default_space_name_uses_user_name():
    assert _svc(user_name="张三").personal_default_space_name() == "张三的知识库"


@pytest.mark.asyncio
async def test_ensure_personal_default_returns_existing():
    svc = _svc()
    existing = Knowledge(id=200, name="张三的知识库", user_id=7, type=3)
    with patch.object(KnowledgeSpaceService, "_find_personal_default_space",
                      new=AsyncMock(return_value=existing)), \
         patch.object(KnowledgeSpaceService, "create_knowledge_space", new=AsyncMock()) as creator:
        space = await svc._ensure_personal_default_space()
        assert space.id == 200
        creator.assert_not_called()


@pytest.mark.asyncio
async def test_ensure_personal_default_creates_when_missing():
    svc = _svc()
    created = Knowledge(id=201, name="张三的知识库", user_id=7, type=3)
    with patch.object(KnowledgeSpaceService, "_find_personal_default_space",
                      new=AsyncMock(return_value=None)), \
         patch.object(KnowledgeSpaceService, "create_knowledge_space",
                      new=AsyncMock(return_value=created)) as creator:
        space = await svc._ensure_personal_default_space()
        assert space.id == 201
        creator.assert_awaited_once()


@pytest.mark.asyncio
async def test_ensure_personal_spaces_ensures_both():
    svc = _svc()
    with patch.object(KnowledgeSpaceService, "_ensure_favorite_space", new=AsyncMock()) as fav, \
         patch.object(KnowledgeSpaceService, "_ensure_personal_default_space", new=AsyncMock()) as dft:
        await svc._ensure_personal_spaces()
        fav.assert_awaited_once()
        dft.assert_awaited_once()

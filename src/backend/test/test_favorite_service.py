import pytest
from unittest.mock import AsyncMock, patch
from bisheng.knowledge.domain.models.knowledge import Knowledge
from bisheng.knowledge.domain.services.knowledge_space_service import KnowledgeSpaceService


def _make_service(user_id=7):
    svc = KnowledgeSpaceService.__new__(KnowledgeSpaceService)
    svc.login_user = type("U", (), {"user_id": user_id, "user_name": "u", "tenant_id": 1})()
    svc.request = None
    return svc


@pytest.mark.asyncio
async def test_ensure_favorite_space_returns_existing():
    svc = _make_service()
    existing = Knowledge(id=100, name="我的收藏", user_id=7, type=3, is_favorite=True)
    with patch.object(KnowledgeSpaceService, "_find_favorite_space",
                      new=AsyncMock(return_value=existing)), \
         patch.object(KnowledgeSpaceService, "_create_favorite_space",
                      new=AsyncMock()) as creator:
        space = await svc._ensure_favorite_space()
        assert space.id == 100
        creator.assert_not_called()


@pytest.mark.asyncio
async def test_ensure_favorite_space_creates_when_missing():
    svc = _make_service()
    created = Knowledge(id=101, name="我的收藏", user_id=7, type=3, is_favorite=True)
    with patch.object(KnowledgeSpaceService, "_find_favorite_space",
                      new=AsyncMock(return_value=None)), \
         patch.object(KnowledgeSpaceService, "_create_favorite_space",
                      new=AsyncMock(return_value=created)) as creator:
        space = await svc._ensure_favorite_space()
        assert space.id == 101
        creator.assert_awaited_once()


@pytest.mark.asyncio
async def test_ensure_favorite_space_concurrent_fallback():
    # 创建抛异常（并发下别人已建），回查能拿到
    svc = _make_service()
    created = Knowledge(id=102, name="我的收藏", user_id=7, type=3, is_favorite=True)
    find = AsyncMock(side_effect=[None, created])  # 第一次没有，回查命中
    with patch.object(KnowledgeSpaceService, "_find_favorite_space", new=find), \
         patch.object(KnowledgeSpaceService, "_create_favorite_space",
                      new=AsyncMock(side_effect=Exception("dup"))):
        space = await svc._ensure_favorite_space()
        assert space.id == 102

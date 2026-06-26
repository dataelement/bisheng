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


@pytest.mark.asyncio
async def test_create_favorite_idempotent_returns_existing():
    from bisheng.knowledge.domain.schemas.knowledge_space_schema import ShougangPortalFavoriteCreateReq
    from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile
    svc = _make_service()
    fav_space = Knowledge(id=200, name="我的收藏", user_id=7, type=3, is_favorite=True)
    source_space = Knowledge(id=1, name="src", user_id=3, type=3)
    source_file = KnowledgeFile(id=2, knowledge_id=1, user_id=3, file_name="doc.pdf")
    existing_ref = KnowledgeFile(id=999, knowledge_id=200, user_id=7, file_name="doc.pdf",
                                 user_metadata={"favorite_reference": {"source_space_id": 1, "source_file_id": 2}})
    with patch("bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeDao.aquery_by_id",
               new=AsyncMock(return_value=source_space)), \
         patch("bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeFileDao.query_by_id",
               new=AsyncMock(return_value=source_file)), \
         patch.object(KnowledgeSpaceService, "_ensure_space_file", new=lambda self, f, sid: f), \
         patch.object(KnowledgeSpaceService, "_require_permission_id", new=AsyncMock()), \
         patch.object(KnowledgeSpaceService, "_ensure_favorite_space", new=AsyncMock(return_value=fav_space)), \
         patch.object(KnowledgeSpaceService, "_find_favorite_reference", new=AsyncMock(return_value=existing_ref)), \
         patch.object(KnowledgeSpaceService, "_create_favorite_reference", new=AsyncMock()) as creator:
        resp = await svc.create_shougang_portal_favorite(
            ShougangPortalFavoriteCreateReq(source_space_id=1, source_file_id=2))
        assert resp.favorite_file_id == 999
        assert resp.space_id == 200
        assert resp.source_space_id == 1 and resp.source_file_id == 2
        creator.assert_not_called()


@pytest.mark.asyncio
async def test_create_favorite_creates_reference_when_absent():
    from bisheng.knowledge.domain.schemas.knowledge_space_schema import ShougangPortalFavoriteCreateReq
    from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile
    svc = _make_service()
    fav_space = Knowledge(id=200, name="我的收藏", user_id=7, type=3, is_favorite=True)
    source_space = Knowledge(id=1, name="src", user_id=3, type=3)
    source_file = KnowledgeFile(id=2, knowledge_id=1, user_id=3, file_name="doc.pdf")
    new_ref = KnowledgeFile(id=1000, knowledge_id=200, user_id=7, file_name="doc.pdf",
                            user_metadata={"favorite_reference": {"source_space_id": 1, "source_file_id": 2}})
    with patch("bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeDao.aquery_by_id",
               new=AsyncMock(return_value=source_space)), \
         patch("bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeFileDao.query_by_id",
               new=AsyncMock(return_value=source_file)), \
         patch("bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeDao.async_update_knowledge_update_time_by_id",
               new=AsyncMock()), \
         patch.object(KnowledgeSpaceService, "_ensure_space_file", new=lambda self, f, sid: f), \
         patch.object(KnowledgeSpaceService, "_require_permission_id", new=AsyncMock()), \
         patch.object(KnowledgeSpaceService, "_ensure_favorite_space", new=AsyncMock(return_value=fav_space)), \
         patch.object(KnowledgeSpaceService, "_find_favorite_reference", new=AsyncMock(return_value=None)), \
         patch.object(KnowledgeSpaceService, "_create_favorite_reference", new=AsyncMock(return_value=new_ref)) as creator:
        resp = await svc.create_shougang_portal_favorite(
            ShougangPortalFavoriteCreateReq(source_space_id=1, source_file_id=2))
        assert resp.favorite_file_id == 1000
        creator.assert_awaited_once()

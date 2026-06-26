import pytest
from unittest.mock import AsyncMock, patch
from bisheng.knowledge.domain.models.knowledge import Knowledge
from bisheng.knowledge.domain.services.knowledge_space_service import KnowledgeSpaceService
from bisheng.common.errcode.knowledge_space import FavoriteSpaceProtectedError


def _svc(user_id=7):
    s = KnowledgeSpaceService.__new__(KnowledgeSpaceService)
    s.login_user = type("U", (), {"user_id": user_id, "user_name": "u", "tenant_id": 1})()
    s.request = None
    return s


@pytest.mark.asyncio
async def test_delete_favorite_space_blocked():
    svc = _svc()
    fav = Knowledge(id=200, name="我的收藏", user_id=7, type=3, is_favorite=True)
    with patch("bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeDao.aquery_by_id",
               new=AsyncMock(return_value=fav)):
        with pytest.raises(FavoriteSpaceProtectedError):
            await svc.delete_space(200)


@pytest.mark.asyncio
async def test_update_favorite_space_blocked():
    svc = _svc()
    fav = Knowledge(id=200, name="我的收藏", user_id=7, type=3, is_favorite=True)
    with patch("bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeDao.aquery_by_id",
               new=AsyncMock(return_value=fav)):
        with pytest.raises(FavoriteSpaceProtectedError):
            await svc.update_knowledge_space(space_id=200, name="改个名")


@pytest.mark.asyncio
async def test_delete_normal_space_not_blocked_by_favorite_guard():
    # 普通库不应被收藏 guard 拦截（应继续走到权限检查并因权限/其它原因失败，但绝不能抛 FavoriteSpaceProtectedError）
    svc = _svc()
    normal = Knowledge(id=300, name="普通库", user_id=7, type=3, is_favorite=False)
    with patch("bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeDao.aquery_by_id",
               new=AsyncMock(return_value=normal)), \
         patch.object(KnowledgeSpaceService, "_require_permission_id",
                      new=AsyncMock(side_effect=RuntimeError("perm-checked"))):
        with pytest.raises(RuntimeError):  # 走到了权限检查，说明没被收藏 guard 拦下
            await svc.delete_space(300)

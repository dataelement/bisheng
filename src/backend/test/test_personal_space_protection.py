import pytest
from unittest.mock import AsyncMock, patch
from types import SimpleNamespace
from bisheng.knowledge.domain.models.knowledge import Knowledge
from bisheng.knowledge.domain.models.knowledge_space_scope import KnowledgeSpaceLevelEnum
from bisheng.knowledge.domain.services.knowledge_space_service import KnowledgeSpaceService
from bisheng.common.errcode.knowledge import PersonalSpaceProtectedError


def _svc():
    svc = KnowledgeSpaceService.__new__(KnowledgeSpaceService)
    svc.login_user = type("U", (), {"user_id": 7, "user_name": "u", "tenant_id": 1})()
    svc.request = None
    return svc


@pytest.mark.asyncio
async def test_delete_personal_space_is_rejected():
    svc = _svc()
    space = Knowledge(id=300, name="张三的知识库", user_id=7, type=3, is_favorite=False)
    scope = SimpleNamespace(level=KnowledgeSpaceLevelEnum.PERSONAL)
    with patch("bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeDao") as kdao, \
         patch("bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeSpaceScopeDao") as sdao:
        kdao.aquery_by_id = AsyncMock(return_value=space)
        sdao.aget_by_space_id = AsyncMock(return_value=scope)
        with pytest.raises(PersonalSpaceProtectedError):
            await svc.delete_space(300)


@pytest.mark.asyncio
async def test_manage_members_on_personal_space_is_rejected():
    svc = _svc()
    scope = SimpleNamespace(level=KnowledgeSpaceLevelEnum.PERSONAL)
    req = SimpleNamespace(space_id=300, user_id=9)
    with patch("bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeSpaceScopeDao") as sdao:
        sdao.aget_by_space_id = AsyncMock(return_value=scope)
        with pytest.raises(PersonalSpaceProtectedError):
            await svc.update_member_role(req)
        with pytest.raises(PersonalSpaceProtectedError):
            await svc.remove_member(req)

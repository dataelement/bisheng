import pytest
from unittest.mock import AsyncMock, patch
from bisheng.knowledge.domain.services.knowledge_space_service import KnowledgeSpaceService


def _svc():
    svc = KnowledgeSpaceService.__new__(KnowledgeSpaceService)
    svc.login_user = type("U", (), {"user_id": 7, "user_name": "u", "tenant_id": 1})()
    svc.request = None
    return svc


@pytest.mark.asyncio
async def test_get_grouped_spaces_ensures_personal_spaces():
    # NOTE: 本分支的 get_grouped_spaces 用 _format_accessible_spaces + DAO gather
    #（无 _list_accessible_spaces），故按语义 patch 真实依赖，仅断言 ensure 被调用一次。
    svc = _svc()
    with patch.object(KnowledgeSpaceService, "_ensure_personal_spaces", new=AsyncMock()) as ensure, \
         patch.object(KnowledgeSpaceService, "_format_accessible_spaces", new=AsyncMock(return_value=[])), \
         patch("bisheng.knowledge.domain.services.knowledge_space_service.SpaceChannelMemberDao") as scm, \
         patch("bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeDao") as kdao, \
         patch("bisheng.knowledge.domain.services.knowledge_space_service.PermissionService") as perm, \
         patch("bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeSpaceScopeDao") as sdao:
        scm.async_get_user_space_members = AsyncMock(return_value=[])
        kdao.aget_knowledge_ids_created_by = AsyncMock(return_value=[])
        perm.list_accessible_ids = AsyncMock(return_value=[])
        sdao.aget_space_ids_by_level = AsyncMock(return_value=[])
        await svc.get_grouped_spaces()
        ensure.assert_awaited_once()

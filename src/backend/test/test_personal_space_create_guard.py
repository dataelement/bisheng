import pytest
from unittest.mock import AsyncMock, patch
from bisheng.knowledge.domain.services.knowledge_space_service import KnowledgeSpaceService
from bisheng.knowledge.domain.models.knowledge_space_scope import KnowledgeSpaceLevelEnum
from bisheng.common.errcode.knowledge import SpacePersonalCreateForbiddenError


def _svc(user_id=7):
    svc = KnowledgeSpaceService.__new__(KnowledgeSpaceService)
    svc.login_user = type("U", (), {"user_id": user_id, "user_name": "u", "tenant_id": 1})()
    svc.request = None
    return svc


@pytest.mark.asyncio
async def test_user_initiated_personal_create_is_rejected():
    svc = _svc()
    with patch.object(KnowledgeSpaceService, "_normalize_space_name", new=lambda self, n: n):
        with pytest.raises(SpacePersonalCreateForbiddenError):
            await svc.create_knowledge_space(name="my space", space_level=KnowledgeSpaceLevelEnum.PERSONAL)


@pytest.mark.asyncio
async def test_system_managed_personal_create_passes_guard():
    """system_managed=True 必须跳过个人库创建禁令（否则会在 guard 处抛 SpacePersonalCreateForbiddenError）。
    这里只验证 guard 不触发：让后续 DB 步骤在 guard 之后失败，断言异常类型不是 SpacePersonalCreateForbiddenError。"""
    svc = _svc()
    with patch.object(KnowledgeSpaceService, "_normalize_space_name", new=lambda self, n: n), \
         patch.object(KnowledgeSpaceService, "_apply_space_user_limit_if_needed", new=AsyncMock(), create=True):
        with patch("bisheng.knowledge.domain.services.knowledge_space_service.LLMService") as llm:
            llm.get_workbench_llm = AsyncMock(return_value=None)
            with pytest.raises(Exception) as exc:
                await svc.create_knowledge_space(
                    name="我的收藏", space_level=KnowledgeSpaceLevelEnum.PERSONAL, system_managed=True,
                )
    assert not isinstance(exc.value, SpacePersonalCreateForbiddenError)

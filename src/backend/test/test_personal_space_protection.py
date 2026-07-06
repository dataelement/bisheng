import pytest
from contextlib import ExitStack
from unittest.mock import AsyncMock, MagicMock, patch
from types import SimpleNamespace
from bisheng.knowledge.domain.models.knowledge import Knowledge
from bisheng.knowledge.domain.models.knowledge_space_scope import KnowledgeSpaceLevelEnum
from bisheng.knowledge.domain.services.knowledge_space_service import KnowledgeSpaceService
from bisheng.common.errcode.knowledge_space import PersonalSpaceProtectedError

_MOD = "bisheng.knowledge.domain.services.knowledge_space_service"


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
async def test_delete_personal_space_with_force_bypasses_guard_and_skips_notification():
    """force=True (system-maintenance cleanup) deletes a personal/favorite space
    instead of raising, and suppresses the per-owner "space deleted" notification."""
    svc = _svc()
    svc._require_permission_id = AsyncMock()
    svc._list_space_child_resources = AsyncMock(return_value=[])
    svc._cleanup_resource_tuples = AsyncMock()
    svc._send_space_event_notification = AsyncMock()
    # A personal space that is ALSO a favorite — both guards would normally fire.
    space = Knowledge(id=300, name="张三的知识库", user_id=7, type=3, is_favorite=True)
    scope = SimpleNamespace(level=KnowledgeSpaceLevelEnum.PERSONAL)

    with ExitStack() as stack:
        kdao = stack.enter_context(patch(f"{_MOD}.KnowledgeDao"))
        sdao = stack.enter_context(patch(f"{_MOD}.KnowledgeSpaceScopeDao"))
        member_dao = stack.enter_context(patch(f"{_MOD}.SpaceChannelMemberDao"))
        stack.enter_context(patch(f"{_MOD}.KnowledgeService"))
        stat = stack.enter_context(patch(f"{_MOD}.KnowledgeSpaceContentStat"))
        tag_lib = stack.enter_context(patch(f"{_MOD}.KnowledgeSpaceTagLibraryDao"))
        audit = stack.enter_context(patch(f"{_MOD}.KnowledgeAuditTelemetryService"))
        sync_dao = stack.enter_context(
            patch("bisheng.channel.domain.models.channel_knowledge_sync.ChannelKnowledgeSyncDao")
        )
        kdao.aquery_by_id = AsyncMock(return_value=space)
        kdao.async_delete_knowledge = AsyncMock()
        sdao.aget_by_space_id = AsyncMock(return_value=scope)
        member_dao.async_get_members_by_space = AsyncMock(return_value=[])
        member_dao.clean_space_member = AsyncMock()
        stat.enqueue_space_delete_stat_async = AsyncMock()
        tag_lib.adelete_private_for_knowledge = AsyncMock()
        audit.audit_delete_knowledge_space = AsyncMock()
        audit.telemetry_delete_knowledge = MagicMock()
        sync_dao.adelete_by_space_id = AsyncMock()

        await svc.delete_space(300, force=True)

    kdao.async_delete_knowledge.assert_awaited_once_with(knowledge_id=300)
    svc._send_space_event_notification.assert_not_called()
    svc._require_permission_id.assert_not_called()


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

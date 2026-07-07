import pytest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from bisheng.knowledge.domain.models.knowledge import KnowledgeState, KnowledgeTypeEnum
from bisheng.knowledge.domain.services.knowledge_space_service import KnowledgeSpaceService
from bisheng.knowledge.domain.services.free_space_migration_service import MigrationDecision

MOD = "bisheng.knowledge.domain.services.knowledge_space_service"


def _svc():
    svc = KnowledgeSpaceService.__new__(KnowledgeSpaceService)
    svc.login_user = SimpleNamespace(user_id=5)
    svc.request = None
    svc._require_permission_id = AsyncMock()
    svc._list_space_child_resources = AsyncMock(return_value=[])
    return svc


def _space():
    return SimpleNamespace(id=1, type=KnowledgeTypeEnum.SPACE.value, state=1,
                           is_favorite=False, name="s", user_id=5, model="e")


@pytest.mark.asyncio
async def test_migrate_branch_enqueues_and_returns_without_delete():
    svc = _svc()
    with patch(f"{MOD}.KnowledgeDao.aquery_by_id", new=AsyncMock(return_value=_space())), \
         patch(f"{MOD}.FreeSpaceMigrationService.pre_delete_guard",
               new=AsyncMock(return_value=MigrationDecision("migrate", target_space_id=900))), \
         patch(f"{MOD}.KnowledgeDao.async_update_state", new=AsyncMock()) as upd, \
         patch(f"{MOD}.KnowledgeSpaceScopeDao.aget_by_space_id", new=AsyncMock(return_value=None)), \
         patch(f"{MOD}.space_migrate_celery") as task, \
         patch(f"{MOD}.KnowledgeService.delete_knowledge_file_in_vector") as del_vec:
        await svc.delete_space(1)
        task.delay.assert_called_once()
        del_vec.assert_not_called()        # 没有进入真正清理


@pytest.mark.asyncio
async def test_migrate_branch_rolls_back_copying_when_enqueue_fails():
    """入队失败(space_migrate_celery.delay 抛异常)时，之前置为 COPYING 的源库状态
    必须回滚为 PUBLISHED，且异常要真正抛出（不能吞成静默成功），否则源库会
    永久卡在 COPYING、既无法删除也无法正常使用（Imp-2）。
    """
    svc = _svc()
    with patch(f"{MOD}.KnowledgeDao.aquery_by_id", new=AsyncMock(return_value=_space())), \
         patch(f"{MOD}.FreeSpaceMigrationService.pre_delete_guard",
               new=AsyncMock(return_value=MigrationDecision("migrate", target_space_id=900))), \
         patch(f"{MOD}.KnowledgeDao.async_update_state", new=AsyncMock()) as upd, \
         patch(f"{MOD}.KnowledgeSpaceScopeDao.aget_by_space_id", new=AsyncMock(return_value=None)), \
         patch(f"{MOD}.space_migrate_celery") as task, \
         patch(f"{MOD}.KnowledgeService.delete_knowledge_file_in_vector") as del_vec:
        task.delay.side_effect = RuntimeError("broker down")
        with pytest.raises(RuntimeError):
            await svc.delete_space(1)
        assert upd.call_count == 2
        last = upd.call_args_list[-1]
        assert last.kwargs.get("state") == KnowledgeState.PUBLISHED
        del_vec.assert_not_called()         # 真正的清理流程未被触发


@pytest.mark.asyncio
async def test_block_branch_raises():
    from bisheng.common.errcode.knowledge_space import DepartmentSpaceDeleteForbiddenError
    svc = _svc()
    with patch(f"{MOD}.KnowledgeDao.aquery_by_id", new=AsyncMock(return_value=_space())), \
         patch(f"{MOD}.KnowledgeSpaceScopeDao.aget_by_space_id", new=AsyncMock(return_value=None)), \
         patch(f"{MOD}.FreeSpaceMigrationService.pre_delete_guard",
               new=AsyncMock(return_value=MigrationDecision("block", reason="department_space_forbidden"))):
        with pytest.raises(Exception):
            await svc.delete_space(1)


@pytest.mark.asyncio
async def test_migrate_free_space_false_skips_guard():
    svc = _svc()
    guard = AsyncMock()
    with patch(f"{MOD}.KnowledgeDao.aquery_by_id", new=AsyncMock(return_value=_space())), \
         patch(f"{MOD}.KnowledgeSpaceScopeDao.aget_by_space_id", new=AsyncMock(return_value=None)), \
         patch(f"{MOD}.FreeSpaceMigrationService.pre_delete_guard", new=guard), \
         patch(f"{MOD}.KnowledgeService.delete_knowledge_file_in_vector"), \
         patch(f"{MOD}.KnowledgeService.delete_knowledge_file_in_minio"), \
         patch(f"{MOD}.KnowledgeDao.async_delete_knowledge", new=AsyncMock()), \
         patch(f"{MOD}.KnowledgeSpaceContentStat.enqueue_space_delete_stat_async", new=AsyncMock()), \
         patch.object(svc, "_send_space_event_notification", new=AsyncMock()), \
         patch(f"{MOD}.SpaceChannelMemberDao.async_get_members_by_space", new=AsyncMock(return_value=[])), \
         patch.object(svc, "_cleanup_resource_tuples", new=AsyncMock()), \
         patch(f"{MOD}.SpaceChannelMemberDao.clean_space_member", new=AsyncMock()), \
         patch(f"{MOD}.KnowledgeSpaceTagLibraryDao.adelete_private_for_knowledge", new=AsyncMock()), \
         patch(f"{MOD}.KnowledgeAuditTelemetryService.audit_delete_knowledge_space", new=AsyncMock()), \
         patch(f"{MOD}.KnowledgeAuditTelemetryService.telemetry_delete_knowledge"), \
         patch("bisheng.channel.domain.models.channel_knowledge_sync.ChannelKnowledgeSyncDao.adelete_by_space_id",
               new=AsyncMock()):
        await svc.delete_space(1, migrate_free_space=False)
        guard.assert_not_called()          # 跳过判定

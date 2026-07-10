"""个人知识库仅对本人可见：admin(全局超管)也只应在「个人知识库」栏目看到自己的库。

复现 bug：_list_accessible_spaces 对 admin 返回全系统空间(list_accessible_ids=None 分支)，
若分组/按级别接口不按 owner 过滤，admin 会看到别人的 {用户名}的知识库。
"""

import pytest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from bisheng.knowledge.domain.models.knowledge import Knowledge, KnowledgeTypeEnum
from bisheng.knowledge.domain.models.knowledge_space_scope import KnowledgeSpaceLevelEnum
from bisheng.knowledge.domain.services.knowledge_space_service import KnowledgeSpaceService

PERSONAL = KnowledgeSpaceLevelEnum.PERSONAL
PUBLIC = KnowledgeSpaceLevelEnum.PUBLIC


def _svc(user_id=1):
    svc = KnowledgeSpaceService.__new__(KnowledgeSpaceService)
    svc.login_user = type("U", (), {"user_id": user_id, "user_name": "admin", "tenant_id": 1})()
    svc.request = None
    return svc


def _space(sid, user_id, level, is_favorite=False):
    return SimpleNamespace(id=sid, user_id=user_id, space_level=level, is_favorite=is_favorite)


def _mixed_spaces():
    return [
        _space(117, 1, PERSONAL, is_favorite=True),  # admin 自己的收藏
        _space(149, 1, PERSONAL),                    # admin 自己的默认库
        _space(150, 23, PERSONAL),                   # gzx01 的库 -> 应过滤
        _space(152, 24, PERSONAL),                   # gzx02 的库 -> 应过滤
        _space(10, 99, PUBLIC),                      # 公共库(他人创建) -> 保留
    ]


@pytest.mark.asyncio
async def test_grouped_personal_spaces_only_current_user_owned():
    svc = _svc(user_id=1)
    with patch.object(KnowledgeSpaceService, "_ensure_personal_spaces", new=AsyncMock()), \
         patch.object(KnowledgeSpaceService, "_list_accessible_spaces",
                      new=AsyncMock(return_value=_mixed_spaces())):
        grouped = await svc.get_grouped_spaces()

    assert {s.id for s in grouped.personal_spaces} == {117, 149}
    # 公共/部门/团队 不受影响
    assert {s.id for s in grouped.public_spaces} == {10}


@pytest.mark.asyncio
async def test_level_personal_returns_only_the_two_fixed_spaces_without_accessible_space_lookup():
    svc = _svc(user_id=1)
    favorite = Knowledge(id=117, name="我的收藏", user_id=1,
                         type=KnowledgeTypeEnum.SPACE.value, is_favorite=True)
    default = Knowledge(id=149, name="admin的知识库", user_id=1,
                        type=KnowledgeTypeEnum.SPACE.value)
    accessible_spaces = AsyncMock(return_value=_mixed_spaces())
    with patch.object(KnowledgeSpaceService, "_ensure_personal_spaces",
                      new=AsyncMock(return_value=(favorite, default))), \
         patch("bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeFileDao.async_count_success_files_batch",
               new=AsyncMock(return_value={117: 3, 149: 5})), \
         patch.object(KnowledgeSpaceService, "_list_accessible_spaces", new=accessible_spaces):
        result = await svc.get_spaces_by_level(KnowledgeSpaceLevelEnum.PERSONAL)

    assert {s.id for s in result} == {117, 149}
    assert [s.id for s in result] == [117, 149]
    assert [s.file_num for s in result] == [3, 5]
    accessible_spaces.assert_not_awaited()


@pytest.mark.asyncio
async def test_level_public_unaffected_by_owner_filter():
    """按级别取 公共库 时，不应因 owner 过滤而丢失他人创建的公共库。"""
    svc = _svc(user_id=1)
    with patch.object(KnowledgeSpaceService, "_ensure_personal_spaces", new=AsyncMock()), \
         patch.object(KnowledgeSpaceService, "_list_accessible_spaces",
                      new=AsyncMock(return_value=_mixed_spaces())):
        result = await svc.get_spaces_by_level(KnowledgeSpaceLevelEnum.PUBLIC)

    assert {s.id for s in result} == {10}

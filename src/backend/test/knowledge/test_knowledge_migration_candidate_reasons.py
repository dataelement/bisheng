from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bisheng.knowledge.domain.services.knowledge_migration_service import KnowledgeMigrationService


@pytest.mark.parametrize(
    "file_type,status,entry_type,entry_status,reason",
    [
        (1, 1, None, None, "正在解析, 暂不可迁移"),
        (1, 3, None, None, "解析失败, 暂不可迁移"),
        (1, 4, None, None, "正在重建, 暂不可迁移"),
        (1, 5, None, None, "等待解析, 暂不可迁移"),
        (1, 6, None, None, "解析超时, 暂不可迁移"),
        (1, 7, None, None, "内容违规, 不可迁移"),
        (1, 99, None, None, "当前文件状态不支持迁移"),
        (1, 2, "publish", "active", "发布入口, 请从原始文件所在库迁移"),
        (1, 3, "share", "active", "共享入口, 请从原始文件所在库迁移"),
        (1, 2, "projection_tombstone", "invalid", "已失效的入口, 不可迁移"),
        (1, 2, "manager", "preparing", "管理入口准备中, 暂不可迁移"),
        (1, 2, "manager", "deleting", "管理入口删除中, 不可迁移"),
        (1, 2, "manager", "invalid", "管理入口已失效, 不可迁移"),
        (1, 2, "manager", None, "管理入口尚未生效, 暂不可迁移"),
        (1, 2, "manager", "active", None),
        (1, 2, None, None, None),
        (0, 1, None, None, None),
    ],
)
async def test_migration_picker_explains_unavailable_files(file_type, status, entry_type, entry_status, reason):
    item = SimpleNamespace(
        id=100, file_name="document.pdf", file_type=file_type,
        status=status, entry_type=entry_type, entry_status=entry_status,
    )
    repository = SimpleNamespace(
        find_spaces_by_ids=AsyncMock(return_value=[SimpleNamespace(id=10)]),
        list_children=AsyncMock(return_value=[SimpleNamespace(file=item, has_children=False)]),
    )
    service = KnowledgeMigrationService(repository=None, source_repository=repository, dispatcher=None)
    result = await service.list_children(
        SimpleNamespace(is_admin=True), space_id=10, parent_id=None,
        cursor=None, page_size=50, purpose="source",
    )
    assert result["data"][0]["selectable"] is (reason is None)
    assert result["data"][0]["unavailable_reason"] == reason

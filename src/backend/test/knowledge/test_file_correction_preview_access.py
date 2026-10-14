"""纠错打开判定: 预览能过就不要再卡文件级 view_file."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

from bisheng.knowledge.domain.models.knowledge import KnowledgeState
from bisheng.knowledge.domain.models.knowledge_space_scope import KnowledgeSpaceLevelEnum
from bisheng.knowledge.domain.services.knowledge_file_correction_preview_access import (
    user_may_preview_file,
)
from bisheng.permission.domain.services.permission_service import PermissionService


def _file():
    return SimpleNamespace(id=9, knowledge_id=3)


def _knowledge():
    return SimpleNamespace(
        is_favorite=False, state=int(KnowledgeState.PUBLISHED.value) if hasattr(KnowledgeState, "PUBLISHED") else 1
    )


def _scope(level: str):
    return SimpleNamespace(level=level)


async def test_department_open_grant_allows_without_view_file(monkeypatch):
    monkeypatch.setattr(PermissionService, "check", AsyncMock(return_value=False))
    monkeypatch.setattr(
        "bisheng.knowledge.domain.services.knowledge_file_correction_preview_access._space_membership_can_view",
        AsyncMock(return_value=False),
    )
    monkeypatch.setattr(
        "bisheng.knowledge.domain.services.knowledge_file_correction_preview_access._department_or_clinic_can_open",
        AsyncMock(return_value=True),
    )

    allowed = await user_may_preview_file(
        SimpleNamespace(user_id=4),
        _file(),
        _knowledge(),
        _scope(KnowledgeSpaceLevelEnum.DEPARTMENT.value),
    )

    assert allowed is True


async def test_view_denied_when_preview_gates_all_fail(monkeypatch):
    monkeypatch.setattr(PermissionService, "check", AsyncMock(return_value=False))
    monkeypatch.setattr(
        "bisheng.knowledge.domain.services.knowledge_file_correction_preview_access._space_membership_can_view",
        AsyncMock(return_value=False),
    )
    monkeypatch.setattr(
        "bisheng.knowledge.domain.services.knowledge_file_correction_preview_access._department_or_clinic_can_open",
        AsyncMock(return_value=False),
    )

    allowed = await user_may_preview_file(
        SimpleNamespace(user_id=4),
        _file(),
        _knowledge(),
        _scope(KnowledgeSpaceLevelEnum.DEPARTMENT.value),
    )

    assert allowed is False

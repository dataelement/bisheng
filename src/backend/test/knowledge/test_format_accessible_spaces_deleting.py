"""Retiring spaces must disappear from sidebar lists immediately."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from bisheng.knowledge.domain.models.knowledge import (
    AuthTypeEnum,
    Knowledge,
    KnowledgeState,
    KnowledgeTypeEnum,
)
from bisheng.knowledge.domain.services.knowledge_space_service import KnowledgeSpaceService


def _service(*, user_id: int = 11) -> KnowledgeSpaceService:
    service = KnowledgeSpaceService.__new__(KnowledgeSpaceService)
    service.login_user = SimpleNamespace(user_id=user_id, is_admin=lambda: False)
    return service


def _space(*, space_id: int, user_id: int, state: int) -> Knowledge:
    return Knowledge(
        id=space_id,
        name=f"space-{space_id}",
        user_id=user_id,
        type=KnowledgeTypeEnum.SPACE.value,
        state=state,
        auth_type=AuthTypeEnum.PRIVATE,
    )


@pytest.mark.asyncio
async def test_format_accessible_spaces_excludes_deleting_state():
    """Delete API flips state to DELETING then returns success; lists must hide it."""
    service = _service(user_id=11)
    published = _space(space_id=1, user_id=11, state=KnowledgeState.PUBLISHED.value)
    retiring = _space(space_id=2, user_id=11, state=KnowledgeState.DELETING.value)

    with (
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeDao.async_get_spaces_by_ids",
            new=AsyncMock(return_value=[published, retiring]),
        ),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeFileDao.async_count_success_files_batch",
            new=AsyncMock(return_value={1: 0}),
        ),
        patch.object(
            service,
            "_decorate_department_metadata",
            new=AsyncMock(side_effect=lambda spaces: spaces),
        ),
        patch.object(
            service,
            "_attach_space_reorder_flags",
            new=AsyncMock(side_effect=lambda spaces: spaces),
        ),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeSpacePinService.apply_pins",
            new=AsyncMock(side_effect=lambda spaces, _user_id: spaces),
        ),
    ):
        result = await service._format_accessible_spaces(
            [1, 2],
            "update_time",
            memberships=[],
            required_permission_id="view_space",
            include_file_count=False,
        )

    assert [space.id for space in result] == [1]

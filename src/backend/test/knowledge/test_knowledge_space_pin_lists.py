import inspect
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from bisheng.knowledge.domain.models.knowledge_space_scope import KnowledgeSpaceLevelEnum
from bisheng.knowledge.domain.services.knowledge_space_pin_service import KnowledgeSpacePinService
from bisheng.knowledge.domain.services.knowledge_space_service import KnowledgeSpaceService


def _service() -> KnowledgeSpaceService:
    service = KnowledgeSpaceService.__new__(KnowledgeSpaceService)
    service.login_user = SimpleNamespace(user_id=7)
    return service


def test_space_list_formatters_no_longer_read_membership_pin_state():
    accessible_source = inspect.getsource(KnowledgeSpaceService._format_accessible_spaces)
    member_source = inspect.getsource(KnowledgeSpaceService._format_member_spaces)

    assert "member_conf.is_pinned" not in accessible_source
    assert "member_conf.is_pinned" not in member_source
    assert "KnowledgeSpacePinService.apply_pins" in accessible_source
    assert "KnowledgeSpacePinService.apply_pins" in member_source


@pytest.mark.asyncio
async def test_stale_cached_pin_is_reset_before_return():
    service = _service()
    stale_cached = [
        SimpleNamespace(
            id=10,
            space_level=KnowledgeSpaceLevelEnum.PUBLIC,
            is_pinned=True,
        )
    ]
    with (
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.SpaceListCache.get",
            new=AsyncMock(return_value=stale_cached),
        ),
        patch.object(
            KnowledgeSpacePinService,
            "list_pinned_space_ids",
            new=AsyncMock(return_value=[]),
        ) as list_pins,
    ):
        result = await service._list_accessible_spaces()

    assert result[0].is_pinned is False
    list_pins.assert_awaited_once_with(7, {10})


@pytest.mark.asyncio
async def test_personal_residual_link_never_marks_list_item_pinned():
    spaces = [
        SimpleNamespace(
            id=10,
            space_level=KnowledgeSpaceLevelEnum.PERSONAL,
            is_pinned=True,
        )
    ]
    with patch.object(
        KnowledgeSpacePinService,
        "list_pinned_space_ids",
        new=AsyncMock(return_value=[10]),
    ):
        result = await KnowledgeSpacePinService.apply_pins(spaces, user_id=7)

    assert result[0].is_pinned is False

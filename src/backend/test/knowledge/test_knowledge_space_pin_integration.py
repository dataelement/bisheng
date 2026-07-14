from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from bisheng.common.errcode.knowledge_space import (
    SpacePermissionDeniedError,
    SpacePersonalPinForbiddenError,
)
from bisheng.knowledge.domain.models.knowledge import KnowledgeTypeEnum
from bisheng.knowledge.domain.models.knowledge_space_scope import KnowledgeSpaceLevelEnum
from bisheng.knowledge.domain.services.knowledge_space_service import KnowledgeSpaceService


def _service() -> KnowledgeSpaceService:
    service = KnowledgeSpaceService.__new__(KnowledgeSpaceService)
    service.login_user = SimpleNamespace(user_id=7)
    return service


@pytest.mark.asyncio
@pytest.mark.parametrize("is_pinned", [True, False])
async def test_personal_space_rejects_pin_and_unpin_without_writing(is_pinned: bool):
    service = _service()
    space = SimpleNamespace(id=10, type=KnowledgeTypeEnum.SPACE.value)
    scope = SimpleNamespace(level=KnowledgeSpaceLevelEnum.PERSONAL)

    with (
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeDao.aquery_by_id",
            new=AsyncMock(return_value=space),
        ),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeSpaceScopeDao.aget_by_space_id",
            new=AsyncMock(return_value=scope),
        ),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeSpacePinService.set_pin",
            new=AsyncMock(),
        ) as set_pin,
    ):
        with pytest.raises(SpacePersonalPinForbiddenError):
            await service.pin_space(10, is_pinned)

    set_pin.assert_not_awaited()


@pytest.mark.asyncio
async def test_visible_unsubscribed_public_space_can_be_pinned():
    service = _service()
    space = SimpleNamespace(id=10, type=KnowledgeTypeEnum.SPACE.value)
    scope = SimpleNamespace(level=KnowledgeSpaceLevelEnum.PUBLIC)

    with (
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeDao.aquery_by_id",
            new=AsyncMock(return_value=space),
        ),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeSpaceScopeDao.aget_by_space_id",
            new=AsyncMock(return_value=scope),
        ),
        patch.object(service, "get_public_spaces", new=AsyncMock(return_value=[{"id": 10}])),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeSpacePinService.set_pin",
            new=AsyncMock(return_value=True),
        ) as set_pin,
    ):
        assert await service.pin_space(10, True) is True

    set_pin.assert_awaited_once_with(
        user_id=7,
        space_id=10,
        visible_space_ids={10},
        is_pinned=True,
    )


@pytest.mark.asyncio
async def test_invisible_department_space_cannot_be_pinned():
    service = _service()
    space = SimpleNamespace(id=10, type=KnowledgeTypeEnum.SPACE.value)
    scope = SimpleNamespace(level=KnowledgeSpaceLevelEnum.DEPARTMENT)

    with (
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeDao.aquery_by_id",
            new=AsyncMock(return_value=space),
        ),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeSpaceScopeDao.aget_by_space_id",
            new=AsyncMock(return_value=scope),
        ),
        patch.object(service, "get_spaces_by_level", new=AsyncMock(return_value=[])),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeSpacePinService.set_pin",
            new=AsyncMock(),
        ) as set_pin,
    ):
        with pytest.raises(SpacePermissionDeniedError):
            await service.pin_space(10, True)

    set_pin.assert_not_awaited()


@pytest.mark.asyncio
async def test_cached_base_list_is_decorated_on_every_read():
    service = _service()
    cached = [SimpleNamespace(id=10, space_level=KnowledgeSpaceLevelEnum.PUBLIC, is_pinned=False)]
    decorated = [SimpleNamespace(id=10, space_level=KnowledgeSpaceLevelEnum.PUBLIC, is_pinned=True)]

    with (
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.SpaceListCache.get",
            new=AsyncMock(return_value=cached),
        ),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeSpacePinService.apply_pins",
            new=AsyncMock(return_value=decorated),
        ) as apply_pins,
    ):
        result = await service._list_accessible_spaces()

    assert result == decorated
    apply_pins.assert_awaited_once_with(cached, 7)

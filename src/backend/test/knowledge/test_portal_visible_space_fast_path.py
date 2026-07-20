from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from bisheng.knowledge.domain.models.knowledge import AuthTypeEnum, KnowledgeTypeEnum
from bisheng.knowledge.domain.models.knowledge_space_scope import KnowledgeSpaceLevelEnum
from bisheng.knowledge.domain.services.knowledge_space_service import KnowledgeSpaceService
from bisheng.permission.domain.knowledge_space_permission_template import (
    default_permission_ids_for_relation,
)


def _space(space_id: int) -> SimpleNamespace:
    return SimpleNamespace(
        id=space_id,
        type=KnowledgeTypeEnum.SPACE.value,
        user_id=99,
        is_released=False,
        auth_type=AuthTypeEnum.PRIVATE,
    )


@pytest.mark.asyncio
async def test_public_spaces_skip_user_permission_resolution() -> None:
    service = object.__new__(KnowledgeSpaceService)
    service.login_user = SimpleNamespace(user_id=7, is_admin=lambda: False)
    public_space = _space(10)
    private_space = _space(11)
    service._resolve_shougang_portal_search_space_ids = AsyncMock(return_value=[10, 11])
    service._get_shougang_portal_public_space_ids = AsyncMock(return_value={10})
    service._get_effective_permission_ids = AsyncMock(return_value={"view_space"})

    with patch(
        "bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeDao.async_get_spaces_by_ids",
        new_callable=AsyncMock,
        return_value=[public_space, private_space],
    ):
        spaces, download_map = await service._compute_shougang_portal_visible_search_spaces(
            [10, 11],
            None,
        )

    assert [space.id for space in spaces] == [10, 11]
    assert download_map == {
        10: "download_file" in default_permission_ids_for_relation("viewer"),
        11: False,
    }
    service._get_shougang_portal_public_space_ids.assert_awaited_once_with(
        [10, 11],
        spaces=[public_space, private_space],
    )
    service._get_effective_permission_ids.assert_awaited_once_with("knowledge_space", 11)


@pytest.mark.asyncio
async def test_non_public_spaces_still_require_view_permission() -> None:
    service = object.__new__(KnowledgeSpaceService)
    service.login_user = SimpleNamespace(user_id=7, is_admin=lambda: False)
    private_space = _space(11)
    service._resolve_shougang_portal_search_space_ids = AsyncMock(return_value=[11])
    service._get_shougang_portal_public_space_ids = AsyncMock(return_value=set())
    service._get_effective_permission_ids = AsyncMock(return_value=set())

    with patch(
        "bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeDao.async_get_spaces_by_ids",
        new_callable=AsyncMock,
        return_value=[private_space],
    ):
        spaces, download_map = await service._compute_shougang_portal_visible_search_spaces(
            [11],
            None,
        )

    assert spaces == []
    assert download_map == {}
    service._get_effective_permission_ids.assert_awaited_once_with("knowledge_space", 11)


@pytest.mark.asyncio
async def test_many_public_spaces_use_one_scope_lookup_and_no_user_permissions() -> None:
    service = object.__new__(KnowledgeSpaceService)
    service.login_user = SimpleNamespace(user_id=7, is_admin=lambda: False)
    space_ids = list(range(1, 171))
    spaces = [_space(space_id) for space_id in space_ids]
    scopes = {space_id: SimpleNamespace(level=KnowledgeSpaceLevelEnum.PUBLIC) for space_id in space_ids}
    service._resolve_shougang_portal_search_space_ids = AsyncMock(return_value=space_ids)
    service._get_effective_permission_ids = AsyncMock(
        side_effect=AssertionError("public spaces must not use user permissions")
    )

    with (
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeDao.async_get_spaces_by_ids",
            new_callable=AsyncMock,
            return_value=spaces,
        ),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeSpaceScopeDao.aget_map_by_space_ids",
            new_callable=AsyncMock,
            return_value=scopes,
        ) as mock_scope_lookup,
    ):
        visible_spaces, download_map = await service._compute_shougang_portal_visible_search_spaces(
            space_ids,
            None,
        )

    assert [space.id for space in visible_spaces] == space_ids
    assert download_map == dict.fromkeys(space_ids, True)
    mock_scope_lookup.assert_awaited_once_with(space_ids)
    service._get_effective_permission_ids.assert_not_awaited()

from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from bisheng.common.errcode.knowledge_space import SpacePinLimitError
from bisheng.knowledge.domain.models.knowledge_space_scope import KnowledgeSpaceLevelEnum
from bisheng.knowledge.domain.services.knowledge_space_pin_service import KnowledgeSpacePinService


@pytest.mark.asyncio
async def test_apply_pins_intersects_visible_ids_forces_personal_false_and_keeps_stable_order():
    spaces = [
        SimpleNamespace(id=1, space_level=KnowledgeSpaceLevelEnum.PUBLIC, is_pinned=False),
        SimpleNamespace(id=2, space_level=KnowledgeSpaceLevelEnum.PUBLIC, is_pinned=False),
        SimpleNamespace(id=3, space_level=KnowledgeSpaceLevelEnum.PERSONAL, is_pinned=True),
        SimpleNamespace(id=4, space_level=KnowledgeSpaceLevelEnum.PUBLIC, is_pinned=False),
    ]
    with patch.object(
        KnowledgeSpacePinService,
        "get_pinned_space_ids",
        new=AsyncMock(return_value={2, 3, 4, 999}),
    ) as get_pins:
        result = await KnowledgeSpacePinService.apply_pins(spaces, user_id=7)

    get_pins.assert_awaited_once_with(7, {1, 2, 3, 4})
    assert [item.id for item in result] == [2, 4, 1, 3]
    assert [item.is_pinned for item in result] == [True, True, False, False]


@pytest.mark.asyncio
async def test_apply_pins_supports_public_list_dicts():
    spaces = [
        {"id": 1, "space_level": "public"},
        {"id": 2, "space_level": "public"},
    ]
    with patch.object(
        KnowledgeSpacePinService,
        "get_pinned_space_ids",
        new=AsyncMock(return_value={2}),
    ):
        result = await KnowledgeSpacePinService.apply_pins(spaces, user_id=7)

    assert [item["id"] for item in result] == [2, 1]
    assert [item["is_pinned"] for item in result] == [True, False]


@pytest.mark.asyncio
async def test_set_pin_rejects_sixth_visible_pin_without_writing():
    repository = SimpleNamespace(
        lock_user=AsyncMock(),
        list_for_user=AsyncMock(return_value=set(range(1, 6))),
        add_pin=AsyncMock(),
        remove_pin=AsyncMock(),
    )
    session = SimpleNamespace(commit=AsyncMock())

    @asynccontextmanager
    async def fake_session():
        yield session

    with (
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_pin_service.get_async_db_session",
            side_effect=fake_session,
        ),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_pin_service.KnowledgeSpacePinRepositoryImpl",
            return_value=repository,
        ),
    ):
        with pytest.raises(SpacePinLimitError):
            await KnowledgeSpacePinService.set_pin(
                user_id=7,
                space_id=6,
                visible_space_ids=set(range(1, 7)),
                is_pinned=True,
            )

    repository.lock_user.assert_awaited_once_with(7)
    repository.add_pin.assert_not_awaited()
    session.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_set_pin_is_idempotent_for_existing_pin_even_at_limit():
    repository = SimpleNamespace(
        lock_user=AsyncMock(),
        list_for_user=AsyncMock(return_value=set(range(1, 6))),
        add_pin=AsyncMock(),
        remove_pin=AsyncMock(),
    )
    session = SimpleNamespace(commit=AsyncMock())

    @asynccontextmanager
    async def fake_session():
        yield session

    with (
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_pin_service.get_async_db_session",
            side_effect=fake_session,
        ),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_pin_service.KnowledgeSpacePinRepositoryImpl",
            return_value=repository,
        ),
    ):
        result = await KnowledgeSpacePinService.set_pin(
            user_id=7,
            space_id=5,
            visible_space_ids=set(range(1, 6)),
            is_pinned=True,
        )

    assert result is True
    repository.add_pin.assert_not_awaited()

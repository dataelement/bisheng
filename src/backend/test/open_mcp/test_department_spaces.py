from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bisheng.knowledge.domain.services import knowledge_space_service as space_module
from bisheng.knowledge.domain.services.department_knowledge_space_service import DepartmentKnowledgeSpaceService
from bisheng.knowledge.domain.services.knowledge_space_service import KnowledgeSpaceService


def _space(space_id, name="s", user_id=1):
    return SimpleNamespace(
        id=space_id, name=f"{name}{space_id}", user_id=user_id, update_time=None, create_time=None,
        user_name=None, actions=None,
    )


def _service(monkeypatch, *, created, joined, department):
    service = KnowledgeSpaceService.__new__(KnowledgeSpaceService)
    service.request = object()
    service.login_user = SimpleNamespace(user_id=1)
    service.get_my_created_spaces = AsyncMock(return_value=created)
    service.get_my_followed_spaces = AsyncMock(return_value=joined)
    service._get_effective_actions = AsyncMock(return_value={"view"})
    monkeypatch.setattr(space_module.UserDao, "aget_user_by_ids", AsyncMock(return_value=[]))
    fetch = AsyncMock(return_value=department)
    monkeypatch.setattr(DepartmentKnowledgeSpaceService, "get_user_department_spaces", fetch)
    return service, fetch


@pytest.mark.asyncio
async def test_default_listing_stays_frozen_and_never_reads_department_spaces(monkeypatch):
    service, fetch = _service(monkeypatch, created=[_space(1)], joined=[_space(2)], department=[_space(3)])

    page = await service.alist_mine_and_joined_cursor(page_size=10)

    assert sorted(item.id for item in page.data) == [1, 2]
    fetch.assert_not_awaited()


@pytest.mark.asyncio
async def test_include_department_adds_visible_department_spaces_without_duplicates(monkeypatch):
    service, fetch = _service(
        monkeypatch,
        created=[_space(1)],
        joined=[_space(2)],
        department=[_space(3), _space(1, name="dept-copy")],
    )

    page = await service.alist_mine_and_joined_cursor(page_size=10, include_department=True)

    by_id = {item.id: item for item in page.data}
    assert sorted(by_id) == [1, 2, 3]
    assert by_id[1].name == "s1", "the created space wins over its department copy"
    fetch.assert_awaited_once()
    assert by_id[3].actions == ["view"]


@pytest.mark.asyncio
async def test_department_cursor_is_not_interchangeable_with_the_plain_listing(monkeypatch):
    service, _ = _service(
        monkeypatch, created=[_space(i) for i in range(1, 4)], joined=[], department=[_space(10)]
    )

    first = await service.alist_mine_and_joined_cursor(page_size=2, include_department=True)

    assert first.has_more is True
    from bisheng.common.errcode.knowledge_space import KnowledgeSpaceInvalidCursorError

    with pytest.raises(KnowledgeSpaceInvalidCursorError):
        await service.alist_mine_and_joined_cursor(page_size=2, cursor=first.next_cursor)

    second = await service.alist_mine_and_joined_cursor(
        page_size=2, cursor=first.next_cursor, include_department=True
    )
    assert second.has_more is False
    assert len(first.data) + len(second.data) == 4

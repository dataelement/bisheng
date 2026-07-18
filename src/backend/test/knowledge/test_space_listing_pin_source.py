"""F037 — space listings derive is_pinned from the decoupled pin table, not from
the membership row's legacy is_pinned column.

AC1: a pinned space sorts first with is_pinned=True.
AC5 (decoupling): pin state is read from KnowledgeSpaceUserPinDao even when the
member row's own is_pinned is False (or there is no member row at all).
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from bisheng.knowledge.domain.services.knowledge_space_service import KnowledgeSpaceService

_KS = "bisheng.knowledge.domain.services.knowledge_space_service"


class _User:
    user_id = 5
    tenant_id = 1

    def is_admin(self):
        return False


def _service():
    return KnowledgeSpaceService(request=None, login_user=_User())


def _space(space_id: int, name: str, user_id: int = 5):
    """Minimal stand-in for a Knowledge row: only what the formatters touch."""
    return SimpleNamespace(
        id=space_id,
        user_id=user_id,
        model_dump=lambda: {"id": space_id, "name": name, "user_id": user_id},
    )


async def test_accessible_spaces_pin_comes_from_pin_table_and_sorts_first():
    service = _service()
    spaces = [_space(100, "alpha"), _space(200, "beta")]  # both creator-owned (user 5)

    with (
        patch(f"{_KS}.KnowledgeDao.async_get_spaces_by_ids", new=AsyncMock(return_value=spaces)),
        patch(
            f"{_KS}.KnowledgeSpaceUserPinDao.list_pinned_space_ids",
            new=AsyncMock(return_value={200}),
        ),
        patch.object(service, "_decorate_department_metadata", new=AsyncMock(side_effect=lambda x: x)),
    ):
        result = await service._format_accessible_spaces([100, 200], "name")

    assert [r.id for r in result] == [200, 100]  # pinned first
    by_id = {r.id: r.is_pinned for r in result}
    assert by_id == {200: True, 100: False}


async def test_member_spaces_pin_decoupled_from_member_row():
    """A member row with is_pinned=False must still render as pinned when the
    user pinned that space in the new table."""
    service = _service()
    member = SimpleNamespace(
        business_id="300",
        is_pinned=False,  # legacy column intentionally stale/false
        user_role="member",
        status="ACTIVE",
    )

    with (
        patch(
            f"{_KS}.KnowledgeDao.async_get_spaces_by_ids",
            new=AsyncMock(return_value=[_space(300, "gamma", user_id=9)]),
        ),
        patch(
            f"{_KS}.KnowledgeSpaceUserPinDao.list_pinned_space_ids",
            new=AsyncMock(return_value={300}),
        ),
        patch.object(service, "_decorate_department_metadata", new=AsyncMock(side_effect=lambda x: x)),
    ):
        result = await service._format_member_spaces([member], "name")

    assert len(result) == 1
    assert result[0].id == 300
    assert result[0].is_pinned is True

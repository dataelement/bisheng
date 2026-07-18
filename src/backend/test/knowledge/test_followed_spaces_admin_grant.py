"""Admin users must still see knowledge spaces they were directly authorized to in the
followed list — mirror of the channel fix.

PermissionService.list_accessible_ids returns None ("can read all") for admins, so
get_my_followed_spaces would otherwise drop spaces an admin was directly granted (ReBAC +
binding, no membership row). The fix recovers them from the admin's direct space bindings.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from bisheng.knowledge.domain.services.knowledge_space_service import KnowledgeSpaceService

_KS = "bisheng.knowledge.domain.services.knowledge_space_service"
_RP = "bisheng.permission.api.endpoints.resource_permission._get_bindings"


class _Admin:
    user_id = 7
    tenant_id = 1

    def is_admin(self):
        return True


def _service():
    return KnowledgeSpaceService(request=None, login_user=_Admin())


@pytest.mark.asyncio
async def test_directly_granted_space_ids_extracts_user_space_bindings():
    service = _service()
    bindings = [
        {"resource_type": "knowledge_space", "resource_id": "42", "subject_type": "user", "subject_id": 7},
        {"resource_type": "knowledge_space", "resource_id": "43", "subject_type": "department", "subject_id": 3},
        {"resource_type": "channel", "resource_id": "99", "subject_type": "user", "subject_id": 7},
        {"resource_type": "knowledge_space", "resource_id": "44", "subject_type": "user", "subject_id": 99},
    ]
    with patch(_RP, new=AsyncMock(return_value=bindings)):
        ids = await service._directly_granted_space_ids(7)

    assert ids == ["42"]


@pytest.mark.asyncio
async def test_admin_followed_spaces_includes_directly_authorized_space():
    service = _service()

    captured: dict = {}

    async def _fmt(space_ids, order_by, **kwargs):
        captured["space_ids"] = set(space_ids)
        return []

    service._format_accessible_spaces = _fmt

    bindings = [{"resource_type": "knowledge_space", "resource_id": "42", "subject_type": "user", "subject_id": 7}]

    with patch(
        f"{_KS}.SpaceChannelMemberDao.async_get_user_followed_members",
        new=AsyncMock(return_value=[]),
    ), patch(_RP, new=AsyncMock(return_value=bindings)):
        await service.get_my_followed_spaces()

    assert 42 in captured["space_ids"]

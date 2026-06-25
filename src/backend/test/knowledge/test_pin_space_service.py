"""F037 — KnowledgeSpaceService.pin_space: permission-gated, writes the decoupled
per-user pin table instead of mutating membership rows.

AC1/AC7 pin (idempotent via DAO), AC3 unpin, AC4 permission gate (no write).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from bisheng.knowledge.domain.services.knowledge_space_service import KnowledgeSpaceService

_KS = "bisheng.knowledge.domain.services.knowledge_space_service"


class _User:
    user_id = 5
    tenant_id = 1

    def is_admin(self):
        return False


def _service():
    return KnowledgeSpaceService(request=None, login_user=_User())


async def test_pin_requires_read_permission_before_writing():
    """AC4: no view_space permission → error propagates, nothing written."""
    service = _service()
    boom = RuntimeError("denied")
    with (
        patch.object(service, "_require_read_permission", new=AsyncMock(side_effect=boom)),
        patch(f"{_KS}.KnowledgeSpaceUserPinDao") as dao,
    ):
        with pytest.raises(RuntimeError):
            await service.pin_space(42, is_pinned=True)
    dao.pin.assert_not_called()
    dao.unpin.assert_not_called()


async def test_pin_writes_pin_after_permission_check():
    """AC1: is_pinned=True → DAO.pin(user, space) after read-permission check."""
    service = _service()
    with (
        patch.object(service, "_require_read_permission", new=AsyncMock()),
        patch(f"{_KS}.KnowledgeSpaceUserPinDao") as dao,
    ):
        dao.pin = AsyncMock()
        dao.unpin = AsyncMock()
        result = await service.pin_space(42, is_pinned=True)
    assert result is True
    dao.pin.assert_awaited_once_with(user_id=5, space_id=42)
    dao.unpin.assert_not_called()


async def test_unpin_removes_pin():
    """AC3: is_pinned=False → DAO.unpin(user, space)."""
    service = _service()
    with (
        patch.object(service, "_require_read_permission", new=AsyncMock()),
        patch(f"{_KS}.KnowledgeSpaceUserPinDao") as dao,
    ):
        dao.pin = AsyncMock()
        dao.unpin = AsyncMock()
        result = await service.pin_space(42, is_pinned=False)
    assert result is True
    dao.unpin.assert_awaited_once_with(user_id=5, space_id=42)
    dao.pin.assert_not_called()

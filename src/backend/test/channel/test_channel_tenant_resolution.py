"""Tenant-status regression coverage for channel authorization candidates."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from bisheng.channel.domain.services.channel_authorization_service import ChannelAuthorizationService


class _User:
    user_id = 7
    tenant_id = 1

    def is_admin(self):
        return False


async def test_resolve_channel_tenant_requires_active_tenant():
    service = ChannelAuthorizationService(
        channel_repository=MagicMock(),
        space_channel_member_repository=MagicMock(),
        membership_sync_service=MagicMock(),
    )

    with (
        patch(
            "bisheng.channel.domain.services.channel_authorization_service.PermissionService._resolve_resource_tenant",
            new_callable=AsyncMock,
            return_value=3,
        ),
        patch(
            "bisheng.database.models.tenant.TenantDao.aget_by_id",
            new_callable=AsyncMock,
            return_value=SimpleNamespace(id=3, status="disabled"),
        ),
    ):
        tenant_id = await service._resolve_channel_tenant("channel-1", _User())

    assert tenant_id is None

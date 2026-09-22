"""Staged uploads must show up in the storage figure the profile card reads.

The upload path charges bytes that are staged but not yet a knowledge file. A
usage number that leaves them out reads as free space the caller cannot use, so
uploads keep failing over quota while the card still shows room.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from bisheng.role.domain.services.quota_service import QuotaService

GB = 1024**3


@pytest.fixture
def quota_context():
    """Strip everything that is not the usage arithmetic under test."""
    with (
        patch.object(QuotaService, "get_tenant_resource_count", new_callable=AsyncMock, return_value=0),
        patch.object(QuotaService, "get_user_resource_count", new_callable=AsyncMock) as user_count,
        patch(
            "bisheng.role.domain.services.quota_service.UserRoleDao.aget_user_roles",
            new_callable=AsyncMock,
            return_value=[],
        ),
        patch(
            "bisheng.role.domain.services.quota_service.TenantDao.aget_by_id",
            new_callable=AsyncMock,
            return_value=SimpleNamespace(quota_config={}),
        ),
    ):
        yield user_count


async def _storage_item(items):
    return next(item for item in items if item.resource_type == "knowledge_space_file")


async def test_staged_uploads_count_towards_the_reported_usage(quota_context):
    quota_context.return_value = 0.8  # GB already committed as knowledge files

    with patch.object(QuotaService, "_reserved_storage_gb", new_callable=AsyncMock, return_value=0.05):
        items = await QuotaService.get_all_effective_quotas(user_id=7, tenant_id=1)

    assert (await _storage_item(items)).user_used == pytest.approx(0.85)


async def test_usage_is_unchanged_when_nothing_is_staged(quota_context):
    quota_context.return_value = 0.8

    with patch.object(QuotaService, "_reserved_storage_gb", new_callable=AsyncMock, return_value=0.0):
        items = await QuotaService.get_all_effective_quotas(user_id=7, tenant_id=1)

    assert (await _storage_item(items)).user_used == pytest.approx(0.8)


async def test_counted_resources_other_than_storage_ignore_reservations(quota_context):
    quota_context.return_value = 3

    with patch.object(QuotaService, "_reserved_storage_gb", new_callable=AsyncMock, return_value=0.05):
        items = await QuotaService.get_all_effective_quotas(user_id=7, tenant_id=1)

    spaces = next(item for item in items if item.resource_type == "knowledge_space")
    assert spaces.user_used == 3


async def test_a_failing_reservation_lookup_never_breaks_the_usage_readout():
    with patch(
        "bisheng.core.database.get_async_db_session",
        side_effect=RuntimeError("database is unreachable"),
    ):
        assert await QuotaService._reserved_storage_gb("user_id", 7) == 0.0

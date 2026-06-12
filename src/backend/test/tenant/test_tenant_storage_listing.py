"""Tests for tenant management list/detail surfacing real storage_used_gb.

Bug 2: ``TenantService.alist_tenants`` / ``aget_tenant`` previously hard-coded
``storage_used_gb=None``, which the platform UI rendered as ``0/X GB``. These
tests verify the values are now sourced from
``QuotaService.get_storage_used_gb_batch`` and rounded to two decimals.
"""

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest


def _make_tenant(
    *, tid: int, name: str, code: str, quota_gb: float | None = None,
    parent_tenant_id: int | None = None,
) -> SimpleNamespace:
    quota_config = {'storage_gb': quota_gb} if quota_gb is not None else None
    fields = {
        'id': tid,
        'tenant_name': name,
        'tenant_code': code,
        'logo': None,
        'status': 'active',
        'parent_tenant_id': parent_tenant_id,
        'quota_config': quota_config,
        'storage_config': None,
        'root_dept_id': None,
        'contact_name': None,
        'contact_phone': None,
        'contact_email': None,
        'create_time': datetime(2026, 5, 1, 12, 0, 0),
        'update_time': datetime(2026, 5, 1, 12, 0, 0),
    }
    obj = SimpleNamespace(**fields)
    # _safe_tenant_dump calls .model_dump(include=...); stub it with the same
    # subset semantics so the service can serialize this fake tenant.
    obj.model_dump = lambda include=None: (
        {k: fields[k] for k in include if k in fields}
        if include else dict(fields)
    )
    return obj


@pytest.mark.asyncio
async def test_alist_tenants_fills_storage_used_gb_from_quota_service():
    from bisheng.tenant.domain.services.tenant_service import TenantService

    tenants = [
        _make_tenant(tid=1, name='Root', code='root', quota_gb=100, parent_tenant_id=None),
        _make_tenant(tid=7, name='Child A', code='ca', quota_gb=1, parent_tenant_id=1),
        _make_tenant(tid=8, name='Child B', code='cb', quota_gb=None, parent_tenant_id=1),
    ]

    with patch(
        'bisheng.tenant.domain.services.tenant_service.TenantDao.alist_tenants',
        new=AsyncMock(return_value=(tenants, len(tenants))),
    ), patch(
        'bisheng.tenant.domain.services.tenant_service.UserDepartmentDao'
        '.acount_users_by_tenant_subtree_batch',
        new=AsyncMock(return_value={1: 5, 7: 2, 8: 0}),
    ), patch(
        'bisheng.tenant.domain.services.tenant_mount_service.display_tenant_code',
        new=lambda code: code,
    ), patch(
        'bisheng.role.domain.services.quota_service.QuotaService'
        '.get_storage_used_gb_batch',
        new=AsyncMock(return_value={1: 12.345, 7: 0.123456, 8: 0.0}),
    ):
        result = await TenantService.alist_tenants(
            keyword=None, status=None, page=1, page_size=20, login_user=None,
        )

    assert result['total'] == 3
    rows = {row['id']: row for row in result['data']}
    assert rows[1]['storage_used_gb'] == 12.35  # rounded to 2 decimals
    assert rows[1]['storage_quota_gb'] == 100
    assert rows[7]['storage_used_gb'] == 0.12
    assert rows[7]['storage_quota_gb'] == 1
    # Tenant without quota config still gets a real used number, quota stays None
    assert rows[8]['storage_used_gb'] == 0.0
    assert rows[8]['storage_quota_gb'] is None


@pytest.mark.asyncio
async def test_alist_tenants_zero_files_returns_zero_not_none():
    """Empty tenants must show ``0/X GB`` rather than ``None/X GB`` so the UI
    progress bar renders correctly (the platform front-end uses
    ``{used || 0}/{quota}GB``)."""
    from bisheng.tenant.domain.services.tenant_service import TenantService

    tenants = [_make_tenant(tid=11, name='Empty', code='e', quota_gb=5)]

    with patch(
        'bisheng.tenant.domain.services.tenant_service.TenantDao.alist_tenants',
        new=AsyncMock(return_value=(tenants, 1)),
    ), patch(
        'bisheng.tenant.domain.services.tenant_service.UserDepartmentDao'
        '.acount_users_by_tenant_subtree_batch',
        new=AsyncMock(return_value={}),
    ), patch(
        'bisheng.tenant.domain.services.tenant_mount_service.display_tenant_code',
        new=lambda code: code,
    ), patch(
        'bisheng.role.domain.services.quota_service.QuotaService'
        '.get_storage_used_gb_batch',
        new=AsyncMock(return_value={}),
    ):
        result = await TenantService.alist_tenants(
            keyword=None, status=None, page=1, page_size=20, login_user=None,
        )

    assert result['data'][0]['storage_used_gb'] == 0.0
    assert result['data'][0]['storage_used_gb'] is not None


@pytest.mark.asyncio
async def test_aset_quota_accepts_decimal_storage_gb():
    """Verifies the PUT path now accepts 0.1~999 with one decimal for storage_gb,
    closing the 24005 round-trip that caused the dialog's silent toast bug."""
    from bisheng.tenant.domain.services.tenant_service import TenantService
    from bisheng.tenant.domain.schemas.tenant_schema import TenantQuotaUpdate

    updated = _make_tenant(tid=5, name='child', code='c5', quota_gb=0.5, parent_tenant_id=1)
    captured: dict = {}

    async def _fake_update(tenant_id, **fields):
        captured['tenant_id'] = tenant_id
        captured['fields'] = fields
        return updated

    with patch(
        'bisheng.tenant.domain.services.tenant_service.TenantDao.aupdate_tenant',
        new=_fake_update,
    ):
        result = await TenantService.aset_quota(
            tenant_id=5,
            data=TenantQuotaUpdate(quota_config={'storage_gb': 0.5}),
            login_user=None,
        )

    assert captured['tenant_id'] == 5
    assert captured['fields']['quota_config'] == {'storage_gb': 0.5}
    assert result['quota_config'] == {'storage_gb': 0.5}


@pytest.mark.asyncio
async def test_aset_quota_rejects_invalid_decimal_storage_gb():
    """Two-decimal places must still be rejected at the service boundary."""
    from bisheng.common.errcode.role import QuotaConfigInvalidError
    from bisheng.tenant.domain.services.tenant_service import TenantService
    from bisheng.tenant.domain.schemas.tenant_schema import TenantQuotaUpdate

    with patch(
        'bisheng.tenant.domain.services.tenant_service.TenantDao.aupdate_tenant',
        new=AsyncMock(),
    ) as mock_update:
        with pytest.raises(QuotaConfigInvalidError):
            await TenantService.aset_quota(
                tenant_id=5,
                data=TenantQuotaUpdate(quota_config={'storage_gb': 1.55}),
                login_user=None,
            )

    # No DB write happened — rejection occurs before persistence.
    mock_update.assert_not_called()


@pytest.mark.asyncio
async def test_aget_tenant_root_uses_aggregated_usage():
    """Detail endpoint must call the same batch helper so root rows aggregate
    children (INV-T9) just like the list."""
    from bisheng.tenant.domain.services.tenant_service import TenantService

    root = _make_tenant(tid=1, name='Root', code='root', quota_gb=10, parent_tenant_id=None)

    with patch(
        'bisheng.tenant.domain.services.tenant_service.TenantDao.aget_by_id',
        new=AsyncMock(return_value=root),
    ), patch(
        'bisheng.tenant.domain.services.tenant_service.UserDepartmentDao'
        '.acount_users_by_tenant_subtree',
        new=AsyncMock(return_value=10),
    ), patch.object(
        TenantService, '_get_tenant_admin_users',
        new=AsyncMock(return_value=[]),
    ), patch(
        'bisheng.tenant.domain.services.tenant_mount_service.display_tenant_code',
        new=lambda code: code,
    ), patch(
        'bisheng.role.domain.services.quota_service.QuotaService'
        '.get_storage_used_gb_batch',
        new=AsyncMock(return_value={1: 7.5}),
    ) as mock_batch:
        detail = await TenantService.aget_tenant(tenant_id=1, login_user=None)

    mock_batch.assert_awaited_once_with([1])
    assert detail['storage_used_gb'] == 7.5
    assert detail['storage_quota_gb'] == 10

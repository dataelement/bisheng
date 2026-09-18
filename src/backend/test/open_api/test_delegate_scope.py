from types import SimpleNamespace

import pytest

from bisheng.common.errcode.open_api import OpenApiDelegateConfigurationInvalidError
from bisheng.open_api.domain.schemas.credential import DelegateScopeInput
from bisheng.open_api.domain.services.delegate_scope_service import DelegateScopeService


async def test_user_and_department_scopes_are_validated_in_tenant(monkeypatch):
    async def users(user_ids):
        return {user_id: SimpleNamespace(user_id=user_id, tenant_id=4) for user_id in user_ids}

    async def departments(department_ids):
        return {
            department_id: SimpleNamespace(id=department_id, tenant_id=4, status="active", is_deleted=0)
            for department_id in department_ids
        }

    monkeypatch.setattr(
        "bisheng.open_api.domain.services.delegate_scope_service.OwnerRepository.get_active_natural_people",
        users,
    )
    monkeypatch.setattr(
        "bisheng.open_api.domain.services.delegate_scope_service.DelegateScopeRepository.get_departments",
        departments,
    )
    entries = await DelegateScopeService.validate_entries(
        tenant_id=4,
        entries=[
            DelegateScopeInput(subject_type="user", subject_id=9),
            DelegateScopeInput(subject_type="department", subject_id=3),
            DelegateScopeInput(subject_type="user", subject_id=9),
        ],
    )
    assert entries == (("user", 9), ("department", 3))


async def test_cross_tenant_or_inactive_scope_is_rejected(monkeypatch):
    async def cross_tenant(_user_ids):
        return {9: SimpleNamespace(user_id=9, tenant_id=5)}

    monkeypatch.setattr(
        "bisheng.open_api.domain.services.delegate_scope_service.OwnerRepository.get_active_natural_people",
        cross_tenant,
    )
    with pytest.raises(OpenApiDelegateConfigurationInvalidError):
        await DelegateScopeService.validate_entries(
            tenant_id=4,
            entries=[DelegateScopeInput(subject_type="user", subject_id=9)],
        )

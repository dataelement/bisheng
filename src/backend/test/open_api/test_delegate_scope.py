from types import SimpleNamespace

import pytest

from bisheng.common.errcode.open_api import OpenApiDelegateConfigurationInvalidError
from bisheng.open_api.domain.schemas.credential import DelegateScopeInput
from bisheng.open_api.domain.services.delegate_scope_service import DelegateScopeService


async def test_user_and_department_scopes_are_validated_in_tenant(monkeypatch):
    async def user(user_id):
        return SimpleNamespace(user_id=user_id, tenant_id=4)

    async def department(department_id):
        return SimpleNamespace(
            id=department_id,
            tenant_id=4,
            status="active",
            is_deleted=0,
        )

    monkeypatch.setattr(
        "bisheng.open_api.domain.services.delegate_scope_service.OwnerRepository.get_active_natural_person",
        user,
    )
    monkeypatch.setattr(
        "bisheng.open_api.domain.services.delegate_scope_service.DelegateScopeRepository.get_department",
        department,
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
    async def cross_tenant(_user_id):
        return SimpleNamespace(user_id=9, tenant_id=5)

    monkeypatch.setattr(
        "bisheng.open_api.domain.services.delegate_scope_service.OwnerRepository.get_active_natural_person",
        cross_tenant,
    )
    with pytest.raises(OpenApiDelegateConfigurationInvalidError):
        await DelegateScopeService.validate_entries(
            tenant_id=4,
            entries=[DelegateScopeInput(subject_type="user", subject_id=9)],
        )

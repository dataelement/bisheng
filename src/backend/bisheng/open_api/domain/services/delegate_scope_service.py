from __future__ import annotations

from bisheng.common.errcode.open_api import OpenApiDelegateConfigurationInvalidError
from bisheng.open_api.domain.models.credential_delegate_scope import (
    DELEGATE_SUBJECT_DEPARTMENT,
    DELEGATE_SUBJECT_USER,
)
from bisheng.open_api.domain.repositories.delegate_scope_repository import DelegateScopeRepository
from bisheng.open_api.domain.repositories.owner_repository import OwnerRepository
from bisheng.open_api.domain.schemas.credential import DelegateScopeInput


class DelegateScopeService:
    @classmethod
    async def validate_entries(
        cls,
        *,
        tenant_id: int,
        entries: list[DelegateScopeInput],
    ) -> tuple[tuple[str, int], ...]:
        normalized = tuple(dict.fromkeys((entry.subject_type, entry.subject_id) for entry in entries))
        for subject_type, subject_id in normalized:
            if subject_type == DELEGATE_SUBJECT_USER:
                user = await OwnerRepository.get_active_natural_person(subject_id)
                if user is None or user.tenant_id != tenant_id:
                    raise OpenApiDelegateConfigurationInvalidError()
            elif subject_type == DELEGATE_SUBJECT_DEPARTMENT:
                department = await DelegateScopeRepository.get_department(subject_id)
                if (
                    department is None
                    or department.tenant_id != tenant_id
                    or department.status != "active"
                    or department.is_deleted
                ):
                    raise OpenApiDelegateConfigurationInvalidError()
            else:
                raise OpenApiDelegateConfigurationInvalidError()
        return normalized

    @classmethod
    async def target_allowed(cls, credential_id: int, user_id: int) -> bool:
        rows = await DelegateScopeRepository.list_for_credential(credential_id)
        if any(row.subject_type == DELEGATE_SUBJECT_USER and row.subject_id == user_id for row in rows):
            return True
        department_ids = tuple(
            row.subject_id for row in rows if row.subject_type == DELEGATE_SUBJECT_DEPARTMENT
        )
        return await DelegateScopeRepository.target_in_departments(user_id, department_ids)

    @classmethod
    async def response_entries(cls, credential_id: int) -> list[DelegateScopeInput]:
        rows = await DelegateScopeRepository.list_for_credential(credential_id)
        return [
            DelegateScopeInput(subject_type=row.subject_type, subject_id=row.subject_id)
            for row in rows
        ]


__all__ = ["DelegateScopeService"]

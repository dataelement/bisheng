from __future__ import annotations

from bisheng.common.errcode.open_api import OpenApiDelegateConfigurationInvalidError
from bisheng.open_api.domain.models.credential_delegate_scope import (
    DELEGATE_SUBJECT_DEPARTMENT,
    DELEGATE_SUBJECT_USER,
)
from bisheng.open_api.domain.repositories.delegate_scope_repository import DelegateScopeRepository
from bisheng.open_api.domain.repositories.owner_repository import OwnerRepository
from bisheng.open_api.domain.schemas.credential import DelegateScopeInput, DelegateScopeItem


class DelegateScopeService:
    @classmethod
    async def validate_entries(
        cls,
        *,
        tenant_id: int,
        entries: list[DelegateScopeInput],
    ) -> tuple[tuple[str, int], ...]:
        normalized = tuple(dict.fromkeys((entry.subject_type, entry.subject_id) for entry in entries))
        if await cls.filter_entries(tenant_id=tenant_id, entries=entries) != normalized:
            raise OpenApiDelegateConfigurationInvalidError()
        return normalized

    @classmethod
    async def filter_entries(cls, *, tenant_id: int, entries: list[DelegateScopeInput]) -> tuple[tuple[str, int], ...]:
        """Use one eligibility rule for picker candidates and credential writes."""
        normalized = tuple(dict.fromkeys((entry.subject_type, entry.subject_id) for entry in entries))
        user_ids = tuple(sid for kind, sid in normalized if kind == DELEGATE_SUBJECT_USER)
        department_ids = tuple(sid for kind, sid in normalized if kind == DELEGATE_SUBJECT_DEPARTMENT)
        users = await OwnerRepository.get_active_natural_people(user_ids) if user_ids else {}
        departments = await DelegateScopeRepository.get_departments(department_ids) if department_ids else {}
        eligible = []
        for subject_type, subject_id in normalized:
            if subject_type == DELEGATE_SUBJECT_USER:
                user = users.get(subject_id)
                if user is not None and user.tenant_id == tenant_id:
                    eligible.append((subject_type, subject_id))
            elif subject_type == DELEGATE_SUBJECT_DEPARTMENT:
                department = departments.get(subject_id)
                if (
                    department is not None
                    and department.tenant_id == tenant_id
                    and department.status == "active"
                    and not department.is_deleted
                ):
                    eligible.append((subject_type, subject_id))
        return tuple(eligible)

    @classmethod
    async def target_allowed(cls, credential_id: int, user_id: int) -> bool:
        rows = await DelegateScopeRepository.list_for_credential(credential_id)
        if any(row.subject_type == DELEGATE_SUBJECT_USER and row.subject_id == user_id for row in rows):
            return True
        department_ids = tuple(row.subject_id for row in rows if row.subject_type == DELEGATE_SUBJECT_DEPARTMENT)
        return await DelegateScopeRepository.target_in_departments(user_id, department_ids)

    @classmethod
    async def response_entries(cls, credential_id: int) -> list[DelegateScopeItem]:
        rows = await DelegateScopeRepository.list_for_credential(credential_id)
        entries = []
        for row in rows:
            if row.subject_type == DELEGATE_SUBJECT_USER:
                subject_name = await OwnerRepository.get_user_name(row.subject_id)
            else:
                department = await DelegateScopeRepository.get_department(row.subject_id)
                subject_name = department.name if department else None
            entries.append(
                DelegateScopeItem(
                    subject_type=row.subject_type,
                    subject_id=row.subject_id,
                    subject_name=subject_name,
                )
            )
        return entries


__all__ = ["DelegateScopeService"]

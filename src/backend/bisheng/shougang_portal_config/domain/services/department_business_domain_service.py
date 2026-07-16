"""Exact primary-department business-domain resolution and binding validation."""

from collections.abc import Sequence

from loguru import logger

from bisheng.shougang_portal_config.domain.repositories.interfaces.department_business_domain_repository import (
    DepartmentBusinessDomainBinding,
    DepartmentBusinessDomainRepository,
)
from bisheng.shougang_portal_config.domain.schemas.portal_config_schema import (
    PortalDepartmentBusinessDomainBinding,
)


class DepartmentBusinessDomainValidationError(ValueError):
    pass


class DepartmentBusinessDomainService:
    def __init__(self, repository: DepartmentBusinessDomainRepository):
        self.repository = repository

    async def get_user_business_domain_codes(self, user_id: int) -> list[str]:
        primary_department_ids = await self.repository.list_primary_department_ids_for_user(int(user_id))
        if len(primary_department_ids) != 1:
            if len(primary_department_ids) > 1:
                logger.warning(
                    "portal recommendation disabled department feature because primary department count is {}",
                    len(primary_department_ids),
                )
            return []
        bindings = await self.repository.list_by_department_id(primary_department_ids[0])
        return sorted({binding.business_domain_code for binding in bindings})

    async def validate_departments_exist(
        self,
        bindings: Sequence[PortalDepartmentBusinessDomainBinding],
    ) -> None:
        requested_ids = {int(binding.department_id) for binding in bindings}
        existing_ids = await self.repository.list_existing_department_ids(sorted(requested_ids))
        missing_ids = requested_ids - existing_ids
        if missing_ids:
            raise DepartmentBusinessDomainValidationError(
                "department business domain binding references a missing department"
            )

    @staticmethod
    def flatten_bindings(
        bindings: Sequence[PortalDepartmentBusinessDomainBinding],
    ) -> list[DepartmentBusinessDomainBinding]:
        return [
            DepartmentBusinessDomainBinding(
                department_id=int(binding.department_id),
                business_domain_code=business_domain_code,
            )
            for binding in bindings
            for business_domain_code in binding.business_domain_codes
        ]

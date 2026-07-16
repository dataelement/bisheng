"""Resolve exact primary-department domains from the portal domain config."""

import re
from collections.abc import Sequence

from loguru import logger

from bisheng.shougang_portal_config.domain.repositories.interfaces.portal_department_repository import (
    PortalDepartmentRepository,
)
from bisheng.shougang_portal_config.domain.schemas.portal_config_schema import (
    PortalDomainConfig,
)

_BUSINESS_DOMAIN_CODE_PATTERN = re.compile(r"^[A-Z0-9_]{1,16}$")


class DepartmentBusinessDomainService:
    def __init__(self, repository: PortalDepartmentRepository):
        self.repository = repository

    async def get_user_business_domain_codes(
        self,
        user_id: int,
        domains: Sequence[PortalDomainConfig],
    ) -> list[str]:
        primary_department_ids = await self.repository.list_primary_department_ids_for_user(int(user_id))
        if len(primary_department_ids) != 1:
            if len(primary_department_ids) > 1:
                logger.warning(
                    "portal recommendation disabled department feature because primary department count is {}",
                    len(primary_department_ids),
                )
            return []
        primary_department_id = primary_department_ids[0]
        return sorted(
            {
                domain.code
                for domain in domains
                if domain.enabled
                and _BUSINESS_DOMAIN_CODE_PATTERN.fullmatch(domain.code)
                and primary_department_id in domain.department_ids
            }
        )

    @staticmethod
    def domain_department_pairs(
        domains: Sequence[PortalDomainConfig],
    ) -> set[tuple[int, str]]:
        return {
            (int(department_id), domain.code)
            for domain in domains
            if domain.enabled and _BUSINESS_DOMAIN_CODE_PATTERN.fullmatch(domain.code)
            for department_id in domain.department_ids
        }

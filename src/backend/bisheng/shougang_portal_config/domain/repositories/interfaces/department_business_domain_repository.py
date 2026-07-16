"""Repository contract for exact department business-domain bindings."""

from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class DepartmentBusinessDomainBinding:
    department_id: int
    business_domain_code: str


@dataclass(frozen=True)
class DepartmentBusinessDomainRecord(DepartmentBusinessDomainBinding):
    id: int
    tenant_id: int
    create_user: int | None = None
    create_time: datetime | None = None
    update_time: datetime | None = None


class DepartmentBusinessDomainRepository(ABC):
    @abstractmethod
    async def list_all(self) -> list[DepartmentBusinessDomainRecord]:
        """Return only the current strict tenant's bindings."""

    @abstractmethod
    async def list_by_department_id(self, department_id: int) -> list[DepartmentBusinessDomainRecord]:
        """Return direct bindings for one exact department, without inheritance."""

    @abstractmethod
    async def list_by_department_ids(
        self,
        department_ids: Sequence[int],
    ) -> list[DepartmentBusinessDomainRecord]:
        """Return direct bindings for the requested exact departments."""

    @abstractmethod
    async def list_existing_department_ids(self, department_ids: Sequence[int]) -> set[int]:
        """Return department IDs that exist in the current strict tenant."""

    @abstractmethod
    async def list_primary_department_ids_for_user(self, user_id: int) -> list[int]:
        """Return every is_primary=true membership; never collapse with first()."""

    @abstractmethod
    async def replace_all(
        self,
        bindings: Sequence[DepartmentBusinessDomainBinding],
        *,
        create_user: int | None,
    ) -> list[DepartmentBusinessDomainRecord]:
        """Replace current tenant bindings, flushing without committing."""

    @abstractmethod
    async def delete_all(self) -> int:
        """Delete current tenant bindings, flushing without committing."""

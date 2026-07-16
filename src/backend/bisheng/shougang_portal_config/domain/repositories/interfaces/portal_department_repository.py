"""Tenant-safe department membership lookup for portal personalization."""

from abc import ABC, abstractmethod


class PortalDepartmentRepository(ABC):
    @abstractmethod
    async def list_primary_department_ids_for_user(self, user_id: int) -> list[int]:
        """Return every exact primary membership without collapsing duplicates."""

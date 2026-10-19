"""SubflowRef repository interface."""

from abc import ABC, abstractmethod

from bisheng.common.repositories.interfaces.base_repository import BaseRepository
from bisheng.workflow.domain.models.subflow_ref import WorkflowSubflowRef


class SubflowRefRepository(BaseRepository[WorkflowSubflowRef, int], ABC):
    """Reference rows between a parent workflow and the workflows it uses as subflows."""

    @abstractmethod
    async def replace_for_parent(self, parent_flow_id: str, child_flow_ids: list[str]) -> None:
        """Make the parent's rows equal to ``child_flow_ids`` (duplicates ignored)."""

    @abstractmethod
    async def delete_for_parent(self, parent_flow_id: str) -> None:
        """Remove every row whose parent is ``parent_flow_id``."""

    @abstractmethod
    async def list_referrer_ids(self, child_flow_id: str) -> list[str]:
        """Parent workflow ids that reference ``child_flow_id``, oldest reference first."""

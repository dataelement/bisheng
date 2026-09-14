from abc import ABC, abstractmethod

from bisheng.channel.domain.models.information_article_sync_state import InformationArticleSyncState


class InformationArticleSyncStateRepository(ABC):
    @abstractmethod
    async def find_by_source_id(self, source_id: str) -> InformationArticleSyncState | None:
        """Return the current public progress row."""

    @abstractmethod
    async def create_initial_boundary_if_absent(
        self, source_id: str, cursor: int | None
    ) -> InformationArticleSyncState:
        """Create the first boundary or return the concurrent winner."""

    @abstractmethod
    async def commit_if_unchanged(
        self,
        source_id: str,
        expected_state: InformationArticleSyncState,
        next_cursor: int | None,
        remote_sync_at: int | None,
        article_list_updated_at: int | None,
    ) -> bool:
        """Commit progress only when the persisted values still match the snapshot."""

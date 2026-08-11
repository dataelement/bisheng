from abc import ABC
from typing import Any

from bisheng.common.repositories.interfaces.base_repository import BaseRepository
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile


class KnowledgeFileRepository(BaseRepository[KnowledgeFile, int], ABC):
    """Knowledge Base File Repository Interface Class"""

    async def find_by_ids_for_tenant(
        self,
        *,
        tenant_id: int,
        entity_ids: list[int],
    ) -> list[KnowledgeFile]:
        """Fetch files through an explicit tenant predicate for sensitive reads."""
        ...

    async def get_user_metadata_by_knowledge_file_ids(self, knowledge_id: int,
                                                      knowledge_file_ids: list[int]) ->dict[
        int | None, list[dict[str, Any]] | None]:
        """according knowledge_idAndknowledge_file_ids Dapatkanuser_metadata Data field"""
        pass

    async def find_main_version_files_in_space(
        self,
        knowledge_id: int,
        exclude_file_id: int | None = None,
    ) -> list[KnowledgeFile]:
        """Parsed-SUCCESS files in a space that are the primary version of their logical document.

        Used by the SimHash scanner to know what to compare against.
        Optionally exclude one file (the one currently being scanned, to skip self-match).
        """
        ...

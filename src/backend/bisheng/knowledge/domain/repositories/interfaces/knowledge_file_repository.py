from abc import ABC
from typing import Any, Optional

from bisheng.common.repositories.interfaces.base_repository import BaseRepository
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile


class KnowledgeFileRepository(BaseRepository[KnowledgeFile, int], ABC):
    """Knowledge Base File Repository Interface Class"""

    async def get_user_metadata_by_knowledge_file_ids(self, knowledge_id: int,
                                                      knowledge_file_ids: list[int]) ->dict[
        int | None, list[dict[str, Any]] | None]:
        """according knowledge_idAndknowledge_file_ids Dapatkanuser_metadata Data field"""
        pass

    async def find_main_version_files_in_space(
        self, knowledge_id: int, exclude_file_id: Optional[int] = None,
    ) -> list[KnowledgeFile]:
        """Parsed-SUCCESS files in a space that are the primary version of their logical document.

        Used by the SimHash scanner to know what to compare against.
        Optionally exclude one file (the one currently being scanned, to skip self-match).
        """
        ...

    async def find_success_files_in_space(
        self, knowledge_id: int, exclude_file_id: Optional[int] = None,
    ) -> list[KnowledgeFile]:
        """Parsed-SUCCESS physical files in a space, regardless of version document status."""
        ...

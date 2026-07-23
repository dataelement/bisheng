from abc import ABC
from typing import Any

from bisheng.common.repositories.interfaces.base_repository import BaseRepository
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile


class KnowledgeFileRepository(BaseRepository[KnowledgeFile, int], ABC):
    """Knowledge Base File Repository Interface Class"""

    async def find_by_id_for_update(self, entity_id: int) -> KnowledgeFile | None:
        """锁定文件行，用于串行化申请创建与绑定校验。"""
        ...

    async def find_by_ids_for_update(
        self,
        entity_ids: list[int],
    ) -> list[KnowledgeFile]:
        """批量锁定文件行，供删除与归属变更事务复核。"""
        ...

    async def prepare_delete_by_ids(self, entity_ids: list[int]) -> int:
        """在当前 session 暂存批量删除；只 flush，不提交。"""
        ...

    async def get_user_metadata_by_knowledge_file_ids(
        self, knowledge_id: int, knowledge_file_ids: list[int]
    ) -> dict[int | None, list[dict[str, Any]] | None]:
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

    async def find_success_files_in_space(
        self,
        knowledge_id: int,
        exclude_file_id: int | None = None,
    ) -> list[KnowledgeFile]:
        """Parsed-SUCCESS physical files in a space, regardless of version document status."""
        ...

    async def find_file_sync_folders_by_ids(
        self,
        folder_ids: set[int],
    ) -> list[KnowledgeFile]: ...

    async def list_file_sync_direct_children(
        self,
        *,
        knowledge_id: int,
        parent_path: str,
        visible_folder_ids: set[int] | None,
        after: tuple[str, int] | None,
        limit: int,
    ) -> list[KnowledgeFile]: ...

    async def find_file_sync_space_ids_with_folders(
        self,
        *,
        space_ids: set[int],
        visible_folder_ids: set[int] | None,
    ) -> set[int]: ...

    async def find_file_sync_parent_paths_with_children(
        self,
        *,
        knowledge_id: int,
        parent_paths: set[str],
        visible_folder_ids: set[int] | None,
    ) -> set[str]: ...

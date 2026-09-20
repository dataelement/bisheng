from abc import ABC
from datetime import datetime
from typing import Any

from bisheng.common.repositories.interfaces.base_repository import BaseRepository
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile


class KnowledgeFileRepository(BaseRepository[KnowledgeFile, int], ABC):
    """Knowledge Base File Repository Interface Class"""

    async def list_qa_favorite_page(self, *, space_id: int, after_id: int, limit: int) -> list[KnowledgeFile]:
        """按 ID 分页读取未删除的收藏引用，不展开源库。"""
        ...

    async def find_portal_tag_file_ids(self, space_ids: list[int], tag_name: str) -> list[int]:
        """批量解析空间原有标签及绑定标签库，返回关联的文件 ID。"""
        ...

    async def list_qa_subtree_page(self, *, space_id: int, prefix: str,
                                   after_id: int, limit: int) -> list[KnowledgeFile]:
        """按入口 ID 游标读取指定子树的有效文件，业务层继续检查权限。"""
        ...

    async def list_qa_category_candidates(
        self,
        *,
        space_ids: list[int],
        document_type: str | None,
        file_subcategory_code: str | None,
        before_id: int | None,
        limit: int | None,
    ) -> list[KnowledgeFile]:
        """按分类读取候选；limit=None 用于完整统计，业务层继续检查文件权限。"""
        ...

    async def find_by_id_for_update(self, entity_id: int) -> KnowledgeFile | None:
        """锁定文件行，用于串行化申请创建与绑定校验。"""
        ...

    async def set_parse_priority_if_unset(
        self,
        file_id: int,
        priority: str,
    ) -> KnowledgeFile | None:
        """Atomically persist the first priority and return the database winner."""
        ...

    async def find_by_ids_in_knowledge(
        self,
        entity_ids: list[int],
        knowledge_id: int,
    ) -> list[KnowledgeFile]:
        """Load current-tenant candidate files that belong to one knowledge space."""
        ...

    async def find_by_ids_for_update(
        self,
        entity_ids: list[int],
    ) -> list[KnowledgeFile]:
        """批量锁定文件行，供删除与归属变更事务复核。"""
        ...

    async def find_favorite_referrers_by_source_file_ids(
        self,
        source_file_ids: list[int],
    ) -> list[KnowledgeFile]:
        """批量返回引用指定源文件的个人收藏记录。"""
        ...

    async def prepare_delete_by_ids(self, entity_ids: list[int]) -> int:
        """在当前 session 暂存批量删除；只 flush，不提交。"""
        ...

    async def find_distribution_entries_by_document_id(
        self,
        document_id: int,
        *,
        statuses: set[str] | None = None,
        for_update: bool = False,
    ) -> list[KnowledgeFile]:
        """List F059 entries for a canonical document in stable ID order."""
        ...

    async def find_active_entries_for_documents(
        self,
        *,
        tenant_id: int,
        document_ids: list[int],
        knowledge_ids: list[int],
    ) -> list[KnowledgeFile]:
        """Active manager/publish/share entries of canonical documents in given spaces.

        One batched query for the F059 retrieval Top-K back-mapping (F3):
        entries are limited to ``knowledge_ids`` (requested spaces) so the
        cost stays O(len(document_ids)) instead of O(space file count).
        """
        ...

    async def find_active_entries_for_documents_any_space(
        self,
        *,
        tenant_id: int,
        document_ids: list[int],
    ) -> list[KnowledgeFile]:
        """Active manager/publish/share entries across all spaces for generation checks."""
        ...

    async def find_entry_in_space_for_update(
        self,
        document_id: int,
        knowledge_id: int,
    ) -> KnowledgeFile | None:
        """Lock the active/preparing entry for a document in one space."""
        ...

    async def has_visible_content_in_space(
        self,
        *,
        tenant_id: int,
        knowledge_id: int,
        md5: str,
    ) -> bool:
        """判断目标空间当前可见文件是否已包含相同物理内容。"""
        ...

    async def find_manager_for_update(
        self,
        document_id: int,
    ) -> KnowledgeFile | None:
        """Lock the current manager entry for a canonical document."""
        ...

    async def find_by_approval_instance_id(
        self,
        approval_instance_id: int,
    ) -> KnowledgeFile | None:
        """Find the F059 entry created by an approval instance."""
        ...

    async def mark_document_entries_content_generation(
        self,
        document_id: int,
        generation: int,
    ) -> int:
        """Mark every active entry pending at a canonical content generation."""
        ...

    async def request_projection_rebuild(self, entry_id: int) -> bool:
        """Atomically reopen one ready active logical entry for projection."""
        ...

    async def find_projection_candidates(
        self,
        *,
        now: datetime,
        limit: int,
        max_retries: int | None = None,
    ) -> list[KnowledgeFile]:
        """Return due F059 projection rows using the complete retry predicate."""
        ...

    async def claim_projection_lease(
        self,
        *,
        entry_id: int,
        lease_owner: str,
        lease_until: datetime,
        now: datetime,
        max_retries: int | None = None,
    ) -> KnowledgeFile | None:
        """Atomically claim or take over an expired projection lease."""
        ...

    async def apply_projection_result(
        self,
        *,
        entry_id: int,
        lease_owner: str,
        target_content_generation: int,
        target_entry_generation: int,
        retain_cleanup_lease: bool = False,
    ) -> bool:
        """CAS applied generations by lease token without hiding newer work."""
        ...

    async def defer_projection_lease(
        self, *, entry_id: int, lease_owner: str,
        next_retry_at: datetime, error_summary: str,
    ) -> bool:
        """等待依赖, 释放租约但不消耗失败次数。"""
        ...

    async def recover_failed_projection(
        self, *, entry_id: int, now: datetime, audit_summary: str,
    ) -> bool:
        """显式恢复失败入口; 不能抢占未过期租约。"""
        ...

    async def fail_projection_lease(
        self,
        *,
        entry_id: int,
        lease_owner: str,
        next_retry_at: datetime,
        error_summary: str,
    ) -> bool:
        """Record a projection failure by lease token and release the lease."""
        ...

    async def activate_prepared_entry(self, entry_id: int) -> bool:
        """Conditionally activate one preparing entry and flush."""
        ...

    async def mark_entry_deleting(self, entry_id: int) -> bool:
        """Conditionally hide one active/preparing entry and flush."""
        ...

    async def find_permission_reconcile_candidates(
        self,
        *,
        older_than: datetime,
        limit: int,
        after_id: int = 0,
    ) -> list[KnowledgeFile]:
        """Find aged preparing/deleting entries for permission compensation."""
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

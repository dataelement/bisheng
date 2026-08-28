from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass

from bisheng.knowledge.domain.models.knowledge import Knowledge
from bisheng.knowledge.domain.models.knowledge_document import KnowledgeDocument
from bisheng.knowledge.domain.models.knowledge_document_version import KnowledgeDocumentVersion
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile


@dataclass(frozen=True)
class MigrationSpaceRecord:
    space: Knowledge
    level: str
    owner_type: str
    owner_id: int


@dataclass(frozen=True)
class MigrationChildRecord:
    file: KnowledgeFile
    has_children: bool


class KnowledgeMigrationSourceRepository(ABC):
    @abstractmethod
    async def list_spaces(
        self,
        *,
        keyword: str | None,
        level: str | None,
        offset: int,
        limit: int,
        levels: set[str] | None = None,
    ) -> tuple[list[MigrationSpaceRecord], int]: ...

    @abstractmethod
    async def find_spaces_by_ids(
        self,
        space_ids: set[int],
    ) -> list[MigrationSpaceRecord]: ...

    @abstractmethod
    async def list_children(
        self,
        *,
        space_id: int,
        parent_id: int | None,
        after: tuple[str, int] | None,
        limit: int,
        folders_only: bool,
    ) -> list[MigrationChildRecord]: ...

    @abstractmethod
    async def find_nodes(
        self,
        *,
        space_id: int,
        node_ids: set[int],
    ) -> list[KnowledgeFile]: ...

    @abstractmethod
    async def expand_selection(
        self,
        selection_snapshot: Sequence[dict],
    ) -> list[KnowledgeFile]: ...

    @abstractmethod
    async def expand_selection_page(
        self,
        selection_snapshot: Sequence[dict],
        *,
        after_id: int,
        limit: int,
    ) -> list[KnowledgeFile]: ...

    @abstractmethod
    async def find_versions_by_file_ids(
        self,
        file_ids: set[int],
    ) -> list[KnowledgeDocumentVersion]: ...

    @abstractmethod
    async def find_documents_by_ids(
        self,
        document_ids: set[int],
    ) -> list[KnowledgeDocument]: ...

    @abstractmethod
    async def find_versions_by_document_ids(
        self,
        document_ids: set[int],
    ) -> list[KnowledgeDocumentVersion]: ...

    @abstractmethod
    async def find_files_by_ids(
        self,
        file_ids: set[int],
    ) -> list[KnowledgeFile]: ...

    @abstractmethod
    async def find_entries_by_document_ids(
        self,
        document_ids: set[int],
    ) -> list[KnowledgeFile]: ...

    @abstractmethod
    async def list_target_files(
        self,
        target_space_id: int,
    ) -> list[KnowledgeFile]: ...

    @abstractmethod
    async def list_target_folders(
        self,
        target_space_id: int,
    ) -> list[KnowledgeFile]: ...

    @abstractmethod
    async def list_target_folders_page(
        self,
        target_space_id: int,
        *,
        parent_path: str,
        after_id: int,
        limit: int,
    ) -> list[KnowledgeFile]: ...

    @abstractmethod
    async def list_target_conflict_candidates_page(
        self,
        target_space_id: int,
        *,
        md5_values: set[str],
        parent_paths: set[str],
        after_id: int,
        limit: int,
    ) -> list[KnowledgeFile]: ...

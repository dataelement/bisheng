import asyncio
import logging
from collections.abc import Iterable
from dataclasses import dataclass

from bisheng.core.storage.minio.minio_storage import MinioStorage
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile
from bisheng.knowledge.domain.repositories.interfaces.knowledge_document_version_repository import (
    KnowledgeDocumentVersionRepository,
)
from bisheng.knowledge.domain.repositories.interfaces.knowledge_file_repository import (
    KnowledgeFileRepository,
)
from bisheng.knowledge.domain.services.knowledge_utils import KnowledgeUtils

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RetrieveSourceLink:
    source_url: str
    source_full_url: str


@dataclass(frozen=True)
class RetrieveSourceRef:
    """Authorized retrieval entry and its canonical content identity."""

    entry_file_id: int
    canonical_document_id: int | None = None
    canonical_version_id: int | None = None


EMPTY_RETRIEVE_SOURCE_LINK = RetrieveSourceLink(
    source_url="",
    source_full_url="",
)


class FilelibRetrieveSourceService:
    """Resolve original-file links for already authorized retrieval results."""

    def __init__(
        self,
        file_repository: KnowledgeFileRepository,
        storage: MinioStorage,
        *,
        version_repository: KnowledgeDocumentVersionRepository,
        max_concurrency: int = 8,
    ) -> None:
        self.file_repository = file_repository
        self.version_repository = version_repository
        self.storage = storage
        self._semaphore = asyncio.Semaphore(max_concurrency)

    @staticmethod
    def _positive_int(value: object) -> int | None:
        if isinstance(value, bool):
            return None
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            return None
        return parsed if parsed > 0 else None

    @classmethod
    def _normalize_source_ref(
        cls,
        value: RetrieveSourceRef | int | None,
    ) -> RetrieveSourceRef | None:
        if isinstance(value, int) and not isinstance(value, bool):
            entry_file_id = cls._positive_int(value)
            return RetrieveSourceRef(entry_file_id=entry_file_id) if entry_file_id else None
        if not isinstance(value, RetrieveSourceRef):
            return None

        entry_file_id = cls._positive_int(value.entry_file_id)
        if entry_file_id is None:
            return None
        return RetrieveSourceRef(
            entry_file_id=entry_file_id,
            canonical_document_id=cls._positive_int(value.canonical_document_id),
            canonical_version_id=cls._positive_int(value.canonical_version_id),
        )

    async def _resolve_content_files(
        self,
        source_refs: dict[int, RetrieveSourceRef],
    ) -> dict[int, KnowledgeFile]:
        entry_ids = list(source_refs)
        entries = await self.file_repository.find_by_ids(entry_ids)
        entry_map = {
            int(entry.id): entry
            for entry in entries
            if entry.id is not None and int(entry.id) in source_refs
        }

        content_file_ids: dict[int, int] = {}
        version_refs: dict[int, RetrieveSourceRef] = {}
        for entry_id, source_ref in source_refs.items():
            entry = entry_map.get(entry_id)
            if entry is None:
                continue

            reference_document_id = self._positive_int(
                getattr(entry, "reference_document_id", None)
            )
            if reference_document_id is None:
                content_file_ids[entry_id] = entry_id
                continue
            if (
                source_ref.canonical_document_id != reference_document_id
                or source_ref.canonical_version_id is None
            ):
                continue
            version_refs[entry_id] = source_ref

        if version_refs:
            version_ids = list(
                dict.fromkeys(
                    source_ref.canonical_version_id
                    for source_ref in version_refs.values()
                    if source_ref.canonical_version_id is not None
                )
            )
            versions = await self.version_repository.find_by_ids(version_ids)
            version_map = {
                int(version.id): version
                for version in versions
                if version.id is not None and int(version.id) in version_ids
            }
            for entry_id, source_ref in version_refs.items():
                version = version_map.get(int(source_ref.canonical_version_id or 0))
                if version is None:
                    continue
                if self._positive_int(getattr(version, "document_id", None)) != (
                    source_ref.canonical_document_id
                ):
                    continue
                content_file_id = self._positive_int(
                    getattr(version, "knowledge_file_id", None)
                )
                if content_file_id is not None:
                    content_file_ids[entry_id] = content_file_id

        missing_content_ids = list(
            dict.fromkeys(
                content_file_id
                for content_file_id in content_file_ids.values()
                if content_file_id not in entry_map
            )
        )
        content_file_map = dict(entry_map)
        if missing_content_ids:
            content_files = await self.file_repository.find_by_ids(missing_content_ids)
            content_file_map.update(
                {
                    int(file.id): file
                    for file in content_files
                    if file.id is not None and int(file.id) in missing_content_ids
                }
            )

        return {
            entry_id: content_file_map[content_file_id]
            for entry_id, content_file_id in content_file_ids.items()
            if content_file_id in content_file_map
        }

    async def resolve_links(
        self,
        source_refs: Iterable[RetrieveSourceRef | int | None],
    ) -> dict[int, RetrieveSourceLink]:
        source_ref_map: dict[int, RetrieveSourceRef] = {}
        for value in source_refs:
            source_ref = self._normalize_source_ref(value)
            if source_ref is not None:
                source_ref_map[source_ref.entry_file_id] = source_ref
        if not source_ref_map:
            return {}

        file_map = await self._resolve_content_files(source_ref_map)
        result: dict[int, RetrieveSourceLink] = dict.fromkeys(
            source_ref_map,
            EMPTY_RETRIEVE_SOURCE_LINK,
        )
        entry_ids_by_object_name: dict[str, list[int]] = {}
        for entry_id, file in file_map.items():
            object_name = KnowledgeUtils.resolve_source_object_name(
                file.id,
                file.file_name,
                file.object_name,
            )
            if object_name:
                entry_ids_by_object_name.setdefault(object_name, []).append(entry_id)

        async def _resolve_one(object_name: str) -> tuple[str, RetrieveSourceLink]:
            try:
                async with self._semaphore:
                    exists = await self.storage.object_exists(
                        bucket_name=self.storage.bucket,
                        object_name=object_name,
                    )
                    if not exists:
                        return object_name, EMPTY_RETRIEVE_SOURCE_LINK
                    source_full_url = await self.storage.get_share_link(
                        object_name,
                        clear_host=False,
                        expire_days=7,
                    )
                return object_name, RetrieveSourceLink(
                    source_url=self.storage.clear_minio_share_host(source_full_url),
                    source_full_url=source_full_url,
                )
            except Exception as exc:
                logger.warning(
                    "filelib retrieve source link unavailable entry_count=%s error=%s",
                    len(entry_ids_by_object_name[object_name]),
                    type(exc).__name__,
                )
                return object_name, EMPTY_RETRIEVE_SOURCE_LINK

        object_links = dict(
            await asyncio.gather(
                *(_resolve_one(object_name) for object_name in entry_ids_by_object_name)
            )
        )
        for object_name, entry_ids in entry_ids_by_object_name.items():
            link = object_links.get(object_name, EMPTY_RETRIEVE_SOURCE_LINK)
            result.update(dict.fromkeys(entry_ids, link))
        return result

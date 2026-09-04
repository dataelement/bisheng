import asyncio
import logging
from collections.abc import Iterable
from dataclasses import dataclass

from bisheng.core.storage.minio.minio_storage import MinioStorage
from bisheng.knowledge.domain.repositories.interfaces.knowledge_file_repository import (
    KnowledgeFileRepository,
)
from bisheng.knowledge.domain.services.knowledge_utils import KnowledgeUtils

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RetrieveSourceLink:
    source_url: str
    source_full_url: str


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
        max_concurrency: int = 8,
    ) -> None:
        self.file_repository = file_repository
        self.storage = storage
        self._semaphore = asyncio.Semaphore(max_concurrency)

    async def resolve_links(
        self,
        file_ids: Iterable[int | None],
    ) -> dict[int, RetrieveSourceLink]:
        unique_file_ids = list(
            dict.fromkeys(
                file_id
                for file_id in file_ids
                if isinstance(file_id, int) and not isinstance(file_id, bool) and file_id > 0
            )
        )
        if not unique_file_ids:
            return {}

        files = await self.file_repository.find_by_ids(unique_file_ids)
        file_map = {int(file.id): file for file in files if file.id is not None and int(file.id) in unique_file_ids}
        result: dict[int, RetrieveSourceLink] = dict.fromkeys(unique_file_ids, EMPTY_RETRIEVE_SOURCE_LINK)

        async def _resolve_one(file_id: int) -> tuple[int, RetrieveSourceLink]:
            file = file_map.get(file_id)
            if file is None:
                return file_id, EMPTY_RETRIEVE_SOURCE_LINK

            object_name = KnowledgeUtils.resolve_source_object_name(
                file.id,
                file.file_name,
                file.object_name,
            )
            if not object_name:
                return file_id, EMPTY_RETRIEVE_SOURCE_LINK

            try:
                async with self._semaphore:
                    exists = await self.storage.object_exists(
                        bucket_name=self.storage.bucket,
                        object_name=object_name,
                    )
                    if not exists:
                        return file_id, EMPTY_RETRIEVE_SOURCE_LINK
                    source_full_url = await self.storage.get_share_link(
                        object_name,
                        clear_host=False,
                        expire_days=7,
                    )
                return file_id, RetrieveSourceLink(
                    source_url=self.storage.clear_minio_share_host(source_full_url),
                    source_full_url=source_full_url,
                )
            except Exception as exc:
                logger.warning(
                    "filelib retrieve source link unavailable file_id=%s error=%s",
                    file_id,
                    type(exc).__name__,
                )
                return file_id, EMPTY_RETRIEVE_SOURCE_LINK

        result.update(await asyncio.gather(*(_resolve_one(file_id) for file_id in unique_file_ids)))
        return result

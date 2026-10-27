from sqlalchemy import func, or_
from sqlmodel import col, select

from bisheng.common.errcode.knowledge_space import KnowledgeDocumentStateConflictError
from bisheng.core.database import get_async_db_session
from bisheng.core.search.elasticsearch.manager import get_es_connection
from bisheng.knowledge.domain.models.knowledge import KnowledgeState
from bisheng.knowledge.domain.models.knowledge_document_version import KnowledgeDocumentVersion
from bisheng.knowledge.domain.models.knowledge_file import FileType, KnowledgeFile, KnowledgeFileDao
from bisheng.knowledge.domain.repositories.implementations.knowledge_mcp_repository_impl import (
    KnowledgeMcpRepositoryImpl,
)
from bisheng.knowledge.domain.repositories.interfaces.filelib_space_repository import FilelibSpaceRepository


class FilelibSpaceRepositoryImpl(KnowledgeMcpRepositoryImpl, FilelibSpaceRepository):
    async def fresh_content_state(self, file_id: int) -> tuple | None:
        # A separate managed read avoids MySQL repeatable-read hiding a concurrent version switch.
        async with get_async_db_session() as session:
            repository = FilelibSpaceRepositoryImpl(session)
            entry = await repository.find_by_id(file_id)
            if entry is None or entry.status != 2:
                return None
            space = await repository.get_space(int(entry.knowledge_id))
            if space is None or space.state == KnowledgeState.DELETING.value:
                return None
            ref = (await repository.content_refs([entry])).get(file_id)
            if ref is None:
                return None
            version = await session.get(KnowledgeDocumentVersion, ref[1])
            physical = await repository.find_by_id(int(version.knowledge_file_id)) if version else None
            if physical is None or physical.status != 2 or int(physical.tenant_id or 1) != int(entry.tenant_id or 1):
                return None
            if (
                entry.projection_status != "ready"
                or entry.applied_content_generation != ref[2]
                or entry.applied_content_generation < entry.desired_content_generation
                or entry.applied_entry_generation < entry.desired_entry_generation
            ):
                return None
            return (
                ref,
                int(physical.id),
                entry.applied_entry_generation,
                physical.md5,
                str(physical.update_time),
                physical.preview_file_object_name,
            )

    async def persist_parse_result(self, file_id: int, status: int, remark: str = "") -> KnowledgeFile:
        from bisheng.knowledge.domain.repositories.implementations.knowledge_background_repository_impl import (
            KnowledgeBackgroundRepositoryImpl,
        )
        from bisheng.knowledge.domain.services.knowledge_fulltext_lifecycle_hook import (
            commit_tracked_fulltext_changes,
            track_fulltext_file_changes,
        )

        track_fulltext_file_changes(self.session)
        # Refresh writer-owned generations before updating only the parse fields.
        try:
            result = await self.session.exec(
                select(KnowledgeFile)
                .where(KnowledgeFile.id == file_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            file = result.first()
            if file is None or file.deleted_at is not None or file.entry_status in {"invalid", "deleting"}:
                raise KnowledgeDocumentStateConflictError()
            if status == 2 and (
                file.reference_document_id is None
                or file.projection_status != "ready"
                or file.applied_content_generation != file.desired_content_generation
                or file.applied_entry_generation != file.desired_entry_generation
            ):
                raise KnowledgeDocumentStateConflictError()
            file.status, file.remark = status, remark
            if status == 2:
                await self.session.run_sync(
                    lambda session: KnowledgeBackgroundRepositoryImpl(session).request_auto_publish(file)
                )
            await commit_tracked_fulltext_changes(self.session, trigger_type="filelib_shared_text_parse")
            await self.session.refresh(file)
            return file
        except Exception:
            await self.session.rollback()
            raise

    async def find_by_encoding(self, encoding: str, knowledge_id: int | None) -> list[KnowledgeFile]:
        statement = select(KnowledgeFile).where(
            KnowledgeFile.file_encoding == encoding,
            KnowledgeFile.file_type == FileType.FILE.value,
            col(KnowledgeFile.deleted_at).is_(None),
            or_(KnowledgeFile.entry_status.is_(None), KnowledgeFile.entry_status == "active"),
            or_(KnowledgeFile.entry_type.is_(None), KnowledgeFile.entry_type != "projection_tombstone"),
        )
        if knowledge_id is not None:
            statement = statement.where(KnowledgeFile.knowledge_id == knowledge_id)
        result = await self.session.exec(statement.order_by(KnowledgeFile.id).limit(2))
        return list(result.all())

    async def primary_flags(self, file_ids: list[int]) -> dict[int, bool]:
        if not file_ids:
            return {}
        result = await self.session.exec(
            select(
                KnowledgeDocumentVersion.knowledge_file_id,
                KnowledgeDocumentVersion.is_primary,
            ).where(col(KnowledgeDocumentVersion.knowledge_file_id).in_(file_ids))
        )
        return {int(file_id): bool(primary) for file_id, primary in result.all() if file_id is not None}

    async def root_entries(self, knowledge_id: int) -> list[KnowledgeFile]:
        result = await self.session.exec(
            select(KnowledgeFile)
            .where(
                KnowledgeFile.knowledge_id == knowledge_id,
                KnowledgeFileDao.active_inventory_predicate(),
                func.coalesce(KnowledgeFile.file_level_path, "") == "",
            )
            .order_by(KnowledgeFile.id)
        )
        return list(result.all())

    async def abstracts(self, files: list[KnowledgeFile]) -> dict[int, str]:
        ready = [f for f in files if f.status == 2 and getattr(f, "projection_status", "ready") == "ready"]
        if not ready:
            return {}
        flags = await self.primary_flags([int(f.id) for f in ready])
        refs = await self.content_refs(ready)
        filters = {
            str(f.id): {"bool": {"filter": self._filters(f, refs[f.id])}}
            for f in ready
            if f.id in refs and flags.get(f.id, True)
        }
        if not filters:
            return {}
        route = await self._route(ready)
        client = await get_es_connection()
        result = await client.search(
            index=route.index_name,
            size=0,
            aggs={
                "entries": {
                    "filters": {"filters": filters},
                    "aggs": {
                        "first": {
                            "top_hits": {
                                "size": 1,
                                "sort": [{"metadata.chunk_index": "asc"}],
                                "_source": ["metadata.abstract"],
                            }
                        }
                    },
                },
            },
        )
        titles = {}
        for key, bucket in result.get("aggregations", {}).get("entries", {}).get("buckets", {}).items():
            hits = bucket.get("first", {}).get("hits", {}).get("hits", [])
            if hits:
                titles[int(key)] = str(hits[0].get("_source", {}).get("metadata", {}).get("abstract") or "")
        return titles

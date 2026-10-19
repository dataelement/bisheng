"""Atomic business cutover and leased, tenant-scoped cleanup jobs."""

from datetime import timedelta
from uuid import uuid4

from sqlmodel import col, delete, or_, select, update

from bisheng.common.errcode.knowledge_space import SpaceFileNotFoundError
from bisheng.core.context.tenant import bypass_tenant_filter, get_current_tenant_id
from bisheng.core.database import get_async_db_session
from bisheng.knowledge.domain.models.knowledge import Knowledge, KnowledgeTypeEnum
from bisheng.knowledge.domain.models.knowledge_document import KnowledgeDocument
from bisheng.knowledge.domain.models.knowledge_document_version import KnowledgeDocumentVersion
from bisheng.knowledge.domain.models.knowledge_file import FileType, KnowledgeFile
from bisheng.knowledge.domain.models.knowledge_space_delete_job import (
    DELETE_STEPS,
    KnowledgeSpaceDeleteJob,
    deletion_now,
)

LEASE_SECONDS = 900


class KnowledgeSpaceDeleteRepository:
    def __init__(self, session_factory=get_async_db_session):
        self.session_factory = session_factory

    @staticmethod
    def tenant_id() -> int:
        value = get_current_tenant_id()
        if value is None or int(value) <= 0:
            raise RuntimeError("knowledge deletion requires an explicit tenant")
        return int(value)

    async def prepare(self, session, resource: KnowledgeFile) -> dict:
        """Lock the subtree and resolve primary-version expansion without writes."""
        tenant_id = self.tenant_id()
        space = (
            await session.exec(select(Knowledge).where(Knowledge.id == resource.knowledge_id).with_for_update())
        ).first()
        if space is None or space.type != KnowledgeTypeEnum.SPACE.value or space.tenant_id != tenant_id:
            raise SpaceFileNotFoundError()
        root = (
            await session.exec(select(KnowledgeFile).where(KnowledgeFile.id == resource.id).with_for_update())
        ).first()
        if root is None or root.tenant_id != tenant_id or root.knowledge_id != space.id:
            raise SpaceFileNotFoundError()
        if (root.file_name, root.file_level_path, root.file_type) != (
            resource.file_name,
            resource.file_level_path,
            resource.file_type,
        ):
            raise RuntimeError("delete resource changed before cutover")
        rows = [root]
        if root.file_type == FileType.DIR.value:
            prefix = f"{root.file_level_path or ''}/{root.id}"
            rows += list(
                (
                    await session.exec(
                        select(KnowledgeFile)
                        .where(
                            KnowledgeFile.knowledge_id == space.id,
                            or_(
                                KnowledgeFile.file_level_path == prefix,
                                col(KnowledgeFile.file_level_path).startswith(prefix + "/"),
                            ),
                        )
                        .order_by(KnowledgeFile.id)
                        .with_for_update()
                    )
                ).all()
            )
        file_ids = {int(row.id) for row in rows if row.file_type == FileType.FILE.value}
        versions = (
            list(
                (
                    await session.exec(
                        select(KnowledgeDocumentVersion)
                        .where(col(KnowledgeDocumentVersion.knowledge_file_id).in_(file_ids))
                        .order_by(KnowledgeDocumentVersion.document_id, KnowledgeDocumentVersion.id)
                        .with_for_update()
                    )
                ).all()
            )
            if file_ids
            else []
        )
        selected_by_document: dict[int, list] = {}
        for version in versions:
            selected_by_document.setdefault(version.document_id, []).append(version)
        version_ids, document_ids = set(), set()
        for document_id, selected in selected_by_document.items():
            document = (
                await session.exec(
                    select(KnowledgeDocument)
                    .where(KnowledgeDocument.id == document_id, KnowledgeDocument.knowledge_id == space.id)
                    .with_for_update()
                )
            ).first()
            if document is None:
                raise RuntimeError("delete version anchor is outside the space")
            chain = list(
                (
                    await session.exec(
                        select(KnowledgeDocumentVersion)
                        .where(KnowledgeDocumentVersion.document_id == document_id)
                        .order_by(KnowledgeDocumentVersion.id)
                        .with_for_update()
                    )
                ).all()
            )
            remove_chain = any(version.is_primary for version in selected) or len(selected) == len(chain)
            removed = chain if remove_chain else selected
            version_ids.update(version.id for version in removed)
            file_ids.update(version.knowledge_file_id for version in removed)
            if remove_chain:
                document_ids.add(document_id)
        sibling_ids = file_ids - {row.id for row in rows}
        if sibling_ids:
            siblings = list(
                (
                    await session.exec(
                        select(KnowledgeFile)
                        .where(KnowledgeFile.knowledge_id == space.id, col(KnowledgeFile.id).in_(sibling_ids))
                        .order_by(KnowledgeFile.id)
                        .with_for_update()
                    )
                ).all()
            )
            if {row.id for row in siblings} != sibling_ids:
                raise RuntimeError("delete version siblings are missing or outside the space")
            rows += siblings
        if any(row.tenant_id != tenant_id for row in rows):
            raise SpaceFileNotFoundError()
        return {
            "rows": sorted(row.id for row in rows),
            "file_ids": sorted(file_ids),
            "folder_ids": sorted(row.id for row in rows if row.file_type == FileType.DIR.value),
            "version_ids": sorted(version_ids),
            "document_ids": sorted(document_ids),
            "fga_resources": [
                {
                    "resource_type": "folder" if row.file_type == FileType.DIR.value else "knowledge_file",
                    "resource_id": row.id,
                }
                for row in sorted(rows, key=lambda row: row.id)
            ],
            "object_names": sorted(
                {
                    str(value)
                    for row in rows
                    for value in (
                        row.object_name,
                        row.preview_file_object_name,
                        row.bbox_object_name,
                        row.thumbnails,
                        str(row.id) if row.file_type == FileType.FILE.value else None,
                    )
                    if value
                }
            ),
            "knowledge": space.model_dump(
                include={"id", "name", "type", "tenant_id", "user_id", "model", "index_name", "collection_name"}
            ),
        }

    async def cutover(self, session, manifest: dict) -> None:
        """Delete the formal graph in the same transaction that inserts the job."""
        space_id = int(manifest["knowledge"]["id"])
        if manifest["document_ids"]:
            await session.exec(
                update(KnowledgeDocument)
                .where(
                    KnowledgeDocument.knowledge_id == space_id, col(KnowledgeDocument.id).in_(manifest["document_ids"])
                )
                .values(primary_version_id=None)
            )
        if manifest["version_ids"]:
            await session.exec(
                delete(KnowledgeDocumentVersion).where(col(KnowledgeDocumentVersion.id).in_(manifest["version_ids"]))
            )
        if manifest["document_ids"]:
            await session.exec(
                delete(KnowledgeDocument).where(
                    KnowledgeDocument.knowledge_id == space_id, col(KnowledgeDocument.id).in_(manifest["document_ids"])
                )
            )
        await session.exec(
            delete(KnowledgeFile).where(
                KnowledgeFile.knowledge_id == space_id, col(KnowledgeFile.id).in_(manifest["rows"])
            )
        )
        await session.flush()

    async def _locked_job(self, session, job_id):
        job = (
            await session.exec(
                select(KnowledgeSpaceDeleteJob).where(KnowledgeSpaceDeleteJob.id == job_id).with_for_update()
            )
        ).first()
        if job is None or job.tenant_id != self.tenant_id():
            raise LookupError("delete job not found in the current tenant")
        return job

    async def claim(self, job_id: str) -> KnowledgeSpaceDeleteJob | None:
        async with self.session_factory() as session, session.begin():
            job = await self._locked_job(session, job_id)
            now = deletion_now()
            if job.state == "SUCCEEDED" or job.next_attempt_at > now or (job.lease_until and job.lease_until > now):
                return None
            job.state = "RUNNING"
            job.attempts += 1
            job.lease_token = str(uuid4())
            job.lease_until = now + timedelta(seconds=LEASE_SECONDS)
            job.update_time = now
            session.add(job)
            await session.flush()
            session.expunge(job)
            return job

    async def advance(self, job, *, step: str | None = None, error: str | None = None, complete=False) -> None:
        async with self.session_factory() as session, session.begin():
            row = await self._locked_job(session, job.id)
            if row.state != "RUNNING" or row.lease_token != job.lease_token:
                raise RuntimeError("delete job lease was replaced")
            if (
                step
                and step not in row.completed_steps
                and (step not in DELETE_STEPS or list(DELETE_STEPS[: DELETE_STEPS.index(step)]) != row.completed_steps)
            ):
                raise RuntimeError("delete job steps must finish in order")
            if complete and row.completed_steps != list(DELETE_STEPS):
                raise RuntimeError("delete job has unverified cleanup steps")
            row.update_time = deletion_now()
            row.lease_until = row.update_time + timedelta(seconds=LEASE_SECONDS)
            if step:
                row.completed_steps = list(dict.fromkeys([*row.completed_steps, step]))
            if error is not None or complete:
                row.state = "SUCCEEDED" if complete else "PENDING"
                row.last_error = error[:4000] if error is not None else None
                row.next_attempt_at = row.update_time + timedelta(seconds=60)
                row.lease_token = None
                row.lease_until = None
            session.add(row)

    async def due_jobs(self, *, limit=100) -> list[tuple[int, str]]:
        # Beat enumerates routing metadata only; execution restores each tenant.
        with bypass_tenant_filter():
            async with self.session_factory() as session:
                now = deletion_now()
                rows = (
                    await session.exec(
                        select(KnowledgeSpaceDeleteJob.tenant_id, KnowledgeSpaceDeleteJob.id)
                        .where(
                            KnowledgeSpaceDeleteJob.state != "SUCCEEDED",
                            KnowledgeSpaceDeleteJob.next_attempt_at <= now,
                            or_(
                                KnowledgeSpaceDeleteJob.lease_until.is_(None),
                                KnowledgeSpaceDeleteJob.lease_until <= now,
                            ),
                        )
                        .order_by(KnowledgeSpaceDeleteJob.next_attempt_at, KnowledgeSpaceDeleteJob.id)
                        .limit(limit)
                    )
                ).all()
                return [(int(tenant_id), str(job_id)) for tenant_id, job_id in rows]

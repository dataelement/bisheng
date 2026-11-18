"""The physical writer/deleter mutex and authoritative cancellation checks."""

import hashlib
from contextlib import asynccontextmanager, contextmanager

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from bisheng.common.errcode.knowledge import ResourceReferenceInvalidError
from bisheng.core.context.tenant import get_current_tenant_id, is_tenant_filter_bypassed
from bisheng.core.database import get_async_db_session, get_sync_db_session
from bisheng.knowledge.domain.models.knowledge import Knowledge
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile
from bisheng.knowledge.domain.models.knowledge_processing_fence import (
    KnowledgeProcessingArtifact,
    KnowledgeProcessingFence,
)
from bisheng.knowledge.domain.models.knowledge_space_delete_job import KnowledgeSpaceDeleteJob


class ProcessingCancelled(RuntimeError):
    """Deletion superseded this asynchronous work; do not persist its outcome."""


class ProcessingFenceRepository:
    def __init__(self, sync_sessions=None, async_sessions=None):
        self.sync_sessions = sync_sessions or get_sync_db_session
        self.async_sessions = async_sessions or get_async_db_session

    @staticmethod
    def tenant():
        tenant = get_current_tenant_id()
        if type(tenant) is not int or tenant <= 0 or is_tenant_filter_bypassed():
            raise ResourceReferenceInvalidError(reason="processing_fence_tenant_required")
        return tenant

    def row(self, space_id, file_id):
        tenant = self.tenant()
        return KnowledgeProcessingFence(
            id=f"{tenant}:{space_id}:{file_id}", tenant_id=tenant, space_id=space_id, file_id=file_id
        )

    def ensure(self, space_id, file_id):
        row = self.row(space_id, file_id)
        with self.sync_sessions() as session:
            if session.get(KnowledgeProcessingFence, row.id) is None:
                try:
                    with session.begin_nested():
                        session.add(row)
                        session.flush()
                except IntegrityError:
                    # Another process inserted this exact immutable mutex.
                    if (
                        session.execute(
                            select(KnowledgeProcessingFence.id)
                            .where(
                                KnowledgeProcessingFence.id == row.id,
                                KnowledgeProcessingFence.tenant_id == self.tenant(),
                            )
                            .with_for_update()
                        ).first()
                        is None
                    ):
                        raise
            session.commit()
        return f"{self.tenant()}:{space_id}:{file_id}"

    def check(self, session, space_id, file_id=0, *, fresh=False):
        tenant = self.tenant()
        root = session.execute(
            select(Knowledge.id).where(Knowledge.id == space_id, Knowledge.tenant_id == tenant)
        ).first()
        if root is None:
            raise ProcessingCancelled("owning_space_deleted")
        if (
            file_id
            and session.execute(
                select(KnowledgeFile.id).where(
                    KnowledgeFile.id == file_id,
                    KnowledgeFile.tenant_id == tenant,
                    KnowledgeFile.knowledge_id == space_id,
                )
            ).first()
            is None
        ):
            raise ProcessingCancelled("owning_file_deleted")
        query = select(KnowledgeSpaceDeleteJob).where(
            KnowledgeSpaceDeleteJob.tenant_id == tenant,
            KnowledgeSpaceDeleteJob.space_id == space_id,
            KnowledgeSpaceDeleteJob.state != "SUCCEEDED",
        )
        # Only DB result finalization requests a current/locking read, AFTER
        # locking the business root/file. External IO never locks this range.
        jobs = session.execute(query.with_for_update() if fresh else query).scalars()

        for job in jobs:
            if (
                job.operation_type == "knowledge_space_delete"
                or (file_id and file_id in job.manifest.get("file_ids", ()))
                or (not file_id and job.operation_type == "knowledge_space_clear")
            ):
                raise ProcessingCancelled("resource_deletion_accepted")

    @contextmanager
    def writer(self, space_id, file_id=0, *, validate=True):
        key = self.ensure(space_id, file_id)
        with self.sync_sessions() as session:
            session.execute(
                select(KnowledgeProcessingFence)
                .where(
                    KnowledgeProcessingFence.id == key,
                    KnowledgeProcessingFence.tenant_id == self.tenant(),
                )
                .with_for_update()
            ).scalar_one()
            # Check after acquiring the physical-write mutex. Acceptance does
            # not need this mutex, so deletion never waits for a model call.
            if validate:
                self.check(session, space_id, file_id)
            yield session
            session.commit()

    def checkpoint(self, space_id, file_id=0):
        with self.sync_sessions() as session:
            self.check(session, space_id, file_id)

    def persist_file(self, file):
        with self.writer(file.knowledge_id, file.id, validate=False) as session:
            current = session.execute(
                select(KnowledgeFile)
                .where(
                    KnowledgeFile.id == file.id,
                    KnowledgeFile.tenant_id == self.tenant(),
                    KnowledgeFile.knowledge_id == file.knowledge_id,
                )
                .with_for_update()
            ).scalar_one_or_none()
            if current is None:
                raise ProcessingCancelled("owning_file_deleted")
            # Lock before checking: confirmation can have held this file row.
            # A fresh READ COMMITTED/locking read observes its committed marker.
            self.check(session, file.knowledge_id, file.id, fresh=True)
            for field in (
                "status",
                "remark",
                "parse_type",
                "preview_file_object_name",
                "bbox_object_name",
                "abstract",
                "user_metadata",
                "simhash",
                "similar_status",
                "file_encoding",
                "thumbnails",
            ):
                setattr(current, field, getattr(file, field))
            session.add(current)

    def record_artifact(self, space_id, file_id, object_name):
        # Called while holding writer(). Commit BEFORE external IO: even a
        # worker killed immediately after upload leaves a durable purge key.
        tenant = self.tenant()
        key = hashlib.sha256(f"{tenant}:{space_id}:{file_id}:{object_name}".encode()).hexdigest()
        with self.sync_sessions() as session:
            if session.get(KnowledgeProcessingArtifact, key) is None:
                session.add(
                    KnowledgeProcessingArtifact(
                        id=key, tenant_id=tenant, space_id=space_id, file_id=file_id, object_name=object_name
                    )
                )
            session.commit()

    async def aensure(self, space_id, file_id):
        row = self.row(space_id, file_id)
        key = row.id
        async with self.async_sessions() as session:
            if await session.get(KnowledgeProcessingFence, key) is None:
                try:
                    async with session.begin_nested():
                        session.add(row)
                        await session.flush()
                except IntegrityError:
                    found = await session.execute(
                        select(KnowledgeProcessingFence.id)
                        .where(KnowledgeProcessingFence.id == key, KnowledgeProcessingFence.tenant_id == self.tenant())
                        .with_for_update()
                    )
                    if found.first() is None:
                        raise
            await session.commit()
        return key

    @asynccontextmanager
    async def awriter(self, space_id, file_id=0):
        key = await self.aensure(space_id, file_id)
        async with self.async_sessions() as session:
            await session.execute(
                select(KnowledgeProcessingFence)
                .where(KnowledgeProcessingFence.id == key, KnowledgeProcessingFence.tenant_id == self.tenant())
                .with_for_update()
            )
            await session.run_sync(lambda active: self.check(active, space_id, file_id))
            yield session
            await session.commit()

    @asynccontextmanager
    async def cleanup(self, job):
        """Join every old writer before SQL cutover and external purge.

        A crashed process releases its DB locks. A live, stalled process keeps
        them: lease expiry is deliberately NOT treated as proof it has stopped.
        """
        tenant = self.tenant()
        ids = [0, *sorted(set(job.manifest["file_ids"]))]
        # Short committed inserts do not hold a writer's external-IO lock.
        for file_id in ids:
            await self.aensure(job.space_id, file_id)
        async with self.async_sessions() as session:
            for file_id in ids:
                await session.execute(
                    select(KnowledgeProcessingFence)
                    .where(
                        KnowledgeProcessingFence.id == self.row(job.space_id, file_id).id,
                        KnowledgeProcessingFence.tenant_id == tenant,
                    )
                    .with_for_update()
                )
            yield session
            await session.commit()

    async def artifacts(self, session, job):
        query = select(KnowledgeProcessingArtifact.object_name).where(
            KnowledgeProcessingArtifact.tenant_id == self.tenant(),
            KnowledgeProcessingArtifact.space_id == job.space_id,
        )
        # Whole clear still owns only its frozen file set, not later uploads.
        if job.operation_type == "knowledge_space_delete":
            return list((await session.execute(query)).scalars())
        result = []
        ids = job.manifest["file_ids"]
        for start in range(0, len(ids), 200):
            result.extend(
                (
                    await session.execute(
                        query.where(KnowledgeProcessingArtifact.file_id.in_(ids[start : start + 200]))
                    )
                ).scalars()
            )
        return result

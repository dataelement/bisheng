"""Commit business deletion before running recoverable external cleanup."""

import asyncio
from dataclasses import asdict

from loguru import logger

from bisheng.core.database import get_async_db_session
from bisheng.knowledge.domain.models.knowledge_space_delete_job import DELETE_STEPS, KnowledgeSpaceDeleteJob
from bisheng.knowledge.domain.repositories.knowledge_space_delete_repository import KnowledgeSpaceDeleteRepository


async def dispatch_delete_job(*, tenant_id: int, job_id: str) -> None:
    from bisheng.worker.knowledge.space_delete import purge_space_delete

    purge_space_delete.apply_async(
        kwargs={"job_id": job_id}, headers={"tenant_id": tenant_id, "f048_permission_task": True}
    )


class KnowledgeSpaceDirectDeleteService:
    def __init__(
        self,
        *,
        authorize=None,
        load_permission_records=None,
        session_factory=get_async_db_session,
        dispatch=dispatch_delete_job,
        purge_step=None,
        repository=None,
    ):
        self.repository = repository or KnowledgeSpaceDeleteRepository(session_factory)
        self.session_factory = session_factory
        self.authorize = authorize
        self.load_permission_records = load_permission_records
        self.dispatch = dispatch
        self.purge_step = purge_step or self._purge_step

    async def delete(self, *, resource, applicant_user_id: int) -> dict:
        tenant_id = self.repository.tenant_id()
        async with self.session_factory() as session, session.begin():
            manifest = await self.repository.prepare(session, resource)
            resources = [(item["resource_type"], item["resource_id"]) for item in manifest["fga_resources"]]
            # Revalidate the locked expansion, including version siblings outside the subtree.
            for kind, resource_id in resources:
                await self.authorize(kind, resource_id, "delete")
            records = await self.load_permission_records(resources)
            if {(record.resource_type, int(record.resource_id)) for record in records} != set(resources) or any(
                record.tenant_id != tenant_id for record in records
            ):
                raise RuntimeError("delete permission snapshots do not match the locked resources")
            manifest["fga_permission_records"] = [asdict(record) for record in records]
            job = KnowledgeSpaceDeleteJob(
                tenant_id=tenant_id,
                space_id=resource.knowledge_id,
                applicant_user_id=applicant_user_id,
                manifest=manifest,
            )
            session.add(job)
            await session.flush()
            job_id = job.id
            await self.repository.cutover(session, manifest)
        try:
            await self.dispatch(tenant_id=tenant_id, job_id=job_id)
        except Exception:
            # The committed job is the source of truth; Beat recovers broker/ack failures.
            logger.exception("Knowledge delete {} committed; periodic dispatch will retry", job_id)
        return manifest

    async def purge(self, job_id: str) -> bool:
        job = await self.repository.claim(job_id)
        if job is None:
            return False
        try:
            for step in DELETE_STEPS:
                if step in job.completed_steps:
                    continue
                await self.repository.advance(job)
                await self.purge_step(step, job)
                await self.repository.advance(job, step=step)
            await self.repository.advance(job, complete=True)
            return True
        except Exception as exc:
            await self.repository.advance(job, error=str(exc))
            raise

    async def _purge_step(self, step: str, job) -> None:
        manifest = job.manifest
        file_ids = manifest["file_ids"]
        if step == "fga":
            from bisheng.knowledge.domain.services.knowledge_permission_service import KnowledgeFilePermissionRecord
            from bisheng.permission.application.access import get_f048_resource_adapter
            from bisheng.permission.domain.services.permission_action_service import PermissionActor

            actor = PermissionActor(user_id=job.applicant_user_id, current_tenant_id=job.tenant_id)
            for snapshot in manifest["fga_permission_records"]:
                await self.repository.advance(job)
                record = KnowledgeFilePermissionRecord(**{**snapshot, "ancestor_ids": tuple(snapshot["ancestor_ids"])})
                adapter = await get_f048_resource_adapter(record.resource_type)
                await adapter.project_delete(record=record, actor=actor)
            return
        if step == "minio":
            if not manifest["object_names"]:
                return
            from bisheng.core.storage.minio.minio_manager import get_minio_storage

            storage = await get_minio_storage()
            for object_name in manifest["object_names"]:
                await self.repository.advance(job)
                await storage.remove_object(bucket_name=storage.bucket, object_name=object_name)
                if await storage.object_exists(bucket_name=storage.bucket, object_name=object_name):
                    raise RuntimeError("knowledge deletion left an object in MinIO")
            return
        if not file_ids:
            return
        from bisheng.knowledge.domain.knowledge_rag import KnowledgeRag
        from bisheng.knowledge.domain.models.knowledge import Knowledge

        knowledge = Knowledge(**manifest["knowledge"])
        if step == "es":
            store = await asyncio.to_thread(KnowledgeRag.init_knowledge_es_vectorstore_sync, knowledge=knowledge)
            if await asyncio.to_thread(store.client.indices.exists, index=knowledge.index_name):
                query = {"terms": {"metadata.document_id": file_ids}}
                result = await asyncio.to_thread(store.client.delete_by_query, index=knowledge.index_name, query=query)
                if result.get("failures"):
                    raise RuntimeError("knowledge deletion returned Elasticsearch shard failures")
                await asyncio.to_thread(store.client.indices.refresh, index=knowledge.index_name)
                result = await asyncio.to_thread(store.client.count, index=knowledge.index_name, body={"query": query})
                if int(result["count"]) != 0:
                    raise RuntimeError("knowledge deletion left Elasticsearch chunks")
            return
        if step == "milvus":
            from bisheng.core.ai import FakeEmbeddings

            store = await asyncio.to_thread(
                KnowledgeRag.init_knowledge_milvus_vectorstore_sync, 0, knowledge=knowledge, embeddings=FakeEmbeddings()
            )
            if store.col is not None:
                expression = f"document_id in {file_ids}"
                await asyncio.to_thread(store.col.delete, expr=expression, timeout=60)
                await asyncio.to_thread(store.col.flush)
                result = await asyncio.to_thread(
                    store.col.query, expr=expression, output_fields=["count(*)"], timeout=60
                )
                if not isinstance(result, list) or len(result) != 1:
                    raise RuntimeError("knowledge deletion received an invalid Milvus verification")
                count = result[0].get("count(*)", result[0].get("count"))
                if count is None or int(count) != 0:
                    raise RuntimeError("knowledge deletion left Milvus chunks")
            return
        raise ValueError(f"unsupported deletion step: {step}")

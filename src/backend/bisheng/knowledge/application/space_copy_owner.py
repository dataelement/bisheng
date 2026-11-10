"""Copy-only application assembly over the unchanged lease/count/retry kernel."""

import asyncio
from contextlib import asynccontextmanager
from copy import deepcopy
from types import SimpleNamespace

from bisheng.common.constants.vectorstore_metadata import KNOWLEDGE_RAG_METADATA_SCHEMA
from bisheng.common.errcode.knowledge import KnowledgeOperationPlanChangedError, KnowledgeProcessingObsoleteError
from bisheng.knowledge.application import move_processing_admission as admission
from bisheng.knowledge.application.space_copy import (
    SpaceCopyApplication,
    assert_authority,
    authority_context,
    clean,
    target,
)
from bisheng.knowledge.domain.knowledge_rag import KnowledgeRag
from bisheng.knowledge.domain.repositories.space_copy_repository import SpaceCopyScope, root_facts
from bisheng.knowledge.domain.schemas.processing_job import JobAccepted
from bisheng.knowledge.domain.schemas.processing_job_acceptance import (
    ProcessingConfiguration,
    _digest,
    processing_request_facts,
)
from bisheng.permission.application.identity import get_current_permission_actor


class SpaceCopyOwner:
    def __init__(self, app=None):
        self.app = app or SpaceCopyApplication()
        self.sessions, self.jobs, self.rows = self.app.sessions, self.app.jobs, self.app.rows

    @asynccontextmanager
    async def _session(self):
        tenant = admission.tenant()
        async with self.sessions() as session:
            context = authority_context()
            if session.in_transaction():
                raise KnowledgeOperationPlanChangedError()
            async with session.begin():
                yield session
                clean(session, context)
                if admission.tenant() != tenant:
                    raise KnowledgeOperationPlanChangedError()

    async def aread(self, job_id, *, full=False):
        async with self.sessions() as session:
            context = authority_context()
            job = await (self.jobs.aget(session, job_id) if full else self.jobs.aget_execution(session, job_id))
            reference = await self.jobs.alatest_retry_actor(session, job_id)
            session.expunge(job)
            clean(session, context)
            return job, reference

    async def _logical(self, target_id, job_id):
        async with self.sessions() as session:
            context = authority_context()
            root = await self.rows.aroot(session, target_id)
            if job_id is not None:
                job = await self.jobs.aget(session, job_id)
                self._hash(job)
                plan = await self.app.plans._locked(session, job.parameters["confirmation_id"])
                mapping = job.parameters["mapping"]["files"]
                reference = await self.jobs.alatest_retry_actor(session, job_id)
                if job.space_id != target_id or plan.operation_id != job.id or plan.operation != "space_copy":
                    raise KnowledgeOperationPlanChangedError()
            else:
                plan = await self.rows.aread_empty_plan(session, target_id=target_id)
                reference = plan.actor_reference
                mapping = await self.rows.aread_directory_mapping(
                    session, scope=plan.parameters["scope"], target_id=target_id
                )
            self.app.plans._validate(plan, check_expiry=False)
            if root.creation_payload_hash != plan.request_hash:
                raise KnowledgeOperationPlanChangedError()
            clean(session, context)
            return root.model_copy(deep=True), deepcopy(plan.parameters), deepcopy(mapping), deepcopy(reference)

    @staticmethod
    def _hash(job):
        config = ProcessingConfiguration(job.accepted_model_config_revision, job.expected_index_generation)
        facts = processing_request_facts(
            tenant_id=job.tenant_id,
            space_id=job.space_id,
            kind=job.kind,
            actor_user_id=job.actor_user_id,
            actor_reference=job.actor_reference,
            parameters=job.parameters,
            manifest=job.scope_manifest,
            configuration=config,
            space_config_version=job.space_config_version,
        )
        if job.kind != "space_copy" or _digest(facts) != job.request_hash or job.total_count != len(job.scope_manifest):
            raise KnowledgeOperationPlanChangedError()

    @staticmethod
    def _pairs(payload, mapping, target_id, actor):
        source_id = payload["scope"]["source"]["id"]
        context = _digest(payload["scope"])
        pairs = []
        for row in payload["permissions"]:
            source = target(
                row["kind"],
                row["id"],
                context=context,
                parent_type=row["parent_type"],
                parent_id=row["parent_id"],
                version=row["version"],
            )
            parent_id = mapping[str(row["parent_id"])] if row["parent_type"] == "folder" else target_id
            after = target(
                row["kind"],
                target_id if row["kind"] == "knowledge_space" else mapping[str(row["id"])],
                context=context,
                parent_type=None if row["kind"] == "knowledge_space" else row["parent_type"],
                parent_id=None if row["kind"] == "knowledge_space" else parent_id,
            )
            pairs.append((source, after, row["mode"], actor))
        if source_id == target_id:
            raise KnowledgeOperationPlanChangedError()
        return tuple(pairs)

    async def aensure_logical(self, target_id, job_id, *, identity=None, entry_kind=None):
        root, payload, mapping, reference = await self._logical(target_id, job_id)
        scope = SpaceCopyScope(**payload["scope"])
        async with admission.identity(
            reference, current=identity, entry_kind=entry_kind, required_action="upload_file"
        ) as (actual, _):
            authority = authority_context()
            await self.app.authorize(actual, scope.source)
            actor = get_current_permission_actor()
            pairs = self._pairs(payload, mapping, target_id, actor)
            # Children first, root last. Each original copy key is durable.
            for source, after, mode, operator in (*pairs[1:], pairs[0]):
                async with admission.identity(
                    reference, current=identity, entry_kind=entry_kind, required_action="upload_file"
                ) as (current, _):
                    await self.app.authorize(current, scope.source)
                    await self.app.projection.aexecute_or_resume(
                        source=source, target=after, actor=operator, owner_user_id=scope.source["user_id"], mode=mode
                    )
            await self.app.authorize(actual, scope.source)
            if root.state == 0:
                await self._initialize(root, reference["actor_user_id"])
            assert_authority(authority)
            async with self.sessions() as session:
                context = authority_context()
                current = await self.rows.aload_scope(session, scope.source["id"], lock=True)
                if current.execution_digest != scope.execution_digest:
                    raise KnowledgeOperationPlanChangedError()
                actual_root = await self.rows.aroot(session, target_id, lock=True)
                await self.app.projection.arequire_completed(session, pairs=pairs)
                if actual_root.state not in {0, 1, 2} or actual_root.model_transition is not None:
                    raise KnowledgeOperationPlanChangedError()
                if actual_root.state == 0:
                    actual_root.state = 2 if job_id else 1
                    await session.flush()
                clean(session, context)
                await session.commit()

    @staticmethod
    async def _initialize(root, actor_id):
        vector = await KnowledgeRag.init_knowledge_milvus_vectorstore(
            actor_id, knowledge=root, metadata_schemas=KNOWLEDGE_RAG_METADATA_SCHEMA
        )
        vector.col.load()
        es = await KnowledgeRag.init_knowledge_es_vectorstore(
            knowledge=root, metadata_schemas=KNOWLEDGE_RAG_METADATA_SCHEMA
        )
        try:
            await asyncio.to_thread(es._store._create_index_if_not_exists)
        finally:
            await es.client.close()

    @staticmethod
    def configuration(root):
        return ProcessingConfiguration(root.model_config_revision, root.index_generation)

    async def astart(self, job_id, revision):
        job, reference = await self.aread(job_id)
        await self.aensure_logical(job.space_id, job_id)
        async with admission.identity(reference, required_action="upload_file") as (identity, _):
            async with self.sessions() as session:
                context = authority_context()
                root = await self.rows.aroot(session, job.space_id)
                clean(session, context)
            async with self.sessions() as session:
                context = authority_context()
                source = await self.rows.aroot(session, reference["space_id"])
                clean(session, context)
            await self.app.authorize(identity, root_facts(source))
            async with self.sessions() as session:
                context = authority_context()
                result = await self.jobs.aclaim(
                    session, job_id, configuration=self.configuration(root), expected_job_revision=revision
                )
                clean(session, context)
                await session.commit()
                return result

    async def aclaim(self, lease):
        async with self.sessions() as session:
            context = authority_context()
            header = await self.jobs.aread_transport(session, lease.job_id)
            root = await self.rows.aroot(session, header.space_id)
            result = await self.jobs.aclaim_next_item(session, lease, configuration=self.configuration(root))
            if result is not None:
                session.expunge(result.item)
            clean(session, context)
            await session.commit()
            return result

    async def aguard(self, lease, *, renew=False):
        job, reference = await self.aread(lease.job.job_id)
        async with admission.identity(reference, required_action="upload_file") as (actual, _):
            async with self.sessions() as session:
                context = authority_context()
                root = await self.rows.aroot(session, job.space_id)
                clean(session, context)
                snapshot = await self.jobs.aread_item_snapshot(session, job_id=job.id, item_id=lease.item_id)
                clean(session, context)
            await self.app.authorize(actual, snapshot["source"])
            actor = get_current_permission_actor()
            permission = snapshot["permission"]
            context = snapshot["scope_digest"]
            source = target(
                "knowledge_file",
                permission["id"],
                context=context,
                parent_type=permission["parent_type"],
                parent_id=permission["parent_id"],
                version=permission["version"],
            )
            path = (
                snapshot["target_file"]["file_level_path"].strip("/").split("/")
                if snapshot["target_file"]["file_level_path"]
                else []
            )
            after = target(
                "knowledge_file",
                snapshot["target_file"]["id"],
                context=context,
                parent_type="folder" if path else "knowledge_space",
                parent_id=int(path[-1]) if path else root.id,
            )
            async with self.sessions() as session:
                context = authority_context()
                guarded = await self.jobs._guard_item(session, lease, self.configuration(root))
                if guarded is not None:
                    await self.rows.aassert_item(session, snapshot)
                    await self.app.projection.arequire_completed(
                        session, pairs=((source, after, permission["mode"], actor),)
                    )
                    if renew:
                        renewed = await self.jobs.arenew(session, lease.job, configuration=self.configuration(root))
                        renewed_item = await self.jobs.arenew_item(
                            session, lease, configuration=self.configuration(root)
                        )
                        if renewed is None or renewed_item is None:
                            guarded = None
                clean(session, context)
                await session.commit()
            return (
                None if guarded is None else SimpleNamespace(snapshot=snapshot, configuration=self.configuration(root))
            )

    async def acomplete(self, lease, *, result=None, error_code=None):
        from dataclasses import asdict

        from bisheng.worker.knowledge.space_copy_worker import SpaceCopyResult

        current = await self.aguard(lease)
        if current is None:
            return False
        succeeded = result is not None
        if succeeded and (
            type(result) is not SpaceCopyResult
            or result.file_id != current.snapshot["target_file"]["id"]
            or result.milvus_count != result.es_count
            or result.source_count != result.es_count
        ):
            raise KnowledgeOperationPlanChangedError()
        _, reference = await self.aread(lease.job.job_id)
        async with admission.identity(reference, required_action="upload_file") as (identity, _):
            await self.app.authorize(identity, current.snapshot["source"])
            actor = get_current_permission_actor()
            permission = current.snapshot["permission"]
            context = current.snapshot["scope_digest"]
            source = target(
                "knowledge_file",
                permission["id"],
                context=context,
                parent_type=permission["parent_type"],
                parent_id=permission["parent_id"],
                version=permission["version"],
            )
            file = current.snapshot["target_file"]
            path = file["file_level_path"].strip("/").split("/") if file["file_level_path"] else []
            after = target(
                "knowledge_file",
                file["id"],
                context=context,
                parent_type="folder" if path else "knowledge_space",
                parent_id=int(path[-1]) if path else current.snapshot["destination"]["id"],
            )
            async with self.sessions() as session:
                context = authority_context()
                guarded = await self.jobs._guard_item(session, lease, current.configuration)
                if guarded is None:
                    await session.commit()
                    return False
                await self.rows.aassert_item(session, current.snapshot)
                await self.app.projection.arequire_completed(
                    session, pairs=((source, after, permission["mode"], actor),)
                )
                await self.rows.acomplete_file(
                    session,
                    file_id=guarded[1].file_id,
                    target_id=guarded[0].space_id,
                    succeeded=succeeded,
                    user_metadata=result.user_metadata if succeeded else None,
                )
                if succeeded:
                    await self.jobs.asave_checkpoint(
                        session,
                        lease,
                        configuration=current.configuration,
                        step="copy_completed",
                        checkpoint={
                            "source_count": result.source_count,
                            "target_payload_digest": result.target_payload_digest,
                        },
                    )
                changed = await self.jobs.acomplete_item(
                    session,
                    lease,
                    configuration=current.configuration,
                    succeeded=succeeded,
                    result=asdict(result) if succeeded else None,
                    error_code=error_code,
                )
                clean(session, context)
                await session.commit()
                return changed

    async def afinalize(self, lease):
        async with self.sessions() as session:
            context = authority_context()
            header = await self.jobs.aread_transport(session, lease.job_id)
            root = await self.rows.aroot(session, header.space_id, lock=True)
            result = await self.jobs.afinalize(session, lease, configuration=self.configuration(root))
            if result is not None and result.state == "succeeded":
                root.state = 1
                await session.flush()
            clean(session, context)
            await session.commit()
            return result

    async def afail(self, job_id, revision, *, lease=None, error_code):
        admission.tenant()
        async with self.sessions() as session:
            context = authority_context()
            result = await self.jobs.afail_attempt(
                session, job_id, expected_job_revision=revision, lease=lease, error_code=error_code
            )
            clean(session, context)
            await session.commit()
            return result

    async def aretry(self, job_id, request, *, identity):
        job, reference = await self.aread(job_id)
        async with admission.identity(
            reference, current=identity, entry_kind="web", allow_other=True, required_action="upload_file"
        ) as (actual, captured):
            await self.aensure_logical(job.space_id, job_id, identity=actual, entry_kind="web")
            async with self.sessions() as session:
                context = authority_context()
                root = await self.rows.aroot(session, job.space_id, lock=True)
                if root.state == 1:
                    root.state = 2
                    await session.flush()
                result = await self.jobs.aretry_failed(
                    session,
                    job_id,
                    idempotency_key=request.idempotency_key,
                    expected_job_revision=request.expected_job_revision,
                    actor_user_id=captured["actor_user_id"],
                    actor_reference=captured,
                    configuration=self.configuration(root),
                )
                clean(session, context)
                await session.commit()
            if result.job.state == "obsolete":
                raise KnowledgeProcessingObsoleteError()
            return JobAccepted(job_id=result.job.id, state=result.job.state, reused=result.reused)

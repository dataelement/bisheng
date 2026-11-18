"""Copy-only application assembly over the unchanged lease/count/retry kernel."""

import asyncio
from contextlib import asynccontextmanager
from copy import deepcopy
from types import SimpleNamespace

from loguru import logger

from bisheng.common.constants.vectorstore_metadata import KNOWLEDGE_RAG_METADATA_SCHEMA
from bisheng.common.errcode import BaseErrorCode
from bisheng.common.errcode.knowledge import (
    KnowledgeOperationPlanChangedError,
    KnowledgeProcessingConflictError,
    KnowledgeProcessingObsoleteError,
    ResourceReferenceInvalidError,
)
from bisheng.common.errcode.permission import PermissionDeniedError
from bisheng.knowledge.application import move_processing_admission as admission
from bisheng.knowledge.application.space_copy import (
    SpaceCopyApplication,
    assert_authority,
    authority_context,
    clean,
    target,
)
from bisheng.knowledge.domain.knowledge_rag import KnowledgeRag
from bisheng.knowledge.domain.repositories.processing_fence_repository import ProcessingFenceRepository
from bisheng.knowledge.domain.repositories.space_copy_repository import SpaceCopyScope, root_facts
from bisheng.knowledge.domain.schemas.processing_job import JobAccepted
from bisheng.knowledge.domain.schemas.processing_job_acceptance import (
    ProcessingConfiguration,
    _digest,
    processing_request_facts,
)
from bisheng.knowledge.domain.services.knowledge_utils import KnowledgeUtils
from bisheng.permission.application.business_authorization import require_business_action
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

    @asynccontextmanager
    async def _logical_target(self, source_id, target_id):
        async with self.sessions() as session:
            context = authority_context()
            # Match acceptance's source-before-target order. The lock is scoped
            # to one projection, not a potentially large whole-space copy.
            await self.rows.aroot(session, source_id, lock=True)
            root = await self.rows.aroot(session, target_id, lock=True)
            if root.state not in {0, 1, 2} or root.model_transition is not None:
                raise KnowledgeOperationPlanChangedError()
            yield session, root
            clean(session, context)
            await session.commit()

    async def aensure_logical(self, target_id, job_id, *, identity=None, entry_kind=None):
        async with self.sessions() as session:
            initialized = await self.rows.aroot(session, target_id)
            if initialized.state == 1:
                if job_id is not None:
                    header = await self.jobs.aget_execution(session, job_id)
                    if header.space_id != target_id:
                        raise KnowledgeOperationPlanChangedError()
                return
        _, payload, mapping, reference = await self._logical(target_id, job_id)
        scope = SpaceCopyScope(**payload["scope"])
        async with admission.identity(
            reference, current=identity, entry_kind=entry_kind, required_action="upload_file"
        ) as (actual, _):
            authority = authority_context()
            await self.app.authorize(actual, scope.source, frozen=False)
            actor = get_current_permission_actor()
            pairs = self._pairs(payload, mapping, target_id, actor)
            # Children first, root last. Each original copy key is durable.
            for source, after, mode, operator in (*pairs[1:], pairs[0]):
                # API, worker and retries share the same SQL exclusion. Never
                # reconcile a live STAGING operation from another executor.
                async with self._logical_target(scope.source["id"], target_id):
                    async with admission.identity(
                        reference, current=identity, entry_kind=entry_kind, required_action="upload_file"
                    ) as (current, _):
                        await self.app.authorize(current, scope.source, frozen=False)
                        await self.app.projection.aexecute_or_resume(
                            source=source,
                            target=after,
                            actor=operator,
                            owner_user_id=scope.source["user_id"],
                            mode=mode,
                        )
            await self.app.authorize(actual, scope.source, frozen=False)
            async with self._logical_target(scope.source["id"], target_id) as (session, actual_root):
                await self.app.projection.arequire_completed(session, pairs=pairs)
                # A waiter must use the state read after acquiring the lock,
                # rather than the pre-lock snapshot returned by _logical.
                if actual_root.state == 0:
                    await self._initialize(
                        actual_root.model_copy(deep=True), reference["actor_user_id"], session=session
                    )
                assert_authority(authority)
                if actual_root.state == 0:
                    actual_root.state = 1
                    await session.flush()

    @staticmethod
    async def _initialize(root, actor_id, *, session):
        vector = await KnowledgeRag.init_knowledge_milvus_vectorstore(
            actor_id, knowledge=root, reference_session=session, metadata_schemas=KNOWLEDGE_RAG_METADATA_SCHEMA
        )
        # Milvus creates a new collection lazily on its first insertion.
        # A fresh copy has no collection to load until the standard schema
        # bootstrap has created it and removed its temporary seed row.
        if vector.col is None:
            vector = await asyncio.to_thread(KnowledgeUtils.ensure_milvus_schema_ready, actor_id, root, vector)
        if vector is None or vector.col is None:
            raise KnowledgeProcessingConflictError(reason="copy_vector_collection_not_ready")
        await asyncio.to_thread(vector.col.load)
        es = await KnowledgeRag.init_knowledge_es_vectorstore(
            knowledge=root, reference_session=session, metadata_schemas=KNOWLEDGE_RAG_METADATA_SCHEMA
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
        async with admission.identity(reference, required_action="upload_file") as (identity, _):
            async with self.sessions() as session:
                context = authority_context()
                root = await self.rows.aroot(session, job.space_id)
                clean(session, context)
            if root.state == 0:
                async with self.sessions() as session:
                    source = await self.rows.aroot(session, reference["space_id"])
                await self.app.authorize(identity, root_facts(source), frozen=False)
            else:
                await require_business_action(
                    identity, resource_type="knowledge_space", resource_id=root.id, action="upload_file"
                )
            async with self.sessions() as session:
                context = authority_context()
                result = await self.jobs.aclaim(
                    session, job_id, configuration=self.configuration(root), expected_job_revision=revision
                )
                clean(session, context)
                await session.commit()
            if result is not None:
                try:
                    await self.aensure_logical(job.space_id, job_id)
                except Exception as error:
                    # The caller has not received the lease yet. Persist failure
                    # with this exact lease so another executor cannot be failed.
                    code = error.Code if isinstance(error, BaseErrorCode) else ResourceReferenceInvalidError.Code
                    await self.afail(job_id, revision, lease=result, error_code=code)
                    raise
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

    async def aguard(self, lease, *, renew=False, require_source=True):
        job, reference = await self.aread(lease.job.job_id)
        async with admission.identity(reference, required_action="upload_file") as (actual, _):
            async with self.sessions() as session:
                root = await self.rows.aroot(session, job.space_id)
                snapshot = await self.jobs.aread_item_snapshot(session, job_id=job.id, item_id=lease.item_id)
                guarded = await self.jobs._guard_item(session, lease, self.configuration(root))
                if guarded is None:
                    await session.commit()
                    return None
                snapshot = deepcopy(guarded[1].checkpoint.get("copy_source_override", snapshot))
                await self.rows.aassert_target(session, snapshot)
                input_state = deepcopy(guarded[1].checkpoint.get("copy_input"))
                if require_source and input_state is None:
                    source = await self.rows.aassert_source(session, snapshot)
                    snapshot["source"] = root_facts(source)
                if renew:
                    if (
                        await self.jobs.arenew(session, lease.job, configuration=self.configuration(root)) is None
                        or await self.jobs.arenew_item(session, lease, configuration=self.configuration(root)) is None
                    ):
                        await session.commit()
                        return None
                await session.commit()
            await require_business_action(
                actual, resource_type="knowledge_space", resource_id=root.id, action="upload_file"
            )
            await require_business_action(
                actual, resource_type="knowledge_file", resource_id=snapshot["target_file"]["id"], action="visible"
            )
            if require_source and input_state is None:
                await self.app.authorize(actual, snapshot["source"], frozen=False)
                await require_business_action(
                    actual, resource_type="knowledge_file", resource_id=snapshot["source_file"]["id"], action="visible"
                )
            return SimpleNamespace(snapshot=snapshot, configuration=self.configuration(root), input_state=input_state)

    @asynccontextmanager
    async def input_writer(self, lease):
        header = (await self.aread(lease.job.job_id))[0]
        async with self.sessions() as session:
            snapshot = await self.jobs.aread_item_snapshot(session, job_id=header.id, item_id=lease.item_id)
        async with ProcessingFenceRepository(async_sessions=self.sessions).awriter(
            header.space_id, snapshot["target_file"]["id"]
        ):
            yield

    async def arecord_input(self, lease, object_name):
        current = await self.aguard(lease)
        if current is None:
            raise KnowledgeOperationPlanChangedError()
        await ProcessingFenceRepository(async_sessions=self.sessions).arecord_artifact(
            current.snapshot["destination"]["id"],
            current.snapshot["target_file"]["id"],
            object_name,
        )

    async def asave_input(self, lease, value):
        from bisheng.worker.knowledge.copy_input_store import validate_input_key

        current = await self.aguard(lease)
        if current is None:
            raise KnowledgeOperationPlanChangedError()
        validate_input_key(value, job_id=lease.job.job_id, snapshot=current.snapshot)
        async with self.sessions() as session:
            pair = await self.jobs._guard_item(session, lease, current.configuration)
            if pair is None:
                raise KnowledgeOperationPlanChangedError()
            await self.jobs.asave_checkpoint(
                session,
                lease,
                configuration=current.configuration,
                step="copy_input_ready",
                checkpoint={**pair[1].checkpoint, "copy_input": value},
            )
            await session.commit()

    async def acomplete(self, lease, *, result=None, error_code=None, failure_reason=None):
        from dataclasses import asdict

        from bisheng.worker.knowledge.space_copy_worker import SpaceCopyResult

        succeeded = result is not None
        try:
            current = await self.aguard(lease, require_source=succeeded)
        except KnowledgeOperationPlanChangedError:
            if succeeded:
                raise
            # Persist this item's failure without touching a changed/deleted File.
            job, _ = await self.aread(lease.job.job_id)
            async with self.sessions() as session:
                root = await self.rows.aroot(session, job.space_id)
                changed = await self.jobs.acomplete_item(
                    session,
                    lease,
                    configuration=self.configuration(root),
                    succeeded=False,
                    error_code=error_code,
                    failure_reason=failure_reason or "file_changed",
                )
                await session.commit()
                return changed
        if current is None:
            return False
        if succeeded and (
            type(result) is not SpaceCopyResult
            or result.file_id != current.snapshot["target_file"]["id"]
            or result.milvus_count != result.es_count
            or result.source_count != result.es_count
        ):
            raise KnowledgeOperationPlanChangedError()
        async with self.sessions() as session:
            guarded = await self.jobs._guard_item(session, lease, current.configuration)
            if guarded is None:
                await session.commit()
                return False
            await self.rows.aassert_target(session, current.snapshot)
            await self.rows.acomplete_file(
                session,
                file_id=guarded[1].file_id,
                target_id=guarded[0].space_id,
                succeeded=succeeded,
                user_metadata=result.user_metadata if succeeded else None,
                original_status=current.snapshot["source_file"]["status"],
            )
            if succeeded:
                await self.jobs.asave_checkpoint(
                    session,
                    lease,
                    configuration=current.configuration,
                    step="copy_completed",
                    checkpoint={
                        **guarded[1].checkpoint,
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
                failure_reason=failure_reason,
            )
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

    async def afail(self, job_id, revision, *, lease=None, error_code, failure_reason=None):
        admission.tenant()
        async with self.sessions() as session:
            context = authority_context()
            result = await self.jobs.afail_attempt(
                session,
                job_id,
                expected_job_revision=revision,
                lease=lease,
                error_code=error_code,
                failure_reason=failure_reason,
            )
            if result is not None and result.state in {"failed", "partial_failed"}:
                for item in await self.jobs.aretry_items(session, job_id):
                    snapshot = item.checkpoint.get("copy_source_override", item.processing_snapshot)
                    try:
                        await self.rows.aassert_target(session, snapshot)
                    except KnowledgeOperationPlanChangedError:
                        logger.warning(
                            "Copy failure leaves changed target untouched job={} file={}", job_id, item.file_id
                        )
                        continue
                    await self.rows.acomplete_file(
                        session, file_id=item.file_id, target_id=result.space_id, succeeded=False
                    )
            clean(session, context)
            await session.commit()
            return result

    async def aretry(self, job_id, request, *, identity):
        job, reference = await self.aread(job_id)
        async with admission.identity(
            reference, current=identity, entry_kind="web", allow_other=True, required_action="upload_file"
        ) as (actual, captured):
            async with self.sessions() as session:
                context = authority_context()
                root = await self.rows.aroot(session, job.space_id, lock=True)
                if root.state != 0:
                    await require_business_action(
                        actual, resource_type="knowledge_space", resource_id=root.id, action="upload_file"
                    )
                retry_items = await self.jobs.aretry_items(session, job_id)
                result = await self.jobs.aretry_failed(
                    session,
                    job_id,
                    idempotency_key=request.idempotency_key,
                    expected_job_revision=request.expected_job_revision,
                    actor_user_id=captured["actor_user_id"],
                    actor_reference=captured,
                    configuration=self.configuration(root),
                    request_options={"refresh_source": True} if request.refresh_source else None,
                )
                for item in retry_items:
                    marker = item.checkpoint.get("copy_retry_request")
                    wanted = {"key": request.idempotency_key, "refresh_source": request.refresh_source}
                    if result.reused:
                        if marker is not None and marker != wanted:
                            from bisheng.common.errcode.knowledge import KnowledgeIdempotencyConflictError

                            raise KnowledgeIdempotencyConflictError()
                        continue
                    checkpoint = deepcopy(item.checkpoint)
                    snapshot = checkpoint.get("copy_source_override", item.processing_snapshot)
                    if request.refresh_source:
                        try:
                            async with session.begin_nested():
                                await self.rows.aassert_target(session, snapshot)
                                source = await self.rows.acurrent_source(session, snapshot)
                                await self.app.authorize(actual, source["source"], frozen=False)
                                await require_business_action(
                                    actual,
                                    resource_type="knowledge_file",
                                    resource_id=source["source_file"]["id"],
                                    action="visible",
                                )
                                for name in (
                                    "object_name",
                                    "preview_file_object_name",
                                    "bbox_object_name",
                                    "thumbnails",
                                ):
                                    key = snapshot["target_file"].get(name)
                                    if key:
                                        await ProcessingFenceRepository(async_sessions=self.sessions).arecord_artifact(
                                            root.id, item.file_id, key, session=session
                                        )
                                checkpoint["copy_source_override"] = await self.rows.afreshen_target(
                                    session, snapshot, source
                                )
                                checkpoint.pop("copy_input", None)
                                item.step = "pending"
                        except (KnowledgeOperationPlanChangedError, PermissionDeniedError):
                            logger.warning("Copy retry leaves changed input untouched job={} item={}", job_id, item.id)
                            item.state, item.error_code, item.error_message = "failed", 10998, "file_changed"
                    checkpoint["copy_retry_request"] = wanted
                    item.checkpoint = checkpoint
                await session.flush()
                await self.jobs._refresh_counts(session, result.job)
                await session.flush()
                clean(session, context)
                await session.commit()
            if result.job.state == "obsolete":
                raise KnowledgeProcessingObsoleteError()
            return JobAccepted(job_id=result.job.id, state=result.job.state, reused=result.reused)

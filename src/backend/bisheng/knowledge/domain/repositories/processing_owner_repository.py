"""Actual full-version scope in the caller's native processing transaction."""

import hashlib
import json
from copy import deepcopy
from dataclasses import dataclass

from loguru import logger
from sqlalchemy import and_, or_, update
from sqlmodel import select

from bisheng.common.errcode.knowledge import (
    KnowledgeFileFailedError,
    KnowledgeOperationPlanConflictError,
    KnowledgeProcessingConflictError,
)
from bisheng.common.errcode.knowledge_space import SpaceNotFoundError
from bisheng.core.context.tenant import get_current_tenant_id, strict_tenant_filter
from bisheng.knowledge.domain.models.knowledge import Knowledge, KnowledgeState, KnowledgeTypeEnum
from bisheng.knowledge.domain.models.knowledge_document import KnowledgeDocument
from bisheng.knowledge.domain.models.knowledge_document_version import KnowledgeDocumentVersion
from bisheng.knowledge.domain.models.knowledge_file import FileType, KnowledgeFile, KnowledgeFileStatus
from bisheng.knowledge.domain.models.knowledge_processing_item import KnowledgeProcessingItem
from bisheng.knowledge.domain.models.knowledge_processing_job import KnowledgeProcessingJob
from bisheng.knowledge.domain.models.knowledge_processing_retry import KnowledgeProcessingRetryReceipt
from bisheng.knowledge.domain.repositories.model_reference_repository import KnowledgeModelReferenceRepository
from bisheng.knowledge.domain.repositories.processing_job_repository import (
    ItemLease,
    ProcessingConfiguration,
    ProcessingJobRepository,
)
from bisheng.knowledge.domain.schemas.processing_job import ProcessingTargetInput, ResourceVersionTarget


@dataclass(frozen=True, slots=True)
class ProcessingScopeVersion:
    target: ResourceVersionTarget
    file_name: str
    parent_id: int | None
    file_level_path: str | None
    version_no: int
    is_primary: bool
    status: int | None
    split_rule: str | None
    revision: str
    source_revision: str
    file_source: str | None


class ProcessingOwnerRepository:
    _file_kinds = frozenset({"file_reprocess", "file_resplit"})
    _file_patch_fields = frozenset(
        {
            "parse_type",
            "preview_file_object_name",
            "bbox_object_name",
            "abstract",
            "user_metadata",
            "simhash",
            "similar_status",
            "file_encoding",
            "thumbnails",
        }
    )

    async def aassert_empty_model_change(self, session, space_id) -> str:
        """Lock the real physical and logical scope; an empty JOIN is no proof."""
        root = await KnowledgeModelReferenceRepository().aget(session, space_id, for_update=True)
        if root is None or root.type != KnowledgeTypeEnum.SPACE.value:
            raise SpaceNotFoundError()
        if root.state in {KnowledgeState.COPYING.value, KnowledgeState.REBUILDING.value} or root.model_transition:
            raise KnowledgeProcessingConflictError(reason="processing_space_not_ready")
        with strict_tenant_filter():
            active = (
                await session.exec(
                    select(KnowledgeProcessingJob.id)
                    .where(
                        KnowledgeProcessingJob.space_id == space_id,
                        KnowledgeProcessingJob.state.in_(("accepted", "running")),
                    )
                    .with_for_update()
                    .limit(1)
                )
            ).first()
        if active is not None:
            raise KnowledgeProcessingConflictError(reason="processing_target_job_active")
        physical = KnowledgeFile.__table__
        # C3 scopes the selected root. Child columns stay visible to integrity
        # checks even when their tenant/space link is corrupt, as in aload_scope.
        files_query = (
            select(Knowledge, KnowledgeDocument, KnowledgeDocumentVersion, *physical.c)
            .select_from(Knowledge)
            .join(physical, physical.c.knowledge_id == Knowledge.id)
            .outerjoin(KnowledgeDocumentVersion, KnowledgeDocumentVersion.knowledge_file_id == physical.c.id)
            .outerjoin(KnowledgeDocument, KnowledgeDocument.id == KnowledgeDocumentVersion.document_id)
            .where(
                Knowledge.id == space_id,
                or_(physical.c.file_type != FileType.DIR.value, physical.c.file_type.is_(None)),
            )
            .order_by(physical.c.id, KnowledgeDocumentVersion.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        documents_query = (
            select(Knowledge, KnowledgeDocument, KnowledgeDocumentVersion)
            .join(KnowledgeDocument, KnowledgeDocument.knowledge_id == Knowledge.id)
            .outerjoin(KnowledgeDocumentVersion, KnowledgeDocumentVersion.document_id == KnowledgeDocument.id)
            .where(Knowledge.id == space_id)
            .order_by(KnowledgeDocument.id, KnowledgeDocumentVersion.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        with strict_tenant_filter():
            file_rows = (await session.exec(files_query)).all()
            document_rows = (await session.exec(documents_query)).all()
        files, versions, documents, facts = set(), set(), {}, []
        for joined in file_rows:
            _, document, version = joined[:3]
            row = {column.name: joined._mapping[column] for column in physical.c}
            if (
                row["tenant_id"] != root.tenant_id
                or row["file_type"] != FileType.FILE.value
                or row["id"] in files
                or document is None
                or document.knowledge_id != space_id
                or version is None
                or version.version_no <= 0
            ):
                raise KnowledgeOperationPlanConflictError(reason="processing_version_scope_incomplete")
            if row["status"] not in {3, 6, 7}:
                raise KnowledgeProcessingConflictError(reason="processing_scope_not_empty")
            files.add(row["id"])
            versions.add(version.id)
            documents.setdefault(document.id, []).append(version)
            facts.append(
                {
                    "file": KnowledgeFile(**row).model_dump(mode="json"),
                    "document": document.model_dump(mode="json"),
                    "version": version.model_dump(mode="json"),
                }
            )
        actual_versions = set()
        for _, document, version in document_rows:
            if document.id not in documents or version is None or version.id not in versions:
                raise KnowledgeOperationPlanConflictError(reason="processing_version_scope_incomplete")
            primary = [value.id for value in documents[document.id] if value.is_primary]
            if primary != [document.primary_version_id]:
                raise KnowledgeOperationPlanConflictError(reason="processing_version_scope_incomplete")
            actual_versions.add(version.id)
        if actual_versions != versions:
            raise KnowledgeOperationPlanConflictError(reason="processing_version_scope_incomplete")
        return hashlib.sha256(
            json.dumps(facts, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode()
        ).hexdigest()

    async def aassert_file_processing_available(self, session, space_id, scope, *, exclude_job_id=None):
        root = await KnowledgeModelReferenceRepository().aget(session, space_id, for_update=True)
        if root is None or root.state != KnowledgeState.PUBLISHED.value or root.model_transition is not None:
            raise KnowledgeProcessingConflictError(reason="processing_space_not_ready")
        if not scope or any(row.status not in {2, 3, 6, 7} for row in scope):
            raise KnowledgeProcessingConflictError(reason="processing_file_state_not_ready")
        item, job = KnowledgeProcessingItem, KnowledgeProcessingJob
        pairs = [(row.target.file_id, row.target.version_id) for row in scope]
        base = (
            select(job.id)
            .join(item, and_(item.job_id == job.id, item.tenant_id == job.tenant_id))
            .where(
                job.space_id == space_id,
                job.state.in_(("accepted", "running")),
            )
        )
        if exclude_job_id is not None:
            base = base.where(job.id != exclude_job_id)
        for offset in range(0, len(pairs), 200):
            query = base.where(
                or_(
                    *(
                        and_(item.file_id == file_id, item.version_id == version_id)
                        for file_id, version_id in pairs[offset : offset + 200]
                    )
                )
            )
            with strict_tenant_filter():
                conflict = (await session.exec(query.limit(1))).first()
            if conflict is not None:
                raise KnowledgeProcessingConflictError(reason="processing_target_job_active")
        return root

    async def _file(self, session, space_id, file_id):
        with strict_tenant_filter():
            row = (
                await session.exec(
                    select(KnowledgeFile)
                    .where(KnowledgeFile.id == file_id, KnowledgeFile.knowledge_id == space_id)
                    .with_for_update()
                    .execution_options(populate_existing=True)
                )
            ).one_or_none()
        if row is None or row.tenant_id != get_current_tenant_id() or row.file_type != 1:
            raise KnowledgeOperationPlanConflictError(reason="processing_file_owner_changed")
        return row

    async def aqueue_file_processing(self, session, space_id, items, *, rules, actor_user_id):
        for item in items:
            row = await self._file(session, space_id, item.target.file_id)
            if row.status not in {2, 3, 6, 7}:
                raise KnowledgeProcessingConflictError(reason="processing_file_state_not_ready")
            row.status, row.remark, row.split_rule, row.updater_id = 5, "", rules[item.target.file_id], actor_user_id
        await session.flush()

    async def _processing_file(self, session, job, item):
        if job.kind not in self._file_kinds or item.expected_space_id != job.space_id:
            raise KnowledgeOperationPlanConflictError(reason="processing_file_kind_changed")
        scope = await self.aload_scope(
            session,
            job.space_id,
            targets=[{"file_id": item.file_id, "document_id": item.document_id, "version_id": item.version_id}],
            for_update=True,
        )
        if (
            len(scope) != 1
            or scope[0].parent_id != item.expected_parent_id
            or scope[0].source_revision != item.processing_snapshot.get("source_revision")
        ):
            raise KnowledgeOperationPlanConflictError(reason="processing_file_source_changed")
        return await self._file(session, job.space_id, item.file_id)

    async def aqueue_retry_file_processing(self, session, job, *, jobs):
        root, actual = await self._attempt(session, job.id, jobs)
        if (
            actual is not job
            or root is None
            or root.state != 1
            or root.model_transition is not None
            or (root.model_config_revision, root.index_generation)
            != (job.expected_model_config_revision, job.expected_index_generation)
        ):
            raise KnowledgeProcessingConflictError(reason="processing_file_retry_conflict")
        with strict_tenant_filter():
            items = (
                await session.exec(
                    select(KnowledgeProcessingItem)
                    .where(KnowledgeProcessingItem.job_id == job.id, KnowledgeProcessingItem.state == "pending")
                    .with_for_update()
                )
            ).all()
        scope = await self.aload_scope(
            session,
            job.space_id,
            targets=[
                {"file_id": item.file_id, "document_id": item.document_id, "version_id": item.version_id}
                for item in items
            ],
            for_update=True,
        )
        if items:
            await self.aassert_file_processing_available(session, job.space_id, scope, exclude_job_id=job.id)
        for item in items:
            row = await self._processing_file(session, job, item)
            if row.status not in {3, 6, 7}:
                raise KnowledgeProcessingConflictError(reason="processing_file_retry_conflict")
            row.status, row.remark = 5, ""
        await session.flush()

    async def aguard_processed_file(self, session, lease, *, jobs):
        root, _ = await self._attempt(session, lease.job.job_id, jobs)
        if root is None:
            raise KnowledgeOperationPlanConflictError(reason="processing_owner_missing")
        guarded = await jobs._guard_item(
            session, lease, ProcessingConfiguration(root.model_config_revision, root.index_generation)
        )
        if guarded is None:
            return None
        job, item = guarded
        if root.model_transition is not None or root.state != 1:
            raise KnowledgeProcessingConflictError(reason="processing_space_not_ready")
        row = await self._processing_file(session, job, item)
        if row.status not in {1, 5}:
            raise KnowledgeProcessingConflictError(reason="processing_file_state_changed")
        return job, item, row

    async def astart_processed_file(self, session, lease, *, jobs):
        guarded = await self.aguard_processed_file(session, lease, jobs=jobs)
        if guarded is None:
            return False
        guarded[2].status = 1
        await session.flush()
        return True

    async def acomplete_processed_file(self, session, lease, *, jobs, outcome):
        if (
            type(outcome.status) is not int
            or outcome.status not in {2, 3, 7}
            or type(outcome.chunk_count) is not int
            or outcome.chunk_count < 0
            or (outcome.status == 2 and outcome.chunk_count == 0)
            or not isinstance(outcome.file_patch, dict)
            or set(outcome.file_patch) - self._file_patch_fields
        ):
            raise KnowledgeOperationPlanConflictError(reason="processing_file_outcome_invalid")
        guarded = await self.aguard_processed_file(session, lease, jobs=jobs)
        if guarded is None:
            return False
        job, item, row = guarded
        if outcome.file_id != item.file_id or outcome.source_revision != item.processing_snapshot["source_revision"]:
            raise KnowledgeOperationPlanConflictError(reason="processing_file_outcome_changed")
        current = ProcessingConfiguration(job.expected_model_config_revision, job.expected_index_generation)
        if not await jobs.acomplete_item(
            session,
            lease,
            configuration=current,
            succeeded=outcome.status == 2,
            result={"chunk_count": outcome.chunk_count, "file_status": outcome.status},
            error_code=outcome.error_code,
        ):
            return False
        row.status = outcome.status
        row.remark = (
            ""
            if outcome.status == 2
            else json.dumps(
                {
                    "code": outcome.error_code or KnowledgeFileFailedError.Code,
                    **({"reason": "sensitive_check"} if outcome.status == 7 else {}),
                }
            )
        )
        if outcome.status == 2:
            for key, value in outcome.file_patch.items():
                setattr(row, key, deepcopy(value))
        await session.flush()
        return True

    async def _attempt(self, session, job_id, jobs):
        candidate = await jobs.aget(session, job_id)
        root = await KnowledgeModelReferenceRepository().aget(session, candidate.space_id, for_update=True)
        job = await jobs._job(session, job_id, lock=True)
        return root, job

    async def _retry_evidence(self, session, job):
        with strict_tenant_filter():
            receipt = (
                await session.exec(
                    select(KnowledgeProcessingRetryReceipt)
                    .where(KnowledgeProcessingRetryReceipt.job_id == job.id)
                    .order_by(
                        KnowledgeProcessingRetryReceipt.accepted_job_revision.desc(),
                        KnowledgeProcessingRetryReceipt.id.desc(),
                    )
                    .limit(1)
                    .with_for_update()
                    .execution_options(populate_existing=True)
                )
            ).one_or_none()
            other = (
                await session.exec(
                    select(KnowledgeProcessingJob.id)
                    .where(
                        KnowledgeProcessingJob.space_id == job.space_id,
                        KnowledgeProcessingJob.id != job.id,
                        KnowledgeProcessingJob.state.in_(("accepted", "running")),
                    )
                    .limit(1)
                )
            ).first()
        return receipt, other

    @staticmethod
    def _current_operation(root, job):
        return (
            root is not None
            and root.type == KnowledgeTypeEnum.SPACE.value
            and root.tenant_id == job.tenant_id
            and root.model_transition is None
            and root.model_config_revision == job.expected_model_config_revision
            and root.index_generation == job.expected_index_generation
            and type(job.accepted_model_config_revision) is int
            and job.expected_model_config_revision == job.accepted_model_config_revision + 1
            and bool(job.parameters.get("operation_id"))
        )

    async def abegin_retry_fence(self, session, job, *, jobs):
        root, locked = await self._attempt(session, job.id, jobs)
        receipt, other = await self._retry_evidence(session, locked)
        if (
            locked is not job
            or locked.state != "accepted"
            or receipt is None
            or receipt.tenant_id != job.tenant_id
            or receipt.accepted_job_revision != job.revision
            or other is not None
            or root is None
            or (root.model_config_revision, root.index_generation)
            != (job.expected_model_config_revision, job.expected_index_generation)
        ):
            raise KnowledgeProcessingConflictError(reason="processing_retry_fence_conflict")
        if root.model_transition is not None:
            if root.model_transition.get("operation_id") != job.parameters.get("operation_id"):
                raise KnowledgeProcessingConflictError(reason="processing_retry_fence_conflict")
            return  # The existing pending operation already owns its fence.
        if not self._current_operation(root, job) or root.state != KnowledgeState.PUBLISHED.value:
            raise KnowledgeProcessingConflictError(reason="processing_retry_fence_conflict")
        if receipt.item_count == 0:
            return  # Finalization has no provider work and never edits successful checkpoints.
        with strict_tenant_filter():
            anchor = (
                await session.exec(
                    select(KnowledgeProcessingItem)
                    .where(KnowledgeProcessingItem.job_id == job.id, KnowledgeProcessingItem.state == "pending")
                    .order_by(
                        KnowledgeProcessingItem.file_id, KnowledgeProcessingItem.version_id, KnowledgeProcessingItem.id
                    )
                    .limit(1)
                    .with_for_update()
                    .execution_options(populate_existing=True)
                )
            ).one_or_none()
        if anchor is None or anchor.tenant_id != job.tenant_id:
            raise KnowledgeProcessingConflictError(reason="processing_retry_fence_conflict")
        checkpoint = deepcopy(anchor.checkpoint)
        checkpoint["retry_fence"] = {
            "schema_version": 1,
            "job_id": job.id,
            "retry_receipt_id": receipt.id,
            "accepted_job_revision": receipt.accepted_job_revision,
            "model_config_revision": root.model_config_revision,
            "index_generation": root.index_generation,
            "first_claim_generation": job.claim_generation + 1,
            "previous_state": root.state,
        }
        anchor.checkpoint = checkpoint
        root.state = KnowledgeState.REBUILDING.value
        await session.flush()

    async def _owned_retry_fence(self, session, root, job, *, jobs, lease, expected_job_revision):
        if not self._current_operation(root, job) or root.state != KnowledgeState.REBUILDING.value:
            return False
        if lease is not None:
            if not jobs._active_job_lease(job, lease):
                return False
        elif job.state != "accepted" or job.revision != expected_job_revision:
            return False
        receipt, other = await self._retry_evidence(session, job)
        if receipt is None or receipt.tenant_id != job.tenant_id or other is not None:
            return False
        with strict_tenant_filter():
            items = (
                await session.exec(
                    select(KnowledgeProcessingItem)
                    .where(KnowledgeProcessingItem.job_id == job.id)
                    .with_for_update()
                    .execution_options(populate_existing=True)
                )
            ).all()
        for item in items:
            marker = item.checkpoint.get("retry_fence")
            if not isinstance(marker, dict) or item.tenant_id != job.tenant_id:
                continue
            first = marker.get("first_claim_generation")
            if type(first) is not int or first <= 0:
                continue
            expected = {
                "schema_version": 1,
                "job_id": job.id,
                "retry_receipt_id": receipt.id,
                "accepted_job_revision": receipt.accepted_job_revision,
                "model_config_revision": root.model_config_revision,
                "index_generation": root.index_generation,
                "first_claim_generation": first,
                "previous_state": KnowledgeState.PUBLISHED.value,
            }
            # Canonical JSON keeps bools distinct from revision integers.
            if json.dumps(marker, sort_keys=True) != json.dumps(expected, sort_keys=True):
                continue
            if lease is not None:
                return job.claim_generation >= first
            return job.claim_generation + 1 == first and job.revision == receipt.accepted_job_revision
        return False

    async def afail_attempt(self, session, job_id, *, jobs, expected_job_revision, error_code, lease=None):
        root, job = await self._attempt(session, job_id, jobs)
        unfinished = ()
        if job.kind in self._file_kinds:
            with strict_tenant_filter():
                unfinished = (
                    await session.exec(
                        select(KnowledgeProcessingItem)
                        .where(
                            KnowledgeProcessingItem.job_id == job.id,
                            KnowledgeProcessingItem.state.in_(("pending", "running")),
                        )
                        .with_for_update()
                    )
                ).all()
        release = await self._owned_retry_fence(
            session, root, job, jobs=jobs, lease=lease, expected_job_revision=expected_job_revision
        )
        failed = await jobs.afail_attempt(
            session, job_id, expected_job_revision=expected_job_revision, error_code=error_code, lease=lease
        )
        if release and failed is not None and failed.state in {"failed", "partial_failed"}:
            root.state = KnowledgeState.PUBLISHED.value
            await session.flush()
        if failed is not None and failed.state in {"failed", "partial_failed"}:
            for item in unfinished:
                try:
                    row = await self._processing_file(session, job, item)
                except KnowledgeOperationPlanConflictError:
                    # A replaced/deleted source is no longer owned by this
                    # attempt. Persist its job failure without mutating it.
                    logger.warning(
                        "Processing failure leaves changed source untouched job={} file={}", job.id, item.file_id
                    )
                    continue
                if row.status in {1, 5}:
                    row.status, row.remark = 3, json.dumps({"code": error_code})
            await session.flush()
        return failed

    async def afinalize_attempt(self, session, lease, *, jobs):
        root, job = await self._attempt(session, lease.job_id, jobs)
        release = await self._owned_retry_fence(
            session, root, job, jobs=jobs, lease=lease, expected_job_revision=job.revision
        )
        if root is None:
            raise KnowledgeProcessingConflictError(reason="processing_owner_missing")
        finished = await jobs.afinalize(
            session, lease, configuration=ProcessingConfiguration(root.model_config_revision, root.index_generation)
        )
        if release and finished is not None and finished.state in {"succeeded", "failed", "partial_failed"}:
            root.state = KnowledgeState.PUBLISHED.value
            await session.flush()
        return finished

    async def acomplete_file(
        self,
        session,
        lease: ItemLease,
        *,
        jobs: ProcessingJobRepository,
        succeeded: bool,
        error_code: int | None = None,
    ) -> bool:
        if type(succeeded) is not bool:
            raise TypeError("file completion requires an actual success outcome")
        job = await jobs.aget(session, lease.job.job_id)
        root = await KnowledgeModelReferenceRepository().aget(session, job.space_id, for_update=True)
        if root is None or root.type != KnowledgeTypeEnum.SPACE.value:
            raise KnowledgeOperationPlanConflictError(reason="processing_file_owner_changed")
        current = ProcessingConfiguration(root.model_config_revision, root.index_generation)
        guarded = await jobs._guard_item(session, lease, current)
        if guarded is None:
            return False
        job, item = guarded
        if item.expected_space_id != job.space_id:
            raise KnowledgeOperationPlanConflictError(reason="processing_file_owner_changed")
        versions = await self.aload_scope(
            session,
            job.space_id,
            targets=[
                {
                    "file_id": item.file_id,
                    "document_id": item.document_id,
                    "version_id": item.version_id,
                }
            ],
            for_update=True,
        )
        if len(versions) != 1 or versions[0].parent_id != item.expected_parent_id:
            raise KnowledgeOperationPlanConflictError(reason="processing_file_parent_changed")
        if versions[0].status not in {2, 3, 6}:
            raise KnowledgeProcessingConflictError(reason="processing_file_state_not_ready")
        if not await jobs.acomplete_item(
            session, lease, configuration=current, succeeded=succeeded, error_code=error_code
        ):
            return False
        # Bulk UPDATE receives no C3 injection; pin all three actual owning
        # identities. Item/count and file status commit or roll back together.
        status = KnowledgeFileStatus.SUCCESS.value if succeeded else KnowledgeFileStatus.FAILED.value
        remark = "" if succeeded else json.dumps({"code": error_code or KnowledgeFileFailedError.Code})
        result = await session.execute(
            update(KnowledgeFile)
            .where(
                KnowledgeFile.id == item.file_id,
                KnowledgeFile.tenant_id == job.tenant_id,
                KnowledgeFile.knowledge_id == item.expected_space_id,
            )
            .values(status=status, remark=remark)
            .execution_options(synchronize_session=False)
        )
        if result.rowcount != 1:
            raise KnowledgeOperationPlanConflictError(reason="processing_file_owner_changed")
        await session.flush()
        return True

    @staticmethod
    def _parent(path):
        if path in (None, "", "/"):
            return None
        try:
            parents = tuple(int(value) for value in path.strip("/").split("/"))
            if any(value <= 0 for value in parents):
                raise ValueError("invalid folder identity")
            return parents[-1]
        except (TypeError, ValueError, AttributeError) as error:
            raise KnowledgeOperationPlanConflictError(reason="processing_folder_path_invalid") from error

    async def aload_scope(
        self, session, space_id, targets=None, for_update=False
    ) -> tuple[ProcessingScopeVersion, ...]:
        tenant = get_current_tenant_id()
        if type(tenant) is not int or tenant <= 0:
            raise RuntimeError("processing scope requires a concrete tenant")
        if type(for_update) is not bool:
            raise TypeError("for_update must be explicit")
        space_query = select(Knowledge).where(Knowledge.id == space_id, Knowledge.type == KnowledgeTypeEnum.SPACE.value)
        if for_update:
            space_query = space_query.with_for_update().execution_options(populate_existing=True)
        with strict_tenant_filter():
            space = (await session.exec(space_query)).one_or_none()
        if space is None or space.tenant_id != tenant:
            raise SpaceNotFoundError()
        requested = None if targets is None else tuple(ProcessingTargetInput.model_validate(value) for value in targets)
        if requested is not None:
            keys = {(value.file_id, value.version_id) for value in requested}
            if len(keys) != len(requested):
                raise KnowledgeOperationPlanConflictError(reason="processing_duplicate_target")
            if not requested:
                return ()
        # Ownership follows the actual root and version FK. The outer join is
        # deliberate: a broken/cross-space physical link is an incomplete plan,
        # never a silently skipped version. Tenant equality is a relationship
        # integrity predicate; C3 still supplies the current candidate scope.
        physical_table = KnowledgeFile.__table__
        query = (
            select(Knowledge, KnowledgeDocument, KnowledgeDocumentVersion, *physical_table.c)
            .join(KnowledgeDocument, KnowledgeDocument.knowledge_id == Knowledge.id)
            .join(KnowledgeDocumentVersion, KnowledgeDocumentVersion.document_id == KnowledgeDocument.id)
            .outerjoin(
                physical_table,
                and_(
                    physical_table.c.id == KnowledgeDocumentVersion.knowledge_file_id,
                    physical_table.c.knowledge_id == KnowledgeDocument.knowledge_id,
                    physical_table.c.tenant_id == Knowledge.tenant_id,
                ),
            )
            .where(KnowledgeDocument.knowledge_id == space_id)
            .order_by(physical_table.c.id, KnowledgeDocumentVersion.id, KnowledgeDocument.id)
        )
        if requested is not None:
            version_ids = sorted({value.version_id for value in requested})
            query = query.where(
                or_(
                    *(
                        KnowledgeDocumentVersion.id.in_(version_ids[offset : offset + 500])
                        for offset in range(0, len(version_ids), 500)
                    )
                )
            )
        if for_update:
            query = query.with_for_update().execution_options(populate_existing=True)
        with strict_tenant_filter():
            rows = (await session.exec(query)).all()
        result = []
        for joined in rows:
            root, document, version = joined[:3]
            # C3 scopes the selected owned root. Raw child column projection
            # keeps its integrity-checked OUTER JOIN intact: injecting a child
            # tenant WHERE would hide broken links rather than report them.
            physical = KnowledgeFile(**{column.name: joined._mapping[column] for column in physical_table.c})
            if (
                root.tenant_id != tenant
                or physical.id is None
                or physical.tenant_id != tenant
                or physical.knowledge_id != space_id
                or physical.file_type != FileType.FILE.value
            ):
                raise KnowledgeOperationPlanConflictError(reason="processing_version_scope_incomplete")
            target = ResourceVersionTarget(file_id=physical.id, document_id=document.id, version_id=version.id)
            facts = {
                "document": document.model_dump(mode="json"),
                "version": version.model_dump(mode="json"),
                "file": physical.model_dump(mode="json"),
            }
            digest = hashlib.sha256(
                json.dumps(facts, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode()
            ).hexdigest()
            source_facts = {
                "file": {
                    key: getattr(physical, key)
                    for key in (
                        "id",
                        "tenant_id",
                        "knowledge_id",
                        "file_type",
                        "file_source",
                        "object_name",
                        "md5",
                        "file_size",
                        "file_name",
                        "file_level_path",
                        "user_metadata",
                    )
                },
                "document_id": document.id,
                "version_id": version.id,
                "version_no": version.version_no,
            }
            source_digest = hashlib.sha256(
                json.dumps(
                    source_facts, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False
                ).encode()
            ).hexdigest()
            result.append(
                ProcessingScopeVersion(
                    target,
                    physical.file_name,
                    self._parent(physical.file_level_path),
                    physical.file_level_path,
                    version.version_no,
                    version.is_primary,
                    physical.status,
                    physical.split_rule,
                    digest,
                    source_digest,
                    physical.file_source,
                )
            )
        if requested is not None:
            actual = {(value.target.file_id, value.target.version_id): value.target.document_id for value in result}
            if set(actual) != keys or any(
                value.document_id is not None and actual.get((value.file_id, value.version_id)) != value.document_id
                for value in requested
            ):
                raise KnowledgeOperationPlanConflictError(reason="processing_version_scope_changed")
        return tuple(result)

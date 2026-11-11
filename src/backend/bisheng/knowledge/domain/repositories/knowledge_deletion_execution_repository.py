"""Native deletion business phases on the original confirmation and cleanup rows."""

from copy import deepcopy

from sqlalchemy import delete, select, update

from bisheng.common.errcode.knowledge import KnowledgeOperationPlanConflictError
from bisheng.common.models.space_channel_member import BusinessTypeEnum, SpaceChannelMember
from bisheng.core.context.tenant import get_current_tenant_id, is_tenant_filter_bypassed, strict_tenant_filter
from bisheng.knowledge.domain.models.knowledge import Knowledge
from bisheng.knowledge.domain.models.knowledge_document import KnowledgeDocument
from bisheng.knowledge.domain.models.knowledge_document_version import KnowledgeDocumentVersion
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile
from bisheng.knowledge.domain.models.knowledge_operation_plan import KnowledgeOperationPlan
from bisheng.knowledge.domain.models.knowledge_space_delete_job import KnowledgeSpaceDeleteJob, deletion_now
from bisheng.knowledge.domain.models.knowledge_space_tag_library import KnowledgeSpaceTagLibrary
from bisheng.knowledge.domain.repositories.model_reference_repository import KnowledgeModelReferenceRepository
from bisheng.knowledge.domain.repositories.operation_plan_repository import OperationPlanRepository
from bisheng.knowledge.domain.repositories.reference_target_repository import revision
from bisheng.resource_reference.application.contracts import TransactionIdentity

OPERATIONS = frozenset({"knowledge_file_delete", "knowledge_space_clear", "knowledge_space_delete"})


class KnowledgeDeletionExecutionRepository:
    @staticmethod
    def context(session):
        tenant = get_current_tenant_id()
        if type(tenant) is not int or tenant <= 0 or is_tenant_filter_bypassed() or not session.in_transaction():
            raise KnowledgeOperationPlanConflictError(reason="knowledge_delete_native_scope_required")
        return tenant, TransactionIdentity.capture(session)

    @classmethod
    def current(cls, session, context):
        tenant, transaction = context
        transaction.assert_current(session)
        if type(get_current_tenant_id()) is not int or get_current_tenant_id() != tenant or is_tenant_filter_bypassed():
            raise KnowledgeOperationPlanConflictError(reason="knowledge_delete_context_changed")

    async def aroot(self, session, space_id, *, lock=False):
        context = self.context(session)
        row = await KnowledgeModelReferenceRepository().aget(session, space_id, for_update=lock)
        self.current(session, context)
        if row is None or row.type != 3:
            raise KnowledgeOperationPlanConflictError(reason="knowledge_delete_root_unavailable")
        return row, revision(row)

    async def aget(self, session, job_id, *, lock=False):
        context = self.context(session)
        statement = (
            select(KnowledgeSpaceDeleteJob)
            .where(KnowledgeSpaceDeleteJob.id == job_id, KnowledgeSpaceDeleteJob.tenant_id == context[0])
            .execution_options(populate_existing=True)
        )
        with session.no_autoflush, strict_tenant_filter():
            row = (await session.execute(statement.with_for_update() if lock else statement)).scalar_one_or_none()
        self.current(session, context)
        return row

    async def aresolve_historical_version(self, session, *, version_id):
        context = self.context(session)
        version, file, root = KnowledgeDocumentVersion.__table__, KnowledgeFile.__table__, Knowledge.__table__
        query = (
            select(
                version.c.id,
                version.c.document_id,
                version.c.version_no,
                version.c.is_primary,
                file.c.id.label("file_id"),
                file.c.file_name,
                file.c.knowledge_id,
            )
            .select_from(
                version.join(file, file.c.id == version.c.knowledge_file_id).join(
                    root, root.c.id == file.c.knowledge_id
                )
            )
            .where(
                version.c.id == version_id,
                file.c.tenant_id == context[0],
                root.c.tenant_id == context[0],
                root.c.type == 3,
            )
        )
        with session.no_autoflush:
            row = (await session.execute(query)).mappings().one_or_none()
        self.current(session, context)
        return None if row is None else dict(row)

    async def apeek_plan(self, session, plan_id):
        context = self.context(session)
        with session.no_autoflush, strict_tenant_filter():
            row = (
                await session.execute(
                    select(KnowledgeOperationPlan).where(
                        KnowledgeOperationPlan.id == plan_id, KnowledgeOperationPlan.tenant_id == context[0]
                    )
                )
            ).scalar_one_or_none()
        self.current(session, context)
        if row is None or row.operation not in OPERATIONS:
            raise KnowledgeOperationPlanConflictError(reason="knowledge_delete_plan_unavailable")
        OperationPlanRepository()._validate(row, check_expiry=False)
        session.expunge(row)
        return row

    async def arefresh_continuation(self, session, *, job_id, reference):
        job = await self.aget(session, job_id, lock=True)
        if job is None:
            raise KnowledgeOperationPlanConflictError(reason="knowledge_delete_job_missing")
        if job.state != "SUCCEEDED" and (job.lease_until is None or job.lease_until <= deletion_now()):
            job.manifest = {**job.manifest, "continuation": deepcopy(reference)}
            job.next_attempt_at = deletion_now()
            session.add(job)
            await session.flush()
        return job

    async def acreate(self, session, *, plan, manifest):
        context = self.context(session)
        if plan.operation not in OPERATIONS or plan.operation_id != plan.id or plan.tenant_id != context[0]:
            raise KnowledgeOperationPlanConflictError(reason="knowledge_delete_consumed_plan_required")
        job = KnowledgeSpaceDeleteJob(
            id=plan.id,
            tenant_id=context[0],
            space_id=plan.space_id,
            applicant_user_id=plan.actor_user_id,
            operation_type=plan.operation,
            business_phase="prepared",
            manifest=deepcopy(manifest),
        )
        session.add(job)
        await session.flush()
        self.current(session, context)
        return job

    @staticmethod
    def validate_job(job, plan):
        manifest = job.manifest
        execution = manifest["execution"]
        if (
            (job.id, job.tenant_id, job.space_id, job.operation_type, job.applicant_user_id)
            != (plan.id, plan.tenant_id, plan.space_id, plan.operation, plan.actor_user_id)
            or plan.operation_id != job.id
            or execution["confirmation_id"] != plan.id
            or execution["plan_digest"] != plan.plan_digest
            or execution["actor_reference"] != plan.actor_reference
            or execution["scope_digest"] != plan.target_revisions["selected_scope"]
            or job.business_phase not in {"prepared", "finalized"}
        ):
            raise KnowledgeOperationPlanConflictError(reason="knowledge_delete_job_changed")
        expected = {(row["resource_type"], str(row["resource_id"])) for row in manifest["fga_resources"]}
        if plan.operation == "knowledge_space_delete":
            expected.add(("knowledge_space", str(plan.space_id)))
        actual = [(row["resource_type"], str(row["resource_id"])) for row in manifest["projection_targets"]]
        if len(actual) != len(set(actual)) or set(actual) != expected:
            raise KnowledgeOperationPlanConflictError(reason="knowledge_delete_projection_scope_changed")
        if any(row["tenant_id"] != plan.tenant_id for row in manifest["projection_targets"]):
            raise KnowledgeOperationPlanConflictError(reason="knowledge_delete_projection_owner_changed")

    async def arequire_completed(self, session, *, job, plan):
        """A repeated ACK observes physical SQL absence without replaying a write."""
        self.validate_job(job, plan)
        if (
            job.state != "SUCCEEDED"
            or job.business_phase != "finalized"
            or job.completed_steps != ["fga", "minio", "es", "milvus"]
        ):
            raise KnowledgeOperationPlanConflictError(reason="knowledge_delete_completion_incomplete")
        context = self.context(session)
        for model, field in (
            (KnowledgeFile, "rows"),
            (KnowledgeDocumentVersion, "version_ids"),
            (KnowledgeDocument, "document_ids"),
        ):
            ids = job.manifest[field]
            for start in range(0, len(ids), 200):
                # Core reads include a reappeared conflicting owner; no foreign
                # values leave this repository and no bypass authority is used.
                table = model.__table__
                with session.no_autoflush:
                    found = (
                        await session.execute(
                            select(table.c.id).where(table.c.id.in_(ids[start : start + 200])).limit(1)
                        )
                    ).first()
                self.current(session, context)
                if found is not None:
                    raise KnowledgeOperationPlanConflictError(reason="knowledge_delete_sql_not_absent")
        if plan.operation == "knowledge_space_delete":
            table = Knowledge.__table__
            with session.no_autoflush:
                found = (await session.execute(select(table.c.id).where(table.c.id == plan.space_id))).first()
            self.current(session, context)
            if found is not None:
                raise KnowledgeOperationPlanConflictError(reason="knowledge_delete_root_not_absent")

    async def afinalize_scope(self, session, *, scope):
        """Caller already locked/revalidated the complete exact physical scope."""
        context = self.context(session)
        if scope.tenant_id != context[0] or scope.issues:
            raise KnowledgeOperationPlanConflictError(reason="knowledge_delete_scope_incomplete")
        docs = sorted({ident for unit in scope.units for ident in unit.deleted_document_ids})
        versions = sorted({ident for unit in scope.units for ident in unit.version_ids})
        rows = sorted({row.id for row in scope.resources})
        for model, column, ids, clear_pointer in (
            (KnowledgeDocument, KnowledgeDocument.id, docs, True),
            (KnowledgeDocumentVersion, KnowledgeDocumentVersion.id, versions, False),
            (KnowledgeDocument, KnowledgeDocument.id, docs, False),
            (KnowledgeFile, KnowledgeFile.id, rows, False),
        ):
            for start in range(0, len(ids), 200):
                query = update(model).values(primary_version_id=None) if clear_pointer else delete(model)
                query = query.where(column.in_(ids[start : start + 200]))
                if model is KnowledgeDocument:
                    query = query.where(KnowledgeDocument.knowledge_id == scope.space_id)
                elif model is KnowledgeFile:
                    query = query.where(
                        KnowledgeFile.knowledge_id == scope.space_id, KnowledgeFile.tenant_id == context[0]
                    )
                result = await session.execute(query.execution_options(synchronize_session=False))
                self.current(session, context)
                if result.rowcount != len(ids[start : start + 200]):
                    raise KnowledgeOperationPlanConflictError(reason="knowledge_delete_cutover_changed")
        await session.flush()
        self.current(session, context)

    async def amark_finalized(self, session, *, job):
        context = self.context(session)
        if job.operation_type not in OPERATIONS or job.business_phase != "prepared" or job.state != "RUNNING":
            raise KnowledgeOperationPlanConflictError(reason="knowledge_delete_phase_changed")
        job.business_phase, job.update_time = "finalized", deletion_now()
        session.add(job)
        await session.flush()
        self.current(session, context)

    async def acleanup_deleted_space(self, session, *, space_id):
        """Preserve the original space deletion's member/private-library cleanup."""
        context = self.context(session)
        await session.execute(
            delete(KnowledgeSpaceTagLibrary).where(
                KnowledgeSpaceTagLibrary.tenant_id == context[0],
                KnowledgeSpaceTagLibrary.owner_knowledge_id == space_id,
            )
        )
        self.current(session, context)
        # This legacy association has no tenant column. Its globally unique
        # business ID is the exact Knowledge root locked by this cutover.
        await session.execute(
            delete(SpaceChannelMember).where(
                SpaceChannelMember.business_type == BusinessTypeEnum.SPACE,
                SpaceChannelMember.business_id == str(space_id),
            )
        )
        self.current(session, context)
        await session.flush()

    @staticmethod
    def cleanup_manifest(scope):
        return {
            "rows": [row.id for row in scope.resources],
            "file_ids": [row.id for row in scope.resources if row.file_type == 1],
            "folder_ids": [row.id for row in scope.resources if row.file_type == 0],
            "version_ids": sorted({ident for unit in scope.units for ident in unit.version_ids}),
            "document_ids": sorted({ident for unit in scope.units for ident in unit.deleted_document_ids}),
            "fga_resources": [
                {"resource_type": "folder" if row.file_type == 0 else "knowledge_file", "resource_id": row.id}
                for row in scope.resources
            ],
            "object_names": list(scope.object_names),
            "knowledge": deepcopy(scope.cleanup_identity),
        }

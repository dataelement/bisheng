"""Actual move application: original authority, short native TXs and durable ACKs."""

from __future__ import annotations

from collections.abc import Mapping
from contextlib import asynccontextmanager
from datetime import timedelta
from weakref import WeakSet

from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from bisheng.common.errcode.knowledge import KnowledgeOperationPlanConflictError
from bisheng.knowledge.application import move_processing_admission as admission
from bisheng.knowledge.application.processing_identity import capture_processing_actor
from bisheng.knowledge.application.reference_target_owner import KnowledgeReferenceTargetOwner
from bisheng.knowledge.domain.repositories.move_cutover_repository import MoveCutoverRepository
from bisheng.knowledge.domain.repositories.move_execution_repository import (
    MoveExecutionRepository,
    MoveExecutionSnapshot,
)
from bisheng.knowledge.domain.repositories.move_job_ready_repository import MoveJobReadyRepository
from bisheng.knowledge.domain.repositories.move_job_repository import MoveJobRepository
from bisheng.knowledge.domain.repositories.move_scope_repository import MoveRoot, MoveScopeRepository
from bisheng.knowledge.domain.repositories.operation_plan_repository import OperationPlanRepository, _now
from bisheng.knowledge.domain.repositories.processing_job_repository import ProcessingJobRepository
from bisheng.knowledge.domain.schemas.knowledge_space_schema import FileMoveReq
from bisheng.knowledge.domain.schemas.processing_job import (
    JobAccepted,
    OperationItem,
    OperationPrecheck,
    ProcessingCreateRequest,
    ProcessingRetryRequest,
)
from bisheng.knowledge.domain.schemas.processing_job_acceptance import ItemLease, JobLease
from bisheng.knowledge.domain.services.knowledge_space_chat_history_retention_service import (
    build_knowledge_chat_flows,
    dispatch_knowledge_chat_rehome,
)
from bisheng.permission.application.identity import get_current_permission_actor
from bisheng.permission.application.knowledge_move_projection import KnowledgeMoveProjectionApplication
from bisheng.resource_reference.application.contracts import TransactionIdentity
from bisheng.resource_reference.application.write_runtime import ReferenceBindingRuntime


class KnowledgeMoveProcessingOwner:
    def __init__(
        self,
        *,
        session_factory,
        projection: KnowledgeMoveProjectionApplication,
        reference_runtime: ReferenceBindingRuntime,
        clock=_now,
        chat_rehome=dispatch_knowledge_chat_rehome,
    ):
        if (
            not callable(session_factory)
            or not isinstance(projection, KnowledgeMoveProjectionApplication)
            or not isinstance(reference_runtime, ReferenceBindingRuntime)
            or not callable(chat_rehome)
        ):
            raise TypeError("move requires actual session, P1 and registered R2 composition")
        self.sessions, self.projection, self.reference_runtime = session_factory, projection, reference_runtime
        self.clock, self.chat_rehome, self._seen = clock, chat_rehome, WeakSet()
        self.plans = OperationPlanRepository(clock=clock)
        self.scope = MoveScopeRepository(parent_states=projection)
        self.cutover = MoveCutoverRepository(
            scope_repository=self.scope, projection_verifier=projection, plans=self.plans, clock=clock
        )
        self.move_jobs = MoveJobRepository(cutover=self.cutover, clock=clock)
        self.ready = MoveJobReadyRepository(move_jobs=self.move_jobs, clock=clock)
        self.execution = MoveExecutionRepository(move_jobs=self.move_jobs, move_ready=self.ready)
        self.jobs = ProcessingJobRepository(
            move_jobs=self.move_jobs, move_ready=self.ready, move_execution=self.execution, clock=clock
        )
        self.reference_owner = KnowledgeReferenceTargetOwner(move_cutover=self.cutover)

    @asynccontextmanager
    async def _session(self):
        tenant = admission.tenant()
        async with self.sessions() as session:
            if (
                not isinstance(session, AsyncSession)
                or session in self._seen
                or session.in_transaction()
                or session.new
                or session.dirty
                or session.deleted
            ):
                raise ValueError("move requires a fresh clean native owned session")
            self._seen.add(session)
            if admission.tenant() != tenant:
                raise ValueError("move factory changed tenant")
            async with session.begin():
                if admission.tenant() != tenant:
                    raise ValueError("move transaction changed tenant")
                transaction = TransactionIdentity.capture(session)
                yield session
                transaction.assert_current(session)
                self._quiescent(session)
                if admission.tenant() != tenant:
                    raise ValueError("move tenant changed")

    @staticmethod
    def _quiescent(session):
        if session.new or session.dirty or session.deleted:
            raise KnowledgeOperationPlanConflictError(reason="move_owner_pending_tail")

    @asynccontextmanager
    async def _savepoint(self, session):
        self._quiescent(session)
        async with session.begin_nested():
            yield
            self._quiescent(session)

    @staticmethod
    async def _call(session, operation):
        tenant, transaction = admission.tenant(), TransactionIdentity.capture(session)
        result = await operation
        transaction.assert_current(session)
        if admission.tenant() != tenant:
            raise ValueError("move tenant changed")
        return result

    async def _job(self, session, job_id):
        job = await self._call(session, self.jobs.aget_execution(session, job_id))
        if job.kind != "move_index":
            raise ValueError("move owner only accepts move_index")
        reference = await self._call(session, self.jobs.alatest_retry_actor(session, job_id))
        session.expunge(job)
        return job, reference

    async def _plan(self, session, source_space_id, confirmation_id, plan_digest):
        return await self._call(
            session,
            self.move_jobs.aread_move_confirmation(
                session, source_space_id=source_space_id, confirmation_id=confirmation_id, plan_digest=plan_digest
            ),
        )

    async def _scope_for(self, session, job):
        p = job.parameters
        plan = await self._plan(session, p["source_space_id"], p["confirmation_id"], p["plan_digest"])
        return self.cutover._restore(plan.parameters)

    async def _materials(self, session, job, changes, *, actor_id):
        expected, facts = [], []
        for offset in range(0, len(changes), 200):
            page = changes[offset : offset + 200]
            candidates = await self._call(
                session,
                self.projection.alist_operator_candidates(
                    session, job_id=job.id, targets=tuple((row.resource_type, str(row.resource_id)) for row in page)
                ),
            )
            ids = sorted({actor_id, *(row.operator_id for row in candidates)})
            members = set()
            for start in range(0, len(ids), 200):
                members.update(
                    await self._call(
                        session,
                        self.move_jobs.aoperator_membership(
                            session, job_id=job.id, operator_ids=tuple(ids[start : start + 200])
                        ),
                    )
                )
            batch = admission.expectations(job, page, actor_id=actor_id, candidates=candidates, members=members)
            facts.extend(await self._call(session, self.projection.alist_owned_operations(session, expectations=batch)))
            expected.extend(batch)
        return tuple(expected), tuple(facts)

    @staticmethod
    def _accepted(result):
        return JobAccepted(job_id=result.job.id, state=result.job.state, reused=result.reused)

    async def _authorize_scope(self, identity, scope, expected, facts, *, force=False):
        required = admission.needs_move(expected, facts)
        move = scope.roots if force else tuple(root for root in scope.roots if admission.resource(root) in required)
        await admission.authorize(
            identity,
            roots=scope.roots,
            destination_space_id=scope.destination_space_id,
            destination_folder_id=scope.destination_folder_id,
            move=move,
        )

    async def aprecheck(
        self, source_space_id: int, request: FileMoveReq, *, identity, entry_kind: str
    ) -> OperationPrecheck:
        if request.skip_invalid or source_space_id == request.target_space_id:
            raise ValueError("this internal owner requires a complete cross-space request")
        roots = tuple(MoveRoot(row.type, row.id) for row in request.items)

        async def load(session, lock):
            return await self._call(
                session,
                self.scope.aload_scope(
                    session,
                    source_space_id=source_space_id,
                    destination_space_id=request.target_space_id,
                    roots=roots,
                    destination_folder_id=request.target_folder_id,
                    for_update=lock,
                ),
            )

        async with self._session() as session:
            scope = await load(session, False)
        captured = await capture_processing_actor(
            identity, space_id=source_space_id, required_action="move", entry_kind=entry_kind
        )
        async with admission.identity(captured.reference, current=identity, entry_kind=entry_kind) as (
            actual,
            reference,
        ):
            await admission.authorize(
                actual,
                roots=scope.roots,
                destination_space_id=scope.destination_space_id,
                destination_folder_id=scope.destination_folder_id,
                move=scope.roots,
            )
            async with self._session() as session:
                current = await load(session, True)
                if current != scope:
                    raise KnowledgeOperationPlanConflictError(reason="move_precheck_changed")
                result = await self._call(
                    session,
                    self.plans.acreate(
                        session,
                        operation="move",
                        space_id=source_space_id,
                        actor_reference=reference,
                        targets=[leaf.target for leaf in scope.leaves],
                        target_revisions={"scope_digest": scope.scope_digest},
                        source_revisions={"source": scope.source, "destination": scope.destination},
                        parameters=scope.to_parameters(),
                        impact={
                            "logical_count": len(scope.files),
                            "index_item_count": sum(leaf.participates for leaf in scope.leaves),
                            "removed_fields": list(scope.removed_fields),
                        },
                        expires_at=self.clock() + timedelta(minutes=5),
                    ),
                )
                return result.model_copy(
                    update={
                        "can_execute": bool(scope.files),
                        "valid_items": [OperationItem(id=root.id, type=root.type) for root in scope.roots],
                    }
                )

    async def aaccept(
        self, source_space_id: int, request: ProcessingCreateRequest, *, identity, entry_kind: str
    ) -> JobAccepted:
        async with self._session() as session:
            plan = await self._plan(session, source_space_id, request.confirmation_id, request.plan_digest)
            args = {
                "source_space_id": source_space_id,
                "confirmation_id": request.confirmation_id,
                "plan_digest": request.plan_digest,
                "idempotency_key": request.idempotency_key,
                "actor_user_id": plan.actor_user_id,
                "actor_reference": plan.actor_reference,
            }
            existing = await self._call(session, self.move_jobs.aget_move_request(session, **args))
            scope = self.cutover._restore(plan.parameters)
            expected, facts = (
                ((), ())
                if existing is None
                else await self._materials(
                    session,
                    existing.job,
                    scope.parent_changes,
                    actor_id=admission.subject(plan.actor_reference).subject_id,
                )
            )
        async with admission.identity(plan.actor_reference, current=identity, entry_kind=entry_kind) as (actual, _):
            await self._authorize_scope(actual, scope, expected, facts, force=existing is None)
            async with self._session() as session:
                return self._accepted(await self._call(session, self.jobs.acreate_move_reserved(session, **args)))

    async def astart_attempt(
        self, job_id: str, *, expected_dispatch_revision: int, lease_seconds: int = 900
    ) -> JobLease | None:
        async with self._session() as session:
            job, reference = await self._job(session, job_id)
            if job.revision != expected_dispatch_revision or job.state not in {"accepted", "running"}:
                return None
        async with admission.identity(reference) as (actual, _):
            async with self._session() as session:
                scope = await self._scope_for(session, job)
                expected, facts = await self._materials(
                    session, job, scope.parent_changes, actor_id=admission.subject(reference).subject_id
                )
            await self._authorize_scope(actual, scope, expected, facts)
            async with self._session() as session:
                return await self._call(
                    session,
                    self.jobs.aclaim(
                        session,
                        job_id,
                        configuration=None,
                        expected_job_revision=expected_dispatch_revision,
                        lease_seconds=lease_seconds,
                        _move=True,
                    ),
                )

    async def aensure_logical(self, lease: JobLease) -> JobAccepted | None:
        async with self._session() as session:
            job, reference = await self._job(session, lease.job_id)
        async with admission.identity(reference) as (actual, _):
            async with self._session() as session:
                attempt = await self._call(
                    session, self.execution.avalidate_attempt(session, lease=lease, jobs=self.jobs)
                )
                if attempt is None:
                    return None
                expected, facts = await self._materials(
                    session, job, attempt.scope.parent_changes, actor_id=admission.subject(reference).subject_id
                )
            await self._authorize_scope(actual, attempt.scope, expected, facts)
            await self.projection.aexecute_or_resume(
                job_id=job.id, changes=expected, actor=get_current_permission_actor()
            )
            async with self._session() as session:
                async with self._savepoint(session):
                    prepared = await self._call(
                        session, self.cutover.aprepare_cutover(session, job_id=job.id, lease=lease)
                    )
                    evidence = await self._call(
                        session, self.projection.arequire_finalized(session, job_id=job.id, expectations=expected)
                    )
                    logical = await self._call(
                        session, self.cutover.aapply_logical(session, prepared=prepared, projection_evidence=evidence)
                    )
                    await self._call(
                        session,
                        self.reference_owner.amove_file_ownership(
                            session, logical=logical, reference_runtime=self.reference_runtime
                        ),
                    )
                    result = await self._call(
                        session, self.jobs.amark_move_ready(session, logical_receipt=logical, lease=lease)
                    )
            try:
                resources = [
                    ("folder" if row.before["file_type"] == 0 else "knowledge_file", row.file_id)
                    for row in prepared.scope.files
                ]
                self.chat_rehome(
                    source_space_id=prepared.scope.source_space_id,
                    source_flow_ids=build_knowledge_chat_flows(prepared.scope.source_space_id, resources),
                    reason="cross_space_move",
                )
            except Exception:
                # Preserve the original post-commit, best-effort F071 rehome semantics.
                logger.exception("knowledge_chat_entry.task_failed stage=move_after_commit job={}", job.id)
            return result

    async def _item_snapshot(self, session, lease, *, claim):
        if claim:
            return await self._call(session, self.execution.apeek_claimable_item(session, lease=lease, jobs=self.jobs))
        job, current = await self._call(session, self.jobs._execution_job(session, lease.job.job_id, _move=True))
        if not self.jobs._active_job_lease(job, lease.job):
            return None
        if not self.jobs._check_configuration(job, None, move_current=current):
            await self._call(session, session.flush())
            return None
        row = await self._call(session, self.jobs._item(session, job, lease.item_id))
        if not self.jobs._active_item_lease(row, lease):
            return None
        return await self._call(session, self.execution.aread_item(session, job_id=job.id, item_id=row.id))

    async def _item(self, lease, *, action, step=None, checkpoint=None, outcome=None, error_code=None):
        claim = action == "claim"
        job_lease = lease if claim else lease.job
        async with self._session() as session:
            job, reference = await self._job(session, job_lease.job_id)
        async with admission.identity(reference) as (actual, _):
            async with self._session() as session:
                snapshot = await self._item_snapshot(session, lease, claim=claim)
                if snapshot is None:
                    return None
            await admission.authorize(
                actual,
                roots=(snapshot.leaf.selected_root,),
                destination_space_id=snapshot.destination["id"],
                destination_folder_id=job.parameters["destination_folder_id"],
            )
            async with self._session() as session:
                async with self._savepoint(session):
                    current = await self._item_snapshot(session, lease, claim=claim)
                    if current is None:
                        return None
                    if (current.item_id, current.leaf) != (snapshot.item_id, snapshot.leaf):
                        raise KnowledgeOperationPlanConflictError(reason="move_item_candidate_changed")
                    expected, _ = await self._materials(
                        session,
                        job,
                        (current.leaf.projection_anchor,),
                        actor_id=admission.subject(reference).subject_id,
                    )
                    evidence = await self._call(
                        session, self.projection.arequire_finalized(session, job_id=job.id, expectations=expected)
                    )
                    if claim:
                        claimed = await self._call(
                            session,
                            self.jobs.aclaim_next_item(
                                session, lease, configuration=None, _move=True, move_projection_evidence=evidence
                            ),
                        )
                        if claimed is not None:
                            if (
                                claimed.item.id != current.item_id
                                or self.execution._leaf(claimed.item).projection_anchor
                                != current.leaf.projection_anchor
                            ):
                                raise KnowledgeOperationPlanConflictError(reason="move_claim_anchor_changed")
                            return claimed.lease
                        return None
                    if action == "guard":
                        return await self._call(
                            session,
                            self.execution.aguard_item(session, lease, jobs=self.jobs, projection_evidence=evidence),
                        )
                    if action == "checkpoint":
                        return await self._call(
                            session,
                            self.jobs.asave_checkpoint(
                                session,
                                lease,
                                configuration=None,
                                step=step,
                                checkpoint=checkpoint,
                                _move=True,
                                move_projection_evidence=evidence,
                            ),
                        )
                    if action == "renew":
                        return await self._call(
                            session,
                            self.jobs.arenew_item(
                                session, lease, configuration=None, _move=True, move_projection_evidence=evidence
                            ),
                        )
                    if action == "complete":
                        return await self._call(
                            session,
                            self.execution.acomplete_item(
                                session, lease, jobs=self.jobs, projection_evidence=evidence, **outcome
                            ),
                        )
                    return await self._call(
                        session,
                        self.jobs.acomplete_item(
                            session,
                            lease,
                            configuration=None,
                            succeeded=False,
                            result={},
                            error_code=error_code,
                            _move=True,
                            move_projection_evidence=evidence,
                        ),
                    )

    async def aclaim_item(self, lease: JobLease) -> ItemLease | None:
        return await self._item(lease, action="claim")

    async def aguard_item(self, lease: ItemLease) -> MoveExecutionSnapshot | None:
        return await self._item(lease, action="guard")

    async def asave_item_checkpoint(self, lease: ItemLease, *, step: str, checkpoint: Mapping) -> bool:
        return bool(await self._item(lease, action="checkpoint", step=step, checkpoint=checkpoint))

    async def acomplete_item(
        self, lease, *, source_count, milvus_count, es_count, source_digest, target_payload_digest
    ):
        outcome = {
            "source_count": source_count,
            "milvus_count": milvus_count,
            "es_count": es_count,
            "source_digest": source_digest,
            "target_payload_digest": target_payload_digest,
        }
        return bool(await self._item(lease, action="complete", outcome=outcome))

    async def afail_item(self, lease: ItemLease, *, error_code: int) -> bool:
        return bool(await self._item(lease, action="fail", error_code=error_code))

    async def arenew_item(self, lease: ItemLease) -> bool:
        return bool(await self._item(lease, action="renew"))

    async def _attempt_end(self, lease, *, finalize):
        async with self._session() as session:
            job, reference = await self._job(session, lease.job_id)
        async with admission.identity(reference) as (actual, _):
            async with self._session() as session:
                locked, configuration = await self._call(
                    session, self.jobs._execution_job(session, lease.job_id, _move=True)
                )
                if not self.jobs._active_job_lease(locked, lease):
                    return None
                if not self.jobs._check_configuration(locked, None, move_current=configuration):
                    await self._call(session, session.flush())
                    return None
                bounded = not finalize and locked.move_logical_marker is not None
                if bounded:
                    self.ready.require_job_ready(locked)
                else:
                    scope = await self._scope_for(session, job)
                    expected, facts = await self._materials(
                        session, job, scope.parent_changes, actor_id=admission.subject(reference).subject_id
                    )
            if bounded:
                await admission.authorize(
                    actual,
                    roots=(),
                    destination_space_id=job.space_id,
                    destination_folder_id=job.parameters["destination_folder_id"],
                )
            else:
                await self._authorize_scope(actual, scope, expected, facts)
            async with self._session() as session:
                if finalize:
                    result = await self._call(
                        session, self.jobs.afinalize(session, lease, configuration=None, _move=True)
                    )
                    return None if result is None else JobAccepted(job_id=result.id, state=result.state, reused=False)
                return await self._call(session, self.jobs.arenew(session, lease, configuration=None, _move=True))

    async def arenew_attempt(self, lease: JobLease) -> bool:
        return bool(await self._attempt_end(lease, finalize=False))

    async def afinalize_attempt(self, lease: JobLease) -> JobAccepted | None:
        return await self._attempt_end(lease, finalize=True)

    async def afail_attempt(
        self, job_id: str, *, expected_job_revision: int, error_code: int, lease: JobLease | None = None
    ) -> bool:
        if type(error_code) is not int or not 10000 <= error_code <= 99999:
            raise ValueError("move failure requires a five-digit public integer code")
        async with self._session() as session:
            await self._job(session, job_id)
            return (
                await self._call(
                    session,
                    self.jobs.afail_attempt(
                        session, job_id, expected_job_revision=expected_job_revision, error_code=error_code, lease=lease
                    ),
                )
            ) is not None

    async def aretry_failed(
        self, job_id: str, request: ProcessingRetryRequest, *, identity, entry_kind: str
    ) -> JobAccepted:
        async with self._session() as session:
            job, reference = await self._job(session, job_id)
            scope = await self._scope_for(session, job)
            expected, facts = await self._materials(
                session, job, scope.parent_changes, actor_id=admission.subject(reference).subject_id
            )
        async with admission.identity(reference, current=identity, entry_kind=entry_kind, allow_other=True) as (
            actual,
            active,
        ):
            await self._authorize_scope(
                actual, scope, expected, facts, force=admission.subject(active) != admission.subject(reference)
            )
            async with self._session() as session:
                return self._accepted(
                    await self._call(
                        session,
                        self.jobs.aretry_failed(
                            session,
                            job_id,
                            idempotency_key=request.idempotency_key,
                            expected_job_revision=request.expected_job_revision,
                            actor_user_id=active["actor_user_id"],
                            actor_reference=active,
                            configuration=None,
                            _move=True,
                        ),
                    )
                )

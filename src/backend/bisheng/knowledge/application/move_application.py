"""Actual legacy move entry: classified confirmation and synchronous same-space P1."""

from datetime import timedelta
from types import SimpleNamespace
from uuid import UUID, uuid5

from bisheng.common.errcode.knowledge import (
    KnowledgeOperationConfirmationRequiredError,
    KnowledgeOperationPlanChangedError,
)
from bisheng.common.errcode.permission import PermissionDeniedError
from bisheng.knowledge.application import move_processing_admission as admission
from bisheng.knowledge.application.move_processing_access import get_move_owner
from bisheng.knowledge.application.processing_identity import capture_processing_actor
from bisheng.knowledge.domain.repositories.move_batch_repository import MoveBatchRepository, conflict
from bisheng.knowledge.domain.repositories.operation_plan_repository import _digest
from bisheng.knowledge.domain.schemas.move_processing import MoveParentChange, MoveRoot
from bisheng.knowledge.domain.schemas.processing_job import OperationInvalidItem, OperationItem
from bisheng.permission.application.business_authorization import batch_check_business_actions


async def get_move_application():
    from bisheng.knowledge.domain.services.knowledge_space_service import MAX_FOLDER_LEVEL

    return KnowledgeMoveApplication(owner=await get_move_owner(), max_folder_level=MAX_FOLDER_LEVEL)


class KnowledgeMoveApplication:
    def __init__(self, *, owner, max_folder_level):
        self.owner = owner
        self.repository = MoveBatchRepository(max_folder_level=max_folder_level, clock=owner.clock)

    async def _read(self, session, source, request, *, lock=False):
        return await self.owner._call(
            session,
            self.repository.aread(
                session,
                source_space_id=source,
                destination_space_id=request.target_space_id,
                roots=tuple(MoveRoot(row.type, row.id) for row in request.items),
                destination_folder_id=request.target_folder_id,
                lock=lock,
            ),
        )

    async def _classify(self, batch, identity):
        denied, visible = set(), set()
        files = {row["id"]: row for row in batch.files}
        groups = {}
        for root in batch.roots:
            if root.id in files:
                groups.setdefault(admission.resource(root)[0], []).append(root)
        for kind, roots in groups.items():
            for offset in range(0, len(roots), 200):
                page = roots[offset : offset + 200]
                tenant, actor = admission.tenant(), admission.get_current_permission_actor()
                actions = await batch_check_business_actions(
                    identity,
                    resource_type=kind,
                    resource_ids=tuple(root.id for root in page),
                    actions=("move", "visible"),
                )
                if admission.tenant() != tenant or admission.get_current_permission_actor() is not actor:
                    raise PermissionDeniedError(reason="move_classification_context_changed")
                for root in page:
                    codes = actions.get(str(root.id), ())
                    if "move" not in codes:
                        denied.add(root)
                    if "visible" in codes:
                        visible.add(root)
        roots, reasons = self.repository.classify(batch, denied)
        invalid = [
            OperationInvalidItem(
                id=root.id,
                type=root.type,
                name=files[root.id]["file_name"] if root in visible and root.id in files else None,
                reason=reasons[root],
            )
            for root in batch.roots
            if root in reasons
        ]
        await admission.authorize(
            identity,
            roots=roots,
            destination_space_id=batch.destination["id"],
            destination_folder_id=batch.destination_folder_id,
        )
        return roots, invalid

    async def aprecheck(self, source, request, *, identity, entry_kind="web"):
        if not request.items or any(
            type(row.id) is not int or row.id <= 0 or row.type not in {"file", "folder"} for row in request.items
        ):
            conflict("selection_required")
        async with self.owner._session() as session:
            batch = await self._read(session, source, request)
        captured = await capture_processing_actor(
            identity, space_id=source, required_action="move", entry_kind=entry_kind
        )
        async with admission.identity(captured.reference, current=identity, entry_kind=entry_kind) as (
            actual,
            reference,
        ):
            roots, invalid = await self._classify(batch, actual)
            same = source == request.target_space_id
            impact = {
                "cross_space": not same,
                "requested_roots": [row.model_dump() for row in request.items],
                "invalid_items": [row.model_dump(mode="json") for row in invalid],
                "valid_roots": [{"id": root.id, "type": root.type} for root in roots],
                "classification_digest": _digest(
                    {
                        "source": batch.source,
                        "destination": batch.destination,
                        "files": batch.files,
                        "documents": batch.documents,
                        "versions": batch.versions,
                    }
                ),
                "requires_skip_confirmation": bool(invalid),
                "can_execute": bool(roots),
                "target_space_id": request.target_space_id,
                "target_folder_id": request.target_folder_id,
            }
            async with self.owner._session() as session:
                if not roots:
                    parameters, targets = {}, []
                elif same:
                    current = await self._read(session, source, request, lock=True)
                    if current != batch:
                        raise KnowledgeOperationPlanChangedError()
                    parameters = await self.repository.same_parameters(session, batch, roots, self.owner.projection)
                    targets = []
                else:
                    scope = await self.owner._call(
                        session,
                        self.owner.scope.aload_scope(
                            session,
                            source_space_id=source,
                            destination_space_id=request.target_space_id,
                            roots=roots,
                            destination_folder_id=request.target_folder_id,
                            for_update=True,
                        ),
                    )
                    # Actual effective closure is built once, after classification.
                    before = {row["id"]: row for row in batch.files}
                    if (
                        any(before.get(row.file_id) != row.before for row in scope.files)
                        or scope.source != batch.source
                        or scope.destination != batch.destination
                    ):
                        raise KnowledgeOperationPlanChangedError()
                    parameters, targets = scope.to_parameters(), [leaf.target for leaf in scope.leaves]
                    impact.update(
                        logical_count=len(scope.files),
                        index_item_count=sum(leaf.participates for leaf in scope.leaves),
                        removed_fields=list(scope.removed_fields),
                        retained_fields=list(scope.retained_fields),
                    )
                target_revisions = {"scope_digest": scope.scope_digest} if roots and not same else {}
                result = await self.owner._call(
                    session,
                    self.owner.plans.acreate(
                        session,
                        operation="move_same_space" if same else "move",
                        space_id=source,
                        actor_reference=reference,
                        targets=targets,
                        target_revisions=target_revisions,
                        source_revisions={"source": batch.source, "destination": batch.destination},
                        parameters=parameters,
                        impact=impact,
                        expires_at=self.owner.clock() + timedelta(minutes=5),
                    ),
                )
                return result.model_copy(
                    update={
                        "can_execute": bool(roots),
                        "valid_items": [OperationItem(id=root.id, type=root.type) for root in roots],
                        "invalid_items": invalid,
                        "requires_skip_confirmation": bool(invalid),
                    }
                )

    async def _plan(self, session, source, request):
        # This public confirmation reader validates the complete original Plan hash.
        return await self.owner.move_jobs.aread_move_confirmation(
            session, source_space_id=source, confirmation_id=request.confirmation_id, plan_digest=request.plan_digest
        )

    async def aconfirm(self, source, request, *, identity, entry_kind="web"):
        async with self.owner._session() as session:
            plan = await self._plan(session, source, request)
            if not plan.impact.get("can_execute", True):
                conflict("no_valid_items")
            same = plan.parameters.get("same_space_move") == 1
            if (plan.operation == "move_same_space") != same:
                raise KnowledgeOperationPlanChangedError()
            self.owner.plans._validate(plan)
        if not same:
            if plan.operation_id is None:
                await self._recheck_classification(plan, identity, entry_kind)
            return await self.owner.aaccept(source, request, identity=identity, entry_kind=entry_kind)
        return await self._same(plan, request, identity, entry_kind)

    async def _recheck_classification(self, plan, identity, entry_kind):
        from bisheng.knowledge.domain.schemas.knowledge_space_schema import FileMoveReq

        impact = plan.impact
        if "requested_roots" not in impact:
            return
        request = FileMoveReq(
            items=impact["requested_roots"],
            target_space_id=impact["target_space_id"],
            target_folder_id=impact["target_folder_id"],
        )
        async with self.owner._session() as session:
            batch = await self._read(session, plan.space_id, request)
        async with admission.identity(plan.actor_reference, current=identity, entry_kind=entry_kind) as (actual, _):
            roots, invalid = await self._classify(batch, actual)
        digest = _digest(
            {
                "source": batch.source,
                "destination": batch.destination,
                "files": batch.files,
                "documents": batch.documents,
                "versions": batch.versions,
            }
        )
        if (
            digest != impact["classification_digest"]
            or [row.model_dump(mode="json") for row in invalid] != impact["invalid_items"]
            or [{"id": root.id, "type": root.type} for root in roots] != impact["valid_roots"]
        ):
            raise KnowledgeOperationPlanChangedError()

    async def _same_materials(self, session, plan, operation_id, actor_id):
        p = plan.parameters
        changes = tuple(MoveParentChange(**row) for row in p["parent_changes"])
        digest = _digest(p["parent_changes"])
        # Original P1 native expectations are business-operation keyed. No Job exists.
        header = SimpleNamespace(
            id=operation_id, tenant_id=plan.tenant_id, parameters={"scope_digest": _digest(p), "changes_digest": digest}
        )
        candidates = []
        for offset in range(0, len(changes), 200):
            page = changes[offset : offset + 200]
            candidates.extend(
                await self.owner.projection.alist_operator_candidates(
                    session,
                    job_id=operation_id,
                    targets=tuple((row.resource_type, str(row.resource_id)) for row in page),
                )
            )
        if any(row.operator_id != actor_id for row in candidates):
            conflict("same_operator_changed")
        expected = admission.expectations(
            header, changes, actor_id=actor_id, candidates=candidates, members=frozenset({actor_id})
        )
        facts = await self.owner.projection.alist_owned_operations(session, expectations=expected)
        return changes, expected, facts

    async def _same(self, plan, request, identity, entry_kind):
        p = plan.parameters
        roots = tuple(MoveRoot(row["type"], row["id"]) for row in p["roots"])
        operation_id = str(uuid5(UUID(plan.id), request.idempotency_key))
        if plan.operation_id not in (None, operation_id):
            raise KnowledgeOperationPlanChangedError()
        if plan.operation_id is None:
            await self._recheck_classification(plan, identity, entry_kind)
        async with admission.identity(plan.actor_reference, current=identity, entry_kind=entry_kind) as (actual, _):
            actor = admission.get_current_permission_actor()
            async with self.owner._session() as session:
                phase = await self.repository.same_phase(session, p)
                changes, expected, facts = await self._same_materials(session, plan, operation_id, actor.subject_id)
            required = admission.needs_move(expected, facts)
            await admission.authorize(
                actual,
                roots=roots,
                destination_space_id=plan.space_id,
                destination_folder_id=p["destination_folder_id"],
                move=tuple(root for root in roots if admission.resource(root) in required),
            )
            async with self.owner._session() as session:
                await self.repository.same_phase(session, p, lock=True)
                await self.owner.plans.aconsume(
                    session, plan.id, operation_id=operation_id, expected_digest=plan.plan_digest
                )
            await self.owner.projection.aexecute_or_resume(job_id=operation_id, changes=expected, actor=actor)
            async with admission.identity(plan.actor_reference, current=identity, entry_kind=entry_kind) as (fresh, _):
                await admission.authorize(
                    fresh,
                    roots=roots,
                    destination_space_id=plan.space_id,
                    destination_folder_id=p["destination_folder_id"],
                )
                async with self.owner._session() as session:
                    async with self.owner._savepoint(session):
                        phase = await self.repository.same_phase(session, p, lock=True)
                        current = await self._plan(session, plan.space_id, request)
                        if current.operation_id != operation_id:
                            raise KnowledgeOperationPlanChangedError()
                        evidence = await self.owner.projection.arequire_finalized(
                            session, job_id=operation_id, expectations=expected
                        )
                        self.owner.projection.assert_current(
                            evidence,
                            session,
                            job_id=operation_id,
                            expected_changes=changes,
                            changes_digest=_digest(p["parent_changes"]),
                        )
                        if phase == "before":
                            await self.repository.afinalize_same(session, p)
            before = {row["before"]["id"]: row["before"] for row in p["files"]}
            return {
                "moved": [
                    {
                        "id": root.id,
                        "type": root.type,
                        "old_parent_id": (
                            tuple(
                                int(value) for value in (before[root.id]["file_level_path"] or "").split("/") if value
                            )
                            or (None,)
                        )[-1],
                        "cross_space": False,
                    }
                    for root in roots
                ],
                "invalid": plan.impact.get("invalid_items", []),
            }

    async def move_legacy(self, source, request, *, identity, entry_kind="web"):
        if source != request.target_space_id:
            raise KnowledgeOperationConfirmationRequiredError()
        # Bare skip=True is never evidence of an earlier immutable review.
        review = await self.aprecheck(source, request, identity=identity, entry_kind=entry_kind)
        if review.invalid_items:
            return {
                "moved": [],
                "invalid": [row.model_dump(mode="json") for row in review.invalid_items],
                "confirmation_id": review.confirmation_id,
                "plan_digest": review.plan_digest,
            }
        from bisheng.knowledge.domain.schemas.processing_job import ProcessingCreateRequest

        return await self.aconfirm(
            source,
            ProcessingCreateRequest(
                confirmation_id=review.confirmation_id,
                plan_digest=review.plan_digest,
                idempotency_key=review.confirmation_id,
            ),
            identity=identity,
            entry_kind=entry_kind,
        )

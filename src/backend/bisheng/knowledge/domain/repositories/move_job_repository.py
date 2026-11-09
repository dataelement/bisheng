"""Native reserved move acceptance and bounded historical subject facts.

The caller owns the session and commit. These internal capabilities neither
perform the logical move nor authorize execution or publish a worker message.
"""

import re
from collections.abc import Mapping
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.errcode.knowledge import KnowledgeIdempotencyConflictError, KnowledgeOperationPlanConflictError
from bisheng.core.context.tenant import get_current_tenant_id, is_tenant_filter_bypassed, strict_tenant_filter
from bisheng.knowledge.domain.models.knowledge import Knowledge
from bisheng.knowledge.domain.models.knowledge_operation_plan import KnowledgeOperationPlan
from bisheng.knowledge.domain.models.knowledge_processing_item import KnowledgeProcessingItem
from bisheng.knowledge.domain.models.knowledge_processing_job import KnowledgeProcessingJob
from bisheng.knowledge.domain.models.knowledge_processing_retry import KnowledgeProcessingRetryReceipt
from bisheng.knowledge.domain.repositories.move_cutover_repository import MoveCutoverRepository
from bisheng.knowledge.domain.schemas.processing_actor_subject import processing_actor_subject
from bisheng.knowledge.domain.schemas.processing_job import ResourceVersionTarget
from bisheng.knowledge.domain.schemas.processing_job_acceptance import (
    JobRequestResult,
    NewProcessingItem,
    ProcessingConfiguration,
    _digest,
    processing_manifest,
    processing_request_facts,
)
from bisheng.knowledge.domain.services.move_metadata_policy import effective_move_removed_fields

_PARAMETER_KEYS = frozenset(
    (
        "move_schema operation_id confirmation_id plan_digest plan_request_hash source_space_id destination_space_id "
        "destination_folder_id scope_digest changes_digest logical_file_count logical_document_count logical_version_count "
        "index_item_count configuration"
    ).split()
)


def _now():
    return datetime.now(UTC).replace(tzinfo=None)


def _conflict(reason):
    raise KnowledgeOperationPlanConflictError(reason=reason)


class MoveJobRepository:
    def __init__(self, *, cutover: MoveCutoverRepository, clock=_now):
        if not isinstance(cutover, MoveCutoverRepository):
            raise TypeError("move acceptance requires its actual cutover issuer")
        self.cutover, self.clock = cutover, clock

    @staticmethod
    def _context(session):
        tenant = get_current_tenant_id()
        if (
            not isinstance(session, AsyncSession)
            or type(tenant) is not int
            or tenant <= 0
            or is_tenant_filter_bypassed()
        ):
            raise ValueError("move acceptance requires a native session and concrete tenant")
        return tenant

    def _arguments(
        self, session, source_space_id, confirmation_id, plan_digest, idempotency_key, actor_user_id, actor_reference
    ):
        tenant = self._context(session)
        if (
            type(source_space_id) is not int
            or source_space_id <= 0
            or not isinstance(confirmation_id, str)
            or not 0 < len(confirmation_id) <= 36
            or not isinstance(plan_digest, str)
            or re.fullmatch("[0-9a-f]{64}", plan_digest) is None
            or not isinstance(idempotency_key, str)
            or not 0 < len(idempotency_key) <= 64
            or not isinstance(actor_reference, Mapping)
        ):
            raise ValueError("move acceptance requires an exact confirmation and request key")
        processing_actor_subject(
            actor_reference, tenant_id=tenant, actor_user_id=actor_user_id, source_space_id=source_space_id
        )
        _digest(actor_reference)
        return tenant

    async def _rows(self, session, statement):
        with session.no_autoflush, strict_tenant_filter():
            return (await session.execute(statement)).mappings().all()

    async def _plan(self, session, confirmation_id, *, lock=False):
        table = KnowledgeOperationPlan.__table__
        statement = select(table).where(table.c.id == confirmation_id)
        rows = await self._rows(session, statement.with_for_update() if lock else statement)
        if len(rows) != 1 or rows[0]["tenant_id"] != self._context(session):
            _conflict("move_acceptance_plan_missing")
        plan = KnowledgeOperationPlan(**rows[0])
        self.cutover.plans._validate(plan, check_expiry=False)
        return plan

    async def _existing(self, session, key, *, lock=False):
        table = KnowledgeProcessingJob.__table__
        statement = select(table).where(table.c.kind == "move_index", table.c.idempotency_key == key)
        rows = await self._rows(session, statement.with_for_update() if lock else statement)
        if not rows:
            return None
        if len(rows) != 1 or rows[0]["tenant_id"] != self._context(session):
            _conflict("move_acceptance_job_scope")
        return KnowledgeProcessingJob(**rows[0])

    def _origin(self, plan, source_space_id, plan_digest, actor_user_id, actor_reference):
        if (
            plan.operation != "move"
            or plan.space_id != source_space_id
            or plan.plan_digest != plan_digest
            or plan.actor_user_id != actor_user_id
            or plan.actor_reference != actor_reference
        ):
            raise KnowledgeIdempotencyConflictError()
        return processing_actor_subject(
            plan.actor_reference,
            tenant_id=plan.tenant_id,
            actor_user_id=plan.actor_user_id,
            source_space_id=source_space_id,
        )

    @staticmethod
    def _projection(plan, job_id):
        p = plan.parameters
        files = {row["file_id"]: row for row in p["files"]}
        documents = {row["file_id"]: row for row in p["documents"]}
        versions = {row["id"]: row for row in p["versions"]}
        if p["move_schema"] != 1 or not files or p["source_space_id"] != plan.space_id:
            _conflict("move_acceptance_scope")
        configuration = {}
        for side in ("source", "destination"):
            root = p[side]
            configuration.update(
                {
                    side + "_space_id": p[side + "_space_id"],
                    side + "_model_config_revision": root["model_config_revision"],
                    side + "_index_generation": root["index_generation"],
                    side + "_index_digest": _digest([root["index_name"], root["collection_name"]]),
                }
            )
        parameters = {
            "move_schema": 1,
            "operation_id": job_id,
            "confirmation_id": plan.id,
            "plan_digest": plan.plan_digest,
            "plan_request_hash": plan.request_hash,
            "source_space_id": p["source_space_id"],
            "destination_space_id": p["destination_space_id"],
            "destination_folder_id": p["destination_folder_id"],
            "scope_digest": _digest(p),
            "changes_digest": _digest(p["parent_changes"]),
            "logical_file_count": len(files),
            "logical_document_count": len(documents),
            "logical_version_count": len(versions),
            "index_item_count": sum(leaf["participates"] for leaf in p["leaves"]),
            "configuration": configuration,
        }
        items = []
        for leaf in p["leaves"]:
            if not leaf["participates"]:
                continue
            target = ResourceVersionTarget.model_validate(leaf["target"])
            file = files[target.file_id]
            snapshot = {
                "move_schema": 1,
                "leaf": leaf,
                "file_before": file["before"],
                "file_after": file["after"],
                "document_after": documents[target.document_id]["after"],
                "version": versions[target.version_id],
                "metadata_policy": {
                    "retained_fields": p["retained_fields"],
                    "removed_fields": list(
                        effective_move_removed_fields(
                            file_source=file["before"]["file_source"], removed_fields=tuple(p["removed_fields"])
                        )
                    ),
                },
            }
            items.append(NewProcessingItem(target, p["destination_space_id"], leaf["destination_parent_id"], snapshot))
        manifest = processing_manifest(p["destination_space_id"], items)
        config = ProcessingConfiguration(
            p["destination"]["model_config_revision"], p["destination"]["index_generation"]
        )
        request_hash = _digest(
            processing_request_facts(
                tenant_id=plan.tenant_id,
                space_id=p["destination_space_id"],
                kind="move_index",
                actor_user_id=plan.actor_user_id,
                actor_reference=plan.actor_reference,
                parameters=parameters,
                manifest=manifest,
                configuration=config,
                space_config_version=0,
            )
        )
        compact = [
            {
                **{
                    key: row[key]
                    for key in ("file_id", "document_id", "version_id", "expected_space_id", "expected_parent_id")
                },
                "processing_snapshot_digest": _digest(row["processing_snapshot"]),
            }
            for row in manifest
        ]
        return parameters, manifest, config, request_hash, compact

    def _replay(self, plan, existing):
        if existing is None:
            if plan.operation_id is not None:
                raise KnowledgeIdempotencyConflictError()
            return None
        try:
            parameters, _, config, request_hash, compact = self._projection(plan, existing.id)
            subject = processing_actor_subject(
                existing.actor_reference,
                tenant_id=existing.tenant_id,
                actor_user_id=existing.actor_user_id,
                source_space_id=plan.space_id,
            )
            valid = (
                plan.operation_id == existing.id
                and existing.space_id == parameters["destination_space_id"]
                and existing.actor_user_id == plan.actor_user_id
                and existing.actor_reference == plan.actor_reference
                and (existing.actor_subject_type, existing.actor_subject_id)
                == (subject.subject_type, subject.subject_id)
                and existing.parameters == parameters
                and existing.scope_manifest == compact
                and existing.accepted_model_config_revision == config.model_config_revision
                and existing.space_config_version == 0
                and existing.total_count == len(compact)
                and existing.request_hash == request_hash
            )
        except (ValueError, TypeError, KeyError) as error:
            raise KnowledgeIdempotencyConflictError() from error
        if not valid:
            raise KnowledgeIdempotencyConflictError()
        return JobRequestResult(existing, True)

    async def aread_move_confirmation(self, session, *, source_space_id, confirmation_id, plan_digest):
        plan = await self._plan(session, confirmation_id)
        if (
            type(source_space_id) is not int
            or source_space_id <= 0
            or plan.operation not in {"move", "move_same_space"}
            or plan.space_id != source_space_id
            or plan.plan_digest != plan_digest
        ):
            _conflict("move_confirmation_changed")
        return plan

    async def aget_move_request(
        self, session, *, source_space_id, confirmation_id, plan_digest, idempotency_key, actor_user_id, actor_reference
    ) -> JobRequestResult | None:
        tenant = self._arguments(
            session, source_space_id, confirmation_id, plan_digest, idempotency_key, actor_user_id, actor_reference
        )
        plan = await self._plan(session, confirmation_id)
        self._origin(plan, source_space_id, plan_digest, actor_user_id, actor_reference)
        result = self._replay(plan, await self._existing(session, idempotency_key))
        if self._context(session) != tenant:
            _conflict("move_acceptance_context_changed")
        return result

    async def acreate_move_reserved(
        self, session, *, source_space_id, confirmation_id, plan_digest, idempotency_key, actor_user_id, actor_reference
    ) -> JobRequestResult:
        tenant = self._arguments(
            session, source_space_id, confirmation_id, plan_digest, idempotency_key, actor_user_id, actor_reference
        )
        self.cutover._clean(session)
        if not session.in_transaction():
            raise ValueError("move acceptance requires the caller transaction")
        async with session.begin_nested():
            initial = await self._plan(session, confirmation_id)
            self._origin(initial, source_space_id, plan_digest, actor_user_id, actor_reference)
            destination = initial.parameters["destination_space_id"]
            root = Knowledge.__table__
            roots = await self._rows(
                session,
                select(root.c.id, root.c.tenant_id, root.c.type)
                .where(root.c.id.in_(sorted((source_space_id, destination))))
                .order_by(root.c.id)
                .with_for_update(),
            )
            if len(roots) != 2 or any(row["tenant_id"] != tenant or row["type"] != 3 for row in roots):
                _conflict("move_acceptance_roots")
            plan = await self._plan(session, confirmation_id, lock=True)
            subject = self._origin(plan, source_space_id, plan_digest, actor_user_id, actor_reference)
            if plan.parameters["destination_space_id"] != destination:
                _conflict("move_acceptance_plan_changed")
            replay = self._replay(plan, await self._existing(session, idempotency_key, lock=True))
            if replay is not None:
                return replay
            scope = self.cutover._restore(plan.parameters)
            receipt = await self.cutover.aprepare_reservation(
                session,
                scope=scope,
                confirmation_id=confirmation_id,
                plan_digest=plan_digest,
                actor_user_id=actor_user_id,
                actor_reference=actor_reference,
            )
            self.cutover.assert_reservation_current(receipt, session)
            if (
                receipt.plan_id != plan.id
                or receipt.plan_request_hash != plan.request_hash
                or receipt.actor_reference != plan.actor_reference
                or receipt.source_space_id != source_space_id
                or receipt.destination_space_id != destination
            ):
                _conflict("move_acceptance_reservation")
            parameters, manifest, config, request_hash, compact = self._projection(plan, receipt.job_id)
            now = self.clock()
            now = now.astimezone(UTC).replace(tzinfo=None) if now.tzinfo else now
            job = KnowledgeProcessingJob(
                id=receipt.job_id,
                tenant_id=tenant,
                space_id=destination,
                kind="move_index",
                actor_user_id=actor_user_id,
                actor_reference=plan.actor_reference,
                actor_subject_type=subject.subject_type,
                actor_subject_id=subject.subject_id,
                idempotency_key=idempotency_key,
                request_hash=request_hash,
                parameters=parameters,
                scope_manifest=compact,
                expected_model_config_revision=config.model_config_revision,
                accepted_model_config_revision=config.model_config_revision,
                expected_index_generation=config.index_generation,
                space_config_version=0,
                total_count=len(manifest),
                pending_count=len(manifest),
                accepted_at=now,
                next_dispatch_at=now,
                create_time=now,
                update_time=now,
                state="accepted",
                pending_dispatch=True,
                started_at=None,
                finished_at=None,
            )
            session.add(job)
            session.add_all(KnowledgeProcessingItem(tenant_id=tenant, job_id=job.id, **row) for row in manifest)
            await session.flush()
            await self.cutover.aconsume_reservation(session, receipt)
            if self._context(session) != tenant:
                _conflict("move_acceptance_context_changed")
            return JobRequestResult(job, False)

    async def aoperator_membership(self, session, *, job_id, operator_ids: tuple[int, ...]) -> frozenset[int]:
        tenant = self._context(session)
        if (
            type(operator_ids) is not tuple
            or len(operator_ids) > 200
            or any(type(value) is not int or value <= 0 for value in operator_ids)
        ):
            raise ValueError("move membership requires at most 200 positive native operator IDs")
        if not isinstance(job_id, str) or not 0 < len(job_id) <= 36:
            raise ValueError("move membership requires a durable job identifier")
        if not operator_ids:
            return frozenset()
        job, plan, retry = (
            model.__table__
            for model in (KnowledgeProcessingJob, KnowledgeOperationPlan, KnowledgeProcessingRetryReceipt)
        )
        fields = (
            "id",
            "tenant_id",
            "space_id",
            "kind",
            "actor_user_id",
            "actor_reference",
            "actor_subject_type",
            "actor_subject_id",
            "revision",
            "parameters",
        )
        rows = await self._rows(session, select(*(job.c[name] for name in fields)).where(job.c.id == job_id))
        if len(rows) != 1 or rows[0]["tenant_id"] != tenant or rows[0]["kind"] != "move_index":
            _conflict("move_membership_job")
        row = rows[0]
        p = row["parameters"]
        if set(p) != _PARAMETER_KEYS or p["operation_id"] != job_id or p["destination_space_id"] != row["space_id"]:
            _conflict("move_membership_parameters")
        headers = await self._rows(
            session,
            select(
                plan.c.id,
                plan.c.tenant_id,
                plan.c.operation,
                plan.c.space_id,
                plan.c.actor_user_id,
                plan.c.actor_reference,
                plan.c.plan_digest,
                plan.c.request_hash,
                plan.c.operation_id,
                plan.c.consumed_at,
            ).where(plan.c.id == p["confirmation_id"]),
        )
        if (
            len(headers) != 1
            or headers[0]["tenant_id"] != tenant
            or headers[0]["operation"] != "move"
            or headers[0]["space_id"] != p["source_space_id"]
            or headers[0]["operation_id"] != job_id
            or headers[0]["consumed_at"] is None
            or headers[0]["plan_digest"] != p["plan_digest"]
            or headers[0]["request_hash"] != p["plan_request_hash"]
            or headers[0]["actor_user_id"] != row["actor_user_id"]
            or headers[0]["actor_reference"] != row["actor_reference"]
        ):
            _conflict("move_membership_plan")
        found = set()

        def validate(value):
            try:
                subject = processing_actor_subject(
                    value["actor_reference"],
                    tenant_id=tenant,
                    actor_user_id=value["actor_user_id"],
                    source_space_id=p["source_space_id"],
                )
            except (ValueError, TypeError, KeyError) as error:
                raise KnowledgeOperationPlanConflictError(reason="move_membership_origin") from error
            if (value["actor_subject_type"], value["actor_subject_id"]) != (subject.subject_type, subject.subject_id):
                _conflict("move_membership_subject")
            if subject.subject_id in operator_ids:
                found.add(subject.subject_id)

        validate(row)
        candidates = sorted(set(operator_ids))
        for start in range(0, len(candidates), 100):
            representatives = await self._rows(
                session,
                select(func.min(retry.c.id).label("id"))
                .where(
                    retry.c.job_id == job_id,
                    retry.c.actor_subject_id.in_(candidates[start : start + 100]),
                    retry.c.actor_subject_type.in_(("user", "service_account")),
                    retry.c.expected_job_revision >= 0,
                    retry.c.accepted_job_revision > retry.c.expected_job_revision,
                    retry.c.accepted_job_revision <= row["revision"],
                )
                .group_by(retry.c.actor_subject_type, retry.c.actor_subject_id),
            )
            ids = [value["id"] for value in representatives]
            if ids:
                values = await self._rows(
                    session,
                    select(
                        retry.c.tenant_id,
                        retry.c.actor_user_id,
                        retry.c.actor_reference,
                        retry.c.actor_subject_type,
                        retry.c.actor_subject_id,
                    ).where(retry.c.id.in_(ids)),
                )
                if len(values) != len(ids) or any(value["tenant_id"] != tenant for value in values):
                    _conflict("move_membership_retry")
                for value in values:
                    validate(value)
        if self._context(session) != tenant:
            _conflict("move_membership_context_changed")
        return frozenset(found)

    async def alist_query_candidates(
        self,
        session,
        *,
        space_id,
        subject_type,
        subject_id,
        after_id=None,
        limit=200,
        state=None,
        ordered=False,
        after=None,
    ) -> tuple[str, ...]:
        """Coarse typed candidates only; the App still checks live authority."""
        tenant = self._context(session)
        if (
            type(ordered) is not bool
            or (ordered and after_id is not None)
            or (
                after is not None
                and (
                    not ordered
                    or type(after) is not tuple
                    or len(after) != 2
                    or not isinstance(after[0], datetime)
                    or not isinstance(after[1], str)
                )
            )
            or type(space_id) is not int
            or space_id <= 0
            or subject_type not in ("user", "service_account")
            or type(subject_id) is not int
            or subject_id <= 0
            or type(limit) is not int
            or not 1 <= limit <= 200
            or (after_id is not None and (not isinstance(after_id, str) or not 0 < len(after_id) <= 36))
        ):
            raise ValueError("move candidate page requires exact typed subject and bounded seek")
        job, plan, retry = (
            model.__table__
            for model in (KnowledgeProcessingJob, KnowledgeOperationPlan, KnowledgeProcessingRetryReceipt)
        )
        from sqlalchemy import and_, or_

        from bisheng.knowledge.domain.schemas.processing_job import JobState

        historical = (
            select(retry.c.id)
            .where(
                retry.c.tenant_id == tenant,
                retry.c.job_id == job.c.id,
                retry.c.actor_subject_type == subject_type,
                retry.c.actor_subject_id == subject_id,
                retry.c.expected_job_revision >= 0,
                retry.c.accepted_job_revision > retry.c.expected_job_revision,
                retry.c.accepted_job_revision <= job.c.revision,
            )
            .exists()
        )
        statement = (
            (select(job.c.id, job.c.accepted_at) if ordered else select(job.c.id))
            .select_from(
                job.join(
                    plan,
                    and_(
                        plan.c.tenant_id == tenant,
                        plan.c.operation == "move",
                        plan.c.operation_id == job.c.id,
                        plan.c.consumed_at.is_not(None),
                    ),
                )
            )
            .where(
                job.c.tenant_id == tenant,
                job.c.kind == "move_index",
                or_(job.c.space_id == space_id, plan.c.space_id == space_id),
                or_(and_(job.c.actor_subject_type == subject_type, job.c.actor_subject_id == subject_id), historical),
            )
        )
        if after_id is not None:
            statement = statement.where(job.c.id > after_id)
        if state is not None:
            statement = statement.where(job.c.state == JobState(state).value)
        if ordered and after is not None:
            timestamp, ident = after
            statement = statement.where(
                or_(job.c.accepted_at < timestamp, and_(job.c.accepted_at == timestamp, job.c.id < ident))
            )
        order = (job.c.accepted_at.desc(), job.c.id.desc()) if ordered else (job.c.id,)
        rows = await self._rows(session, statement.order_by(*order).limit(limit))
        if self._context(session) != tenant:
            _conflict("move_query_context_changed")
        return tuple((row["id"], row["accepted_at"]) for row in rows) if ordered else tuple(row["id"] for row in rows)

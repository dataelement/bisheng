"""Durable processing requests, leased items, and explicit retry receipts.

The business owner supplies freshly verified configuration while holding its
resource locks. This repository never resolves a model from task parameters,
restores a credential, performs external I/O, or commits the owner's session.
Obsolescence is returned as durable state: the owner must commit it before
rendering the corresponding error, rather than roll it back by raising early.
"""

import re
from collections.abc import Callable, Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from inspect import ismethod
from typing import Any
from uuid import uuid4
from weakref import WeakKeyDictionary

from sqlalchemy import and_, func, inspect, or_
from sqlalchemy.orm import defer
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.errcode.knowledge import (
    KnowledgeIdempotencyConflictError,
    KnowledgeProcessingConflictError,
    KnowledgeProcessingJobNotFoundError,
    KnowledgeProcessingJobNotRetryableError,
    KnowledgeProcessingObsoleteError,
    ResourceReferenceInvalidError,
)
from bisheng.common.errcode.knowledge_space import SpaceNotFoundError
from bisheng.core.context.background_execution import get_current_background_task
from bisheng.core.context.tenant import get_current_tenant_id, strict_tenant_filter
from bisheng.knowledge.domain.models.knowledge import Knowledge, KnowledgeTypeEnum
from bisheng.knowledge.domain.models.knowledge_processing_item import KnowledgeProcessingItem
from bisheng.knowledge.domain.models.knowledge_processing_job import KnowledgeProcessingJob
from bisheng.knowledge.domain.models.knowledge_processing_retry import KnowledgeProcessingRetryReceipt
from bisheng.knowledge.domain.repositories.model_reference_repository import KnowledgeModelReferenceRepository
from bisheng.knowledge.domain.schemas.processing_job import ItemState, JobState, ProcessingKind
from bisheng.knowledge.domain.schemas.processing_job_acceptance import (
    ItemLease as ItemLease,
)
from bisheng.knowledge.domain.schemas.processing_job_acceptance import (
    JobLease as JobLease,
)
from bisheng.knowledge.domain.schemas.processing_job_acceptance import (
    JobRequestResult as JobRequestResult,
)
from bisheng.knowledge.domain.schemas.processing_job_acceptance import (
    NewProcessingItem as NewProcessingItem,
)
from bisheng.knowledge.domain.schemas.processing_job_acceptance import (
    ProcessingConfiguration as ProcessingConfiguration,
)
from bisheng.knowledge.domain.schemas.processing_job_acceptance import (
    _digest as _digest,
)
from bisheng.knowledge.domain.schemas.processing_job_acceptance import (
    processing_manifest,
    processing_request_facts,
)
from bisheng.knowledge.domain.services.processing_cutover_receipts import consume_cutover_receipt
from bisheng.resource_reference.application.contracts import TransactionIdentity


@dataclass(frozen=True)
class ClaimedItem:
    item: KnowledgeProcessingItem
    lease: ItemLease


@dataclass(frozen=True)
class JobPage:
    rows: tuple[KnowledgeProcessingJob, ...]
    total: int


@dataclass(frozen=True)
class ItemPage:
    rows: tuple[KnowledgeProcessingItem, ...]
    total: int


@dataclass(frozen=True)
class JobDispatch:
    job_id: str
    tenant_id: int
    space_id: int
    kind: str
    revision: int


@dataclass(frozen=True)
class RetryEligibility:
    retryable: bool
    finalize_only: bool


@dataclass(frozen=True)
class TargetResetState:
    anchor_item_id: str
    prepared: bool
    configuration: ProcessingConfiguration


def _utc_now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


@dataclass(frozen=True, slots=True, eq=False, weakref_slot=True)
class _MetadataCompletionReceipt:
    space_id: int
    schema_revision: int
    schema_digest: str


_metadata_completions: WeakKeyDictionary = WeakKeyDictionary()


def _metadata_completion_facts(space_id, actor_user_id, actor_reference, parameters, configuration):
    # Orchestration adds its actual ledger identifiers later; it cannot change
    # the accepted business request, schema, values or timestamp through them.
    business = {
        key: value for key, value in parameters.items() if key not in {"operation_id", "confirmation_id", "plan_digest"}
    }
    return (
        space_id,
        actor_user_id,
        _digest(actor_reference),
        _digest(business),
        configuration.model_config_revision,
        configuration.index_generation,
        configuration.metadata_schema_revision,
        configuration.metadata_schema_digest,
    )


async def _metadata_root_facts(session, space_id):
    tenant = get_current_tenant_id()
    if not isinstance(session, AsyncSession) or not session.in_transaction() or type(tenant) is not int or tenant <= 0:
        raise ResourceReferenceInvalidError(reason="metadata_completion_native_transaction_required")
    from bisheng.core.context.tenant import is_tenant_filter_bypassed

    if is_tenant_filter_bypassed():
        raise ResourceReferenceInvalidError(reason="metadata_completion_concrete_tenant_required")
    fields = (
        "id",
        "tenant_id",
        "type",
        "metadata_schema_revision",
        "metadata_fields",
        "model_config_revision",
        "index_generation",
    )
    with session.no_autoflush, strict_tenant_filter():
        row = (
            await session.execute(select(*(getattr(Knowledge, key) for key in fields)).where(Knowledge.id == space_id))
        ).one_or_none()
    if row is None or row.tenant_id != tenant or row.type != KnowledgeTypeEnum.SPACE.value:
        raise ResourceReferenceInvalidError(reason="metadata_completion_space_required")
    return (
        row.id,
        row.tenant_id,
        row.metadata_schema_revision,
        _digest(row.metadata_fields or []),
        row.model_config_revision,
        row.index_generation,
    )


def _assert_no_pending_metadata_root(session, space_id):
    fields = (
        "id",
        "tenant_id",
        "type",
        "metadata_fields",
        "metadata_schema_revision",
        "model_config_revision",
        "index_generation",
    )
    for collection in (session.new, session.dirty, session.deleted):
        for row in collection:
            state = inspect(row)
            if isinstance(row, Knowledge) and space_id in (state.dict.get("id"), *(state.identity or ())):
                if (
                    row in session.new
                    or row in session.deleted
                    or any(state.attrs[name].history.has_changes() for name in fields)
                ):
                    raise ResourceReferenceInvalidError(reason="metadata_completion_pending_schema_change")


class _MetadataCompletionAuthority:
    """Private capability whose only issuance path executes the bound Owner."""

    def __init__(self, owner):
        callback = getattr(owner, "_aperform_metadata_acceptance", None)
        if not ismethod(callback) or callback.__self__ is not owner:
            raise TypeError("metadata completion requires its bound business Owner")
        self._callback = callback

    async def aaccept(self, session, prepared, *, identity):
        transaction = TransactionIdentity.capture(session)
        before = await _metadata_root_facts(session, prepared.space_id)
        accepted = await self._callback(session, prepared, identity=identity)
        transaction.assert_current(session)
        after = await _metadata_root_facts(session, prepared.space_id)
        facts = _metadata_completion_facts(
            accepted.space_id,
            accepted.actor_user_id,
            accepted.actor_reference,
            accepted.parameters,
            accepted.configuration,
        )
        if (
            after[:2] != before[:2]
            or after[2] != before[2] + 1
            or after[4:] != before[4:]
            or (after[2], after[3])
            != (accepted.configuration.metadata_schema_revision, accepted.configuration.metadata_schema_digest)
        ):
            raise ResourceReferenceInvalidError(reason="metadata_completion_business_result_changed")
        if accepted.items:
            return accepted, None
        receipt = _MetadataCompletionReceipt(after[0], after[2], after[3])
        _metadata_completions[receipt] = (transaction, self, facts, after)
        return accepted, receipt


async def _consume_metadata_completion(
    session, receipt, *, space_id, actor_user_id, actor_reference, parameters, configuration
):
    registered = _metadata_completions.get(receipt) if isinstance(receipt, _MetadataCompletionReceipt) else None
    try:
        if registered is None:
            raise ValueError("metadata completion was not issued")
        registered[0].assert_current(session)
        facts = _metadata_completion_facts(space_id, actor_user_id, actor_reference, parameters, configuration)
        _assert_no_pending_metadata_root(session, space_id)
        if (
            facts != registered[2]
            or await _metadata_root_facts(session, space_id) != registered[3]
            or (receipt.space_id, receipt.schema_revision, receipt.schema_digest)
            != (space_id, configuration.metadata_schema_revision, configuration.metadata_schema_digest)
        ):
            raise ValueError("metadata completion context changed")
    except (ValueError, TypeError) as error:
        raise ResourceReferenceInvalidError(reason="metadata_completion_receipt_invalid") from error
    del _metadata_completions[receipt]


class ProcessingJobRepository:
    def __init__(self, *, clock: Callable[[], datetime] = _utc_now):
        self.clock = clock

    def _now(self) -> datetime:
        value = self.clock()
        return value.astimezone(UTC).replace(tzinfo=None) if value.tzinfo is not None else value

    @staticmethod
    def _tenant_id() -> int:
        value = get_current_tenant_id()
        if type(value) is not int or value <= 0:
            raise RuntimeError("processing tasks require a concrete tenant context")
        return value

    @staticmethod
    def _key(value: str) -> str:
        if not isinstance(value, str) or not value or len(value) > 64:
            raise ValueError("idempotency_key must contain 1..64 characters")
        return value

    @staticmethod
    def _actor(actor_user_id: int, actor_reference: Mapping[str, Any]) -> dict:
        if type(actor_user_id) is not int or actor_user_id <= 0 or not actor_reference:
            raise ValueError("a trusted actor and its narrowing reference are required")
        copied = deepcopy(dict(actor_reference))
        _digest(copied)  # Reject non-JSON references before any write.
        return copied

    async def _space(self, session: AsyncSession, space_id: int, *, lock: bool = True) -> None:
        tenant_id = self._tenant_id()
        statement = select(Knowledge).where(Knowledge.id == space_id, Knowledge.type == KnowledgeTypeEnum.SPACE.value)
        if lock:
            statement = statement.with_for_update().execution_options(populate_existing=True)
        with strict_tenant_filter():
            row = (await session.exec(statement)).one_or_none()
        if row is None or row.tenant_id != tenant_id:
            raise SpaceNotFoundError()

    async def _job(
        self, session: AsyncSession, job_id: str, *, lock: bool, include_manifest: bool = True
    ) -> KnowledgeProcessingJob:
        tenant_id = self._tenant_id()
        statement = select(KnowledgeProcessingJob).where(KnowledgeProcessingJob.id == job_id)
        if not include_manifest:
            cached = session.identity_map.get(inspect(KnowledgeProcessingJob).identity_key_from_primary_key((job_id,)))
            if cached is not None and inspect(cached).dict.get("kind") == "metadata_schema_change":
                # A prior query may have loaded the manifest in this Session.
                # Expire only that immutable execution-irrelevant attribute so
                # the explicit raiseload option cannot reuse its cached JSON.
                session.expire(cached, ["scope_manifest"])
            statement = statement.options(defer(KnowledgeProcessingJob.scope_manifest, raiseload=True))
            statement = statement.execution_options(populate_existing=True)
        if lock:
            statement = statement.with_for_update().execution_options(populate_existing=True)
        with strict_tenant_filter():
            row = (await session.exec(statement)).one_or_none()
        if row is None or row.tenant_id != tenant_id:
            raise KnowledgeProcessingJobNotFoundError()
        if not include_manifest and row.kind != "metadata_schema_change":
            # Existing kinds retain their complete historical manifest. Only
            # metadata uses the explicit bounded execution representation.
            with strict_tenant_filter():
                await session.refresh(row, attribute_names=["scope_manifest"])
        return row

    async def aget(self, session: AsyncSession, job_id: str) -> KnowledgeProcessingJob:
        return await self._job(session, job_id, lock=False)

    async def aget_execution(self, session: AsyncSession, job_id: str) -> KnowledgeProcessingJob:
        return await self._job(session, job_id, lock=False, include_manifest=False)

    async def aget_by_request_key(
        self, session: AsyncSession, kind: str, idempotency_key: str, *, lock: bool = False
    ) -> KnowledgeProcessingJob | None:
        tenant = self._tenant_id()
        query = select(KnowledgeProcessingJob).where(
            KnowledgeProcessingJob.kind == ProcessingKind(kind).value,
            KnowledgeProcessingJob.idempotency_key == self._key(idempotency_key),
        )
        if lock:
            query = query.with_for_update().execution_options(populate_existing=True)
        with strict_tenant_filter():
            row = (await session.exec(query)).one_or_none()
        if row is not None and row.tenant_id != tenant:
            raise KnowledgeProcessingJobNotFoundError()
        return row

    @staticmethod
    def _page(page: int, page_size: int) -> int:
        if type(page) is not int or page < 1 or type(page_size) is not int or not 1 <= page_size <= 200:
            raise ValueError("page must be positive and page_size must be 1..200")
        return (page - 1) * page_size

    async def alist_jobs(
        self,
        session: AsyncSession,
        space_id: int,
        *,
        page: int,
        page_size: int,
        kind: str | None = None,
        state: str | None = None,
    ) -> JobPage:
        offset = self._page(page, page_size)
        await self._space(session, space_id, lock=False)
        filters = [KnowledgeProcessingJob.space_id == space_id]
        if kind is not None:
            filters.append(KnowledgeProcessingJob.kind == ProcessingKind(kind).value)
        if state is not None:
            filters.append(KnowledgeProcessingJob.state == JobState(state).value)
        with strict_tenant_filter():
            total = (await session.exec(select(func.count()).select_from(KnowledgeProcessingJob).where(*filters))).one()
            rows = (
                await session.exec(
                    select(KnowledgeProcessingJob)
                    .where(*filters)
                    .order_by(KnowledgeProcessingJob.accepted_at.desc(), KnowledgeProcessingJob.id.desc())
                    .offset(offset)
                    .limit(page_size)
                )
            ).all()
        if any(row.tenant_id != self._tenant_id() for row in rows):
            raise KnowledgeProcessingJobNotFoundError()
        return JobPage(tuple(rows), total)

    async def alist_items(
        self,
        session: AsyncSession,
        job_id: str,
        *,
        page: int,
        page_size: int,
        visible_file_ids: Sequence[int],
        state: str | None = None,
    ) -> ItemPage:
        offset = self._page(page, page_size)
        job = await self._job(session, job_id, lock=False, include_manifest=False)
        ids = tuple(dict.fromkeys(visible_file_ids))
        if any(type(value) is not int or value <= 0 for value in ids):
            raise ValueError("visible scope requires positive file identities")
        filters = [KnowledgeProcessingItem.job_id == job.id, KnowledgeProcessingItem.file_id.in_(ids)]
        if state is not None:
            filters.append(KnowledgeProcessingItem.state == ItemState(state).value)
        with strict_tenant_filter():
            total = (
                await session.exec(select(func.count()).select_from(KnowledgeProcessingItem).where(*filters))
            ).one()
            rows = (
                await session.exec(
                    select(KnowledgeProcessingItem)
                    .where(*filters)
                    .order_by(
                        KnowledgeProcessingItem.file_id, KnowledgeProcessingItem.version_id, KnowledgeProcessingItem.id
                    )
                    .offset(offset)
                    .limit(page_size)
                )
            ).all()
        if any(row.tenant_id != job.tenant_id for row in rows):
            raise KnowledgeProcessingJobNotFoundError()
        return ItemPage(tuple(rows), total)

    async def alatest_retry_actor(self, session: AsyncSession, job_id: str) -> dict:
        job = await self._job(session, job_id, lock=False, include_manifest=False)
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
                )
            ).one_or_none()
        if receipt is not None and receipt.tenant_id != job.tenant_id:
            raise KnowledgeProcessingJobNotFoundError()
        return deepcopy(receipt.actor_reference if receipt is not None else job.actor_reference)

    async def adispatch_candidates(
        self,
        session: AsyncSession,
        *,
        now: datetime,
        after_id: str | None = None,
        limit: int = 200,
    ) -> tuple[JobDispatch, ...]:
        tenant = self._tenant_id()
        if type(limit) is not int or not 1 <= limit <= 200:
            raise ValueError("dispatch batch must be 1..200")
        now = now.astimezone(UTC).replace(tzinfo=None) if now.tzinfo is not None else now
        active = or_(
            and_(KnowledgeProcessingJob.state == "accepted", KnowledgeProcessingJob.pending_dispatch == True),  # noqa: E712
            and_(
                KnowledgeProcessingJob.state == "running",
                or_(KnowledgeProcessingJob.lease_until.is_(None), KnowledgeProcessingJob.lease_until <= now),
            ),
        )
        statement = (
            select(KnowledgeProcessingJob)
            .options(defer(KnowledgeProcessingJob.scope_manifest, raiseload=True))
            .where(active, KnowledgeProcessingJob.next_dispatch_at <= now)
        )
        if after_id is not None:
            statement = statement.where(KnowledgeProcessingJob.id > after_id)
        with strict_tenant_filter():
            rows = (await session.exec(statement.order_by(KnowledgeProcessingJob.id).limit(limit))).all()
        if any(row.tenant_id != tenant for row in rows):
            raise KnowledgeProcessingJobNotFoundError()
        return tuple(JobDispatch(row.id, row.tenant_id, row.space_id, row.kind, row.revision) for row in rows)

    async def arecord_dispatch(
        self,
        session: AsyncSession,
        job_id: str,
        *,
        expected_revision: int,
        published: bool,
        next_at: datetime,
        error_code: int | None = None,
    ) -> bool:
        if type(expected_revision) is not int or expected_revision < 0 or type(published) is not bool:
            raise ValueError("dispatch acknowledgement requires an expected revision and boolean result")
        job = await self._job(session, job_id, lock=True, include_manifest=False)
        if job.revision != expected_revision or (
            not (job.state == "accepted" and job.pending_dispatch)
            and not (job.state == "running" and (job.lease_until is None or job.lease_until <= self._now()))
        ):
            return False
        job.dispatch_attempts += 1
        job.dispatch_error_code = None if published else error_code
        job.next_dispatch_at = next_at.astimezone(UTC).replace(tzinfo=None) if next_at.tzinfo is not None else next_at
        job.update_time = self._now()
        # A successful broker publish may still lose its acknowledgement or
        # delivery. Only a real claim clears pending_dispatch.
        await session.flush()
        return True

    async def _item(self, session: AsyncSession, job: KnowledgeProcessingJob, item_id: str) -> KnowledgeProcessingItem:
        with strict_tenant_filter():
            row = (
                await session.exec(
                    select(KnowledgeProcessingItem)
                    .where(KnowledgeProcessingItem.id == item_id, KnowledgeProcessingItem.job_id == job.id)
                    .with_for_update()
                    .execution_options(populate_existing=True)
                )
            ).one_or_none()
        if row is None or row.tenant_id != job.tenant_id:
            raise KnowledgeProcessingJobNotFoundError()
        return row

    async def acreate(
        self,
        session: AsyncSession,
        *,
        space_id: int,
        kind: str,
        idempotency_key: str,
        actor_user_id: int,
        actor_reference: Mapping[str, Any],
        parameters: Mapping[str, Any],
        configuration: ProcessingConfiguration,
        items: Sequence[NewProcessingItem],
        space_config_version: int = 0,
        metadata_acceptance=None,
    ) -> JobRequestResult:
        tenant_id = self._tenant_id()
        kind = ProcessingKind(kind).value
        idempotency_key = self._key(idempotency_key)
        actor = self._actor(actor_user_id, actor_reference)
        if (
            type(space_config_version) is not int
            or space_config_version < 0
            or (not items and kind != "metadata_schema_change")
        ):
            raise ValueError("a nonempty frozen scope and non-negative settings version are required")
        if not items:
            _assert_no_pending_metadata_root(session, space_id)
        manifest = processing_manifest(space_id, items)
        payload = deepcopy(dict(parameters))
        request_facts = processing_request_facts(
            tenant_id=tenant_id,
            space_id=space_id,
            kind=kind,
            actor_user_id=actor_user_id,
            actor_reference=actor,
            parameters=payload,
            manifest=manifest,
            configuration=configuration,
            space_config_version=space_config_version,
        )
        request_hash = _digest(request_facts)
        # The verified owning resource lock serializes same-space creation;
        # the database unique key is the final cross-space collision guard.
        await self._space(session, space_id)
        with strict_tenant_filter():
            existing = (
                await session.exec(
                    select(KnowledgeProcessingJob)
                    .where(
                        KnowledgeProcessingJob.kind == kind, KnowledgeProcessingJob.idempotency_key == idempotency_key
                    )
                    .with_for_update()
                    .execution_options(populate_existing=True)
                )
            ).one_or_none()
        if existing is not None:
            if existing.tenant_id != tenant_id or existing.request_hash != request_hash:
                raise KnowledgeIdempotencyConflictError()
            return JobRequestResult(existing, True)
        if not manifest:
            await _consume_metadata_completion(
                session,
                metadata_acceptance,
                space_id=space_id,
                actor_user_id=actor_user_id,
                actor_reference=actor,
                parameters=payload,
                configuration=configuration,
            )
        now = self._now()
        job = KnowledgeProcessingJob(
            tenant_id=tenant_id,
            space_id=space_id,
            kind=kind,
            actor_user_id=actor_user_id,
            actor_reference=actor,
            idempotency_key=idempotency_key,
            request_hash=request_hash,
            parameters=payload,
            scope_manifest=(
                [
                    {
                        **{
                            key: value[key]
                            for key in (
                                "file_id",
                                "document_id",
                                "version_id",
                                "expected_space_id",
                                "expected_parent_id",
                            )
                        },
                        "processing_snapshot_digest": _digest(value["processing_snapshot"]),
                    }
                    for value in manifest
                ]
                if kind == "metadata_schema_change"
                else manifest
            ),
            expected_model_config_revision=configuration.model_config_revision,
            accepted_model_config_revision=configuration.model_config_revision,
            expected_index_generation=configuration.index_generation,
            space_config_version=space_config_version,
            total_count=len(manifest),
            pending_count=len(manifest),
            accepted_at=now,
            next_dispatch_at=now,
            create_time=now,
            update_time=now,
            state="accepted" if manifest else "succeeded",
            pending_dispatch=bool(manifest),
            started_at=None if manifest else now,
            finished_at=None if manifest else now,
        )
        session.add(job)
        for value in manifest:
            session.add(KnowledgeProcessingItem(tenant_id=tenant_id, job_id=job.id, **value))
        await session.flush()
        return JobRequestResult(job, False)

    @staticmethod
    def _same_job_lease(job: KnowledgeProcessingJob, lease: JobLease) -> bool:
        return (
            job.id == lease.job_id
            and job.lease_token == lease.lease_token
            and job.claim_generation == lease.claim_generation
        )

    def _active_job_lease(self, job: KnowledgeProcessingJob, lease: JobLease) -> bool:
        return (
            self._same_job_lease(job, lease)
            and job.state == "running"
            and job.lease_until is not None
            and job.lease_until > self._now()
        )

    def _check_configuration(self, job: KnowledgeProcessingJob, configuration: ProcessingConfiguration) -> bool:
        reason = None
        if job.expected_model_config_revision != configuration.model_config_revision:
            reason = "model_config_revision_changed"
        elif job.expected_index_generation != configuration.index_generation:
            reason = "index_generation_changed"
        elif job.kind == "metadata_schema_change":
            metadata_evidence = job.parameters if isinstance(job.parameters, Mapping) else {}
            revision = metadata_evidence.get("metadata_schema_revision")
            digest = metadata_evidence.get("metadata_schema_digest")
            if (
                type(revision) is not int
                or revision < 0
                or not isinstance(digest, str)
                or re.fullmatch(r"[0-9a-f]{64}", digest) is None
                or configuration.metadata_schema_revision is None
                or configuration.metadata_schema_digest is None
            ):
                reason = "metadata_schema_evidence_missing"
            elif revision != configuration.metadata_schema_revision:
                reason = "metadata_schema_revision_changed"
            elif digest != configuration.metadata_schema_digest:
                reason = "metadata_schema_digest_changed"
        if reason is None:
            return True
        job.state = "obsolete"
        job.obsolete_reason = reason
        job.error_code = KnowledgeProcessingObsoleteError.Code
        job.pending_dispatch = False
        job.lease_until = None
        job.finished_at = job.update_time = self._now()
        job.revision += 1
        return False

    async def aclaim(
        self,
        session: AsyncSession,
        job_id: str,
        *,
        configuration: ProcessingConfiguration,
        expected_job_revision: int | None = None,
        lease_seconds: int = 900,
    ) -> JobLease | None:
        if type(lease_seconds) is not int or lease_seconds <= 0:
            raise ValueError("lease_seconds must be positive")
        if expected_job_revision is not None and (type(expected_job_revision) is not int or expected_job_revision < 0):
            raise ValueError("expected_job_revision must be a non-negative integer")
        job = await self._job(session, job_id, lock=True, include_manifest=False)
        if expected_job_revision is not None and job.revision != expected_job_revision:
            return None
        now = self._now()
        if job.state not in {"accepted", "running"}:
            return None
        if job.state == "running" and job.lease_until is not None and job.lease_until > now:
            return None
        if not self._check_configuration(job, configuration):
            await session.flush()
            return None
        job.claim_generation += 1
        job.lease_token = str(uuid4())
        job.lease_until = now + timedelta(seconds=lease_seconds)
        job.state = "running"
        job.pending_dispatch = False
        job.started_at = job.started_at or now
        job.finished_at = None
        job.update_time = now
        job.revision += 1
        await session.flush()
        return JobLease(job.id, job.lease_token, job.claim_generation, job.lease_until)

    async def arenew(
        self,
        session: AsyncSession,
        lease: JobLease,
        *,
        configuration: ProcessingConfiguration,
        lease_seconds: int = 900,
    ) -> JobLease | None:
        if type(lease_seconds) is not int or lease_seconds <= 0:
            raise ValueError("lease_seconds must be positive")
        job = await self._job(session, lease.job_id, lock=True, include_manifest=False)
        if not self._active_job_lease(job, lease):
            return None
        if not self._check_configuration(job, configuration):
            await session.flush()
            return None
        job.lease_until = self._now() + timedelta(seconds=lease_seconds)
        job.update_time = self._now()
        await session.flush()
        return JobLease(job.id, job.lease_token, job.claim_generation, job.lease_until)

    async def aclaim_next_item(
        self, session: AsyncSession, lease: JobLease, *, configuration: ProcessingConfiguration
    ) -> ClaimedItem | None:
        job = await self._job(session, lease.job_id, lock=True, include_manifest=False)
        if not self._active_job_lease(job, lease):
            return None
        if not self._check_configuration(job, configuration):
            await session.flush()
            return None
        now = self._now()
        # Job-row locking serializes item leasing; no dialect-specific SKIP LOCKED.
        query = select(KnowledgeProcessingItem).where(
            KnowledgeProcessingItem.job_id == job.id,
            KnowledgeProcessingItem.state.in_(["pending", "running"]),
        )
        if job.kind == "metadata_schema_change":
            query = query.where(
                or_(
                    KnowledgeProcessingItem.state == "pending",
                    KnowledgeProcessingItem.lease_until.is_(None),
                    KnowledgeProcessingItem.lease_until <= now,
                )
            ).limit(1)
        query = (
            query.order_by(KnowledgeProcessingItem.file_id, KnowledgeProcessingItem.version_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        with strict_tenant_filter():
            candidates = (await session.exec(query)).all()
        for row in candidates:
            if row.tenant_id != job.tenant_id:
                raise KnowledgeProcessingJobNotFoundError()
            if row.state == "running" and row.lease_until is not None and row.lease_until > now:
                continue
            row.state = "running"
            row.attempt += 1
            row.claim_generation += 1
            row.lease_token = str(uuid4())
            row.lease_until = job.lease_until
            row.started_at = row.started_at or now
            row.finished_at = None
            row.error_code = None
            row.update_time = now
            await session.flush()
            return ClaimedItem(row, ItemLease(lease, row.id, row.lease_token, row.claim_generation, row.lease_until))
        return None

    def _active_item_lease(self, row: KnowledgeProcessingItem, lease: ItemLease) -> bool:
        return (
            row.id == lease.item_id
            and row.lease_token == lease.lease_token
            and row.claim_generation == lease.claim_generation
            and row.state == "running"
            and row.lease_until is not None
            and row.lease_until > self._now()
        )

    async def _guard_item(
        self, session: AsyncSession, lease: ItemLease, configuration: ProcessingConfiguration
    ) -> tuple[KnowledgeProcessingJob, KnowledgeProcessingItem] | None:
        job = await self._job(session, lease.job.job_id, lock=True, include_manifest=False)
        if not self._active_job_lease(job, lease.job):
            return None
        row = await self._item(session, job, lease.item_id)
        if not self._active_item_lease(row, lease):
            return None
        if not self._check_configuration(job, configuration):
            await session.flush()
            return None
        return job, row

    async def asave_checkpoint(
        self,
        session: AsyncSession,
        lease: ItemLease,
        *,
        configuration: ProcessingConfiguration,
        step: str,
        checkpoint: Mapping[str, Any],
    ) -> bool:
        if not isinstance(step, str) or not step or len(step) > 64:
            raise ValueError("step must contain 1..64 characters")
        value = deepcopy(dict(checkpoint))
        _digest(value)
        guarded = await self._guard_item(session, lease, configuration)
        if guarded is None:
            return False
        _, row = guarded
        row.step, row.checkpoint, row.update_time = step, value, self._now()
        await session.flush()
        return True

    async def arenew_item(
        self,
        session: AsyncSession,
        lease: ItemLease,
        *,
        configuration: ProcessingConfiguration,
        lease_seconds: int = 900,
    ) -> ItemLease | None:
        if type(lease_seconds) is not int or lease_seconds <= 0:
            raise ValueError("lease_seconds must be positive")
        guarded = await self._guard_item(session, lease, configuration)
        if guarded is None:
            return None
        job, row = guarded
        row.lease_until = min(job.lease_until, self._now() + timedelta(seconds=lease_seconds))
        row.update_time = self._now()
        await session.flush()
        current_job_lease = JobLease(job.id, job.lease_token, job.claim_generation, job.lease_until)
        return ItemLease(current_job_lease, row.id, row.lease_token, row.claim_generation, row.lease_until)

    async def _state_counts(self, session: AsyncSession, job_id: str) -> dict[str, int]:
        with strict_tenant_filter():
            rows = (
                await session.exec(
                    select(KnowledgeProcessingItem.state, func.count())
                    .where(KnowledgeProcessingItem.job_id == job_id)
                    .group_by(KnowledgeProcessingItem.state)
                )
            ).all()
        return dict(rows)

    async def _item_counts(self, session: AsyncSession, job: KnowledgeProcessingJob) -> dict[str, int]:
        counts = await self._state_counts(session, job.id)
        total = sum(counts.values())
        expected_count = job.total_count if job.kind == "metadata_schema_change" else len(job.scope_manifest)
        if total != expected_count:
            raise KnowledgeProcessingConflictError(reason="processing_scope_incomplete")
        return counts

    async def aretry_eligibility(self, session: AsyncSession, job_id: str) -> RetryEligibility:
        # Eligibility is a read projection, not an execution refresh. Returning
        # scalars preserves a caller's already loaded public/audit manifest.
        query = select(
            KnowledgeProcessingJob.tenant_id,
            KnowledgeProcessingJob.kind,
            KnowledgeProcessingJob.state,
            KnowledgeProcessingJob.total_count,
            KnowledgeProcessingJob.error_code,
        ).where(KnowledgeProcessingJob.id == job_id)
        with strict_tenant_filter():
            job = (await session.execute(query)).one_or_none()
        if job is None or job.tenant_id != self._tenant_id():
            raise KnowledgeProcessingJobNotFoundError()
        if job.kind == "metadata_schema_change":
            expected_count = job.total_count
        else:
            with strict_tenant_filter():
                manifest = (
                    await session.exec(
                        select(KnowledgeProcessingJob.scope_manifest).where(KnowledgeProcessingJob.id == job_id)
                    )
                ).one()
            expected_count = len(manifest)
        counts = await self._state_counts(session, job_id)
        if sum(counts.values()) != expected_count:
            raise KnowledgeProcessingConflictError(reason="processing_scope_incomplete")
        terminal_failure = job.state in {"failed", "partial_failed"}
        finalize_only = (
            terminal_failure
            and job.error_code is not None
            and expected_count > 0
            and counts.get("succeeded", 0) == expected_count
        )
        return RetryEligibility(
            terminal_failure and (bool(counts.get("failed", 0) + counts.get("pending", 0)) or finalize_only),
            finalize_only,
        )

    async def _refresh_counts(self, session: AsyncSession, job: KnowledgeProcessingJob) -> None:
        counts = await self._item_counts(session, job)
        total = sum(counts.values())
        job.total_count = total
        job.succeeded_count = counts.get("succeeded", 0)
        job.failed_count = counts.get("failed", 0)
        job.pending_count = total - job.succeeded_count - job.failed_count

    async def acomplete_item(
        self,
        session: AsyncSession,
        lease: ItemLease,
        *,
        configuration: ProcessingConfiguration,
        succeeded: bool,
        result: Mapping[str, Any] | None = None,
        error_code: int | None = None,
    ) -> bool:
        outcome = deepcopy(dict(result or {}))
        _digest(outcome)
        guarded = await self._guard_item(session, lease, configuration)
        if guarded is None:
            return False
        job, row = guarded
        row.state = "succeeded" if succeeded else "failed"
        row.result = outcome
        row.error_code = None if succeeded else error_code
        row.finished_at = row.update_time = self._now()
        row.lease_until = None
        await session.flush()
        await self._refresh_counts(session, job)
        job.update_time = self._now()
        job.revision += 1
        await session.flush()
        # Actual business/index cutover precedes the explicit afinalize call.
        return True

    async def aacknowledge_cutover(self, session: AsyncSession, lease: JobLease, *, receipt):
        job = await self._job(session, lease.job_id, lock=True)
        if not self._active_job_lease(job, lease):
            return None
        revision, generation = consume_cutover_receipt(session, receipt, job, lease)
        job.expected_model_config_revision = revision
        job.expected_index_generation = generation
        job.revision += 1
        job.update_time = self._now()
        await session.flush()
        return job

    @staticmethod
    def _reset_marker(job):
        if (
            type(job.accepted_model_config_revision) is not int
            or job.accepted_model_config_revision < 0
            or not job.expected_index_generation
            or not isinstance(job.parameters.get("operation_id"), str)
            or not job.parameters["operation_id"]
        ):
            raise ResourceReferenceInvalidError(reason="processing_reset_original_evidence_required")
        return {
            "schema_version": 1,
            "job_id": job.id,
            "operation_id": job.parameters["operation_id"],
            "accepted_model_config_revision": job.accepted_model_config_revision,
            "index_generation": job.expected_index_generation,
        }

    async def areset_target_state(self, session: AsyncSession, lease: JobLease) -> TargetResetState | None:
        candidate = await self._job(session, lease.job_id, lock=False)
        root = await KnowledgeModelReferenceRepository().aget(session, candidate.space_id, for_update=True)
        job = await self._job(session, lease.job_id, lock=True)
        if not self._active_job_lease(job, lease):
            return None
        if root is None:
            raise KnowledgeProcessingConflictError(reason="processing_reset_owner_missing")
        current = ProcessingConfiguration(root.model_config_revision, root.index_generation)
        if not self._check_configuration(job, current):
            await session.flush()
            return None
        marker = self._reset_marker(job)
        with strict_tenant_filter():
            anchor = (
                await session.exec(
                    select(KnowledgeProcessingItem)
                    .where(KnowledgeProcessingItem.job_id == job.id)
                    .order_by(
                        KnowledgeProcessingItem.file_id, KnowledgeProcessingItem.version_id, KnowledgeProcessingItem.id
                    )
                    .limit(1)
                    .with_for_update()
                    .execution_options(populate_existing=True)
                )
            ).one_or_none()
        if anchor is None or anchor.tenant_id != job.tenant_id:
            raise KnowledgeProcessingConflictError(reason="processing_scope_incomplete")
        stored = anchor.checkpoint.get("target_reset")
        prepared = isinstance(stored, dict) and _digest(stored) == _digest(marker)
        counts = await self._item_counts(session, job)
        if counts.get("succeeded", 0) and not prepared:
            raise KnowledgeProcessingConflictError(reason="processing_reset_evidence_missing")
        return TargetResetState(anchor.id, prepared, current)

    async def amark_target_reset(self, session: AsyncSession, lease: ItemLease) -> bool:
        state = await self.areset_target_state(session, lease.job)
        if state is None:
            return False
        guarded = await self._guard_item(session, lease, state.configuration)
        if guarded is None:
            return False
        job, item = guarded
        if item.id != state.anchor_item_id:
            raise KnowledgeProcessingConflictError(reason="processing_reset_anchor_changed")
        checkpoint = deepcopy(item.checkpoint)
        checkpoint["target_reset"] = self._reset_marker(job)
        return await self.asave_checkpoint(
            session, lease, configuration=state.configuration, step="target_prepared", checkpoint=checkpoint
        )

    async def afail_attempt(
        self,
        session: AsyncSession,
        job_id: str,
        *,
        expected_job_revision: int,
        error_code: int,
        lease: JobLease | None = None,
    ) -> KnowledgeProcessingJob | None:
        background = get_current_background_task()
        if background is None or background.tenant_id != self._tenant_id():
            raise ResourceReferenceInvalidError(reason="processing_attempt_background_required")
        if type(expected_job_revision) is not int or expected_job_revision < 0 or type(error_code) is not int:
            raise ValueError("failure requires the observed revision and a public error code")
        candidate = await self._job(session, job_id, lock=False, include_manifest=False)
        root = await KnowledgeModelReferenceRepository().aget(session, candidate.space_id, for_update=True)
        job = await self._job(session, job_id, lock=True, include_manifest=False)
        if job.state not in {"accepted", "running"}:
            return None
        if lease is not None:
            if not self._active_job_lease(job, lease):
                return None
        elif job.revision != expected_job_revision or (
            job.state == "running" and job.lease_until is not None and job.lease_until > self._now()
        ):
            return None
        if root is None:
            job.state = "obsolete"
            job.obsolete_reason = "owning_space_missing"
            job.error_code = KnowledgeProcessingObsoleteError.Code
        elif not self._check_configuration(
            job,
            ProcessingConfiguration(
                root.model_config_revision,
                root.index_generation,
                **(
                    {
                        "metadata_schema_revision": root.metadata_schema_revision,
                        "metadata_schema_digest": _digest(root.metadata_fields or []),
                    }
                    if job.kind == "metadata_schema_change"
                    else {}
                ),
            ),
        ):
            await session.flush()
            return job
        else:
            unfinished_query = select(KnowledgeProcessingItem)
            if job.kind == "metadata_schema_change":
                unfinished_query = unfinished_query.options(
                    defer(KnowledgeProcessingItem.processing_snapshot, raiseload=True)
                )
            with strict_tenant_filter():
                unfinished = (
                    await session.exec(
                        unfinished_query.where(
                            KnowledgeProcessingItem.job_id == job.id,
                            KnowledgeProcessingItem.state.in_(("pending", "running")),
                        )
                        .with_for_update()
                        .execution_options(populate_existing=True)
                    )
                ).all()
            for item in unfinished:
                if item.tenant_id != job.tenant_id:
                    raise KnowledgeProcessingJobNotFoundError()
                item.state = "failed"
                item.error_code = error_code
                item.lease_token = item.lease_until = None
                item.finished_at = item.update_time = self._now()
            await session.flush()
            await self._refresh_counts(session, job)
            job.state = "partial_failed" if job.succeeded_count and job.failed_count else "failed"
            job.error_code = error_code
        job.pending_dispatch = False
        job.lease_token = job.lease_until = None
        job.finished_at = job.update_time = self._now()
        job.revision += 1
        await session.flush()
        return job

    async def afinalize(
        self, session: AsyncSession, lease: JobLease, *, configuration: ProcessingConfiguration
    ) -> KnowledgeProcessingJob | None:
        job = await self._job(session, lease.job_id, lock=True, include_manifest=False)
        if not self._active_job_lease(job, lease):
            return None
        if not self._check_configuration(job, configuration):
            await session.flush()
            return job
        await self._refresh_counts(session, job)
        if job.pending_count:
            return None
        job.state = "succeeded" if not job.failed_count else ("partial_failed" if job.succeeded_count else "failed")
        job.finished_at = job.update_time = self._now()
        job.lease_until = None
        job.pending_dispatch = False
        job.revision += 1
        await session.flush()
        return job

    async def aretry_failed(
        self,
        session: AsyncSession,
        job_id: str,
        *,
        idempotency_key: str,
        expected_job_revision: int,
        actor_user_id: int,
        actor_reference: Mapping[str, Any],
        configuration: ProcessingConfiguration,
    ) -> JobRequestResult:
        job = await self._job(session, job_id, lock=True, include_manifest=False)
        key = self._key(idempotency_key)
        actor = self._actor(actor_user_id, actor_reference)
        if type(expected_job_revision) is not int or expected_job_revision < 0:
            raise ValueError("expected_job_revision must be a non-negative integer")
        request_hash = _digest(
            {
                "tenant_id": self._tenant_id(),
                "job_id": job.id,
                "expected_job_revision": expected_job_revision,
                "actor_user_id": actor_user_id,
                "actor_reference": actor,
            }
        )
        with strict_tenant_filter():
            receipt = (
                await session.exec(
                    select(KnowledgeProcessingRetryReceipt)
                    .where(
                        KnowledgeProcessingRetryReceipt.job_id == job.id,
                        KnowledgeProcessingRetryReceipt.idempotency_key == key,
                    )
                    .with_for_update()
                )
            ).one_or_none()
        if receipt is not None:
            if receipt.tenant_id != job.tenant_id or receipt.request_hash != request_hash:
                raise KnowledgeIdempotencyConflictError()
            return JobRequestResult(job, True)
        if job.state == "obsolete":
            return JobRequestResult(job, False)
        if job.revision != expected_job_revision or job.state not in {"failed", "partial_failed"}:
            raise KnowledgeProcessingJobNotRetryableError()
        if not self._check_configuration(job, configuration):
            await session.flush()
            return JobRequestResult(job, False)
        retry_query = select(KnowledgeProcessingItem)
        if job.kind == "metadata_schema_change":
            retry_query = retry_query.options(defer(KnowledgeProcessingItem.processing_snapshot, raiseload=True))
        with strict_tenant_filter():
            rows = (
                await session.exec(
                    retry_query.where(
                        KnowledgeProcessingItem.job_id == job.id,
                        KnowledgeProcessingItem.state.in_(["failed", "pending"]),
                    )
                    .with_for_update()
                    .execution_options(populate_existing=True)
                )
            ).all()
        if not rows and not (await self.aretry_eligibility(session, job.id)).finalize_only:
            raise KnowledgeProcessingJobNotRetryableError()
        for row in rows:
            if row.tenant_id != job.tenant_id:
                raise KnowledgeProcessingJobNotFoundError()
            row.state = "pending"
            row.finished_at = row.lease_until = None
            row.lease_token = None
            row.update_time = self._now()
        job.state = "accepted"
        job.finished_at = job.lease_until = None
        job.lease_token = None
        job.pending_dispatch = True
        job.next_dispatch_at = job.update_time = self._now()
        job.error_code = None
        job.error_message = None
        job.revision += 1
        await session.flush()
        await self._refresh_counts(session, job)
        session.add(
            KnowledgeProcessingRetryReceipt(
                tenant_id=job.tenant_id,
                job_id=job.id,
                idempotency_key=key,
                request_hash=request_hash,
                actor_user_id=actor_user_id,
                actor_reference=actor,
                expected_job_revision=expected_job_revision,
                accepted_job_revision=job.revision,
                item_count=len(rows),
                accepted_at=self._now(),
            )
        )
        await session.flush()
        return JobRequestResult(job, False)

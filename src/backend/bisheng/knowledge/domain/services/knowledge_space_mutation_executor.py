from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from inspect import isawaitable
from typing import Any
from uuid import uuid4

from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.core.context.tenant import get_current_tenant_id
from bisheng.core.database import get_async_db_session
from bisheng.knowledge.domain.models.knowledge_space_file_change_execution_step import (
    KnowledgeSpaceFileChangeExecutionStepState,
)
from bisheng.knowledge.domain.models.knowledge_space_file_change_request import (
    KnowledgeSpaceFileChangeAction,
    KnowledgeSpaceFileChangeExecutionState,
)
from bisheng.knowledge.domain.repositories.knowledge_space_file_change_execution_step_repository import (
    KnowledgeSpaceFileChangeExecutionStepRepository,
)
from bisheng.knowledge.domain.repositories.knowledge_space_file_change_request_repository import (
    KnowledgeSpaceFileChangeRequestRepository,
)
from bisheng.knowledge.domain.repositories.knowledge_space_mutation_repository import (
    KnowledgeSpaceMutationRepository,
)
from bisheng.knowledge.domain.services.knowledge_space_mutation_step_owner import (
    MutationStepOwner,
    OwnerStepResult,
    ProductionMutationStepOwner,
)

SessionFactory = Callable[[], AbstractAsyncContextManager[AsyncSession]]


class UploadExecutionStepCode:
    FGA = "upload.fga"
    PARSE = "upload.parse"
    INDEX = "upload.index"
    VECTOR = "upload.vector"

    ALL = (FGA, PARSE, INDEX, VECTOR)
    BUSINESS_REQUIRED = (FGA, PARSE)


@dataclass(frozen=True, slots=True)
class UploadStepDispatchContext:
    tenant_id: int
    request_id: int
    execution_token: str
    step_code: str
    idempotency_key: str
    file_id: int
    file_name: str
    applicant_user_id: int
    space_id: int
    checkpoint: dict[str, Any]


UploadSideEffect = Callable[[UploadStepDispatchContext], Awaitable[str | None] | str | None]
UploadExecutionValidator = Callable[..., Awaitable[None] | None]


class RenameExecutionStepCode:
    INDEX_SHADOW = "rename.index_shadow"
    VERIFY = "rename.verify"
    DB_CUTOVER = "rename.db_cutover"

    EXTERNAL = (INDEX_SHADOW, VERIFY)
    ALL = (*EXTERNAL, DB_CUTOVER)


class MoveExecutionStepCode:
    PARENT_TUPLE = "move.parent_prepare"
    TAGS = "move.tags_prepare"
    STORAGE = "move.storage_prepare"
    INDEX = "move.index_prepare"
    VERIFY = "move.verify"
    DB_CUTOVER = "move.db_cutover"

    EXTERNAL = (PARENT_TUPLE, TAGS, STORAGE, INDEX, VERIFY)
    ALL = (*EXTERNAL, DB_CUTOVER)


class DeleteExecutionStepCode:
    PREPARE = "delete.prepare"
    DB_CUTOVER = "delete.db_cutover"
    FGA = "delete.fga_purge"
    MINIO = "delete.minio_purge"
    ES = "delete.es_purge"
    MILVUS = "delete.milvus_purge"

    PURGE = (FGA, MINIO, ES, MILVUS)
    ALL = (PREPARE, DB_CUTOVER, *PURGE)


@dataclass(frozen=True, slots=True)
class VerifiedMutationStepResult:
    """Authoritative side-effect acknowledgement, never an enqueue receipt."""

    result_digest: str


@dataclass(frozen=True, slots=True)
class MutationStepContext:
    tenant_id: int
    request_id: int
    execution_token: str
    action: str
    step_code: str
    idempotency_key: str
    resource_type: str
    resource_id: int
    applicant_user_id: int
    source_space_id: int
    target_space_id: int | None
    manifest: dict[str, Any]


MutationStepEffect = Callable[
    [MutationStepContext],
    Awaitable[VerifiedMutationStepResult] | VerifiedMutationStepResult,
]
MutationExecutionValidator = Callable[..., Awaitable[None] | None]
AfterStepEffect = Callable[[MutationStepContext], Any]
DELETE_PHASE_CHECKPOINT_KEY = "delete_phase"
DELETE_PHASE_PREPARED = "prepared"
DELETE_PHASE_PURGING = "purging"
DELETE_PHASE_PURGE_FAILED = "purge_failed"
DELETE_PHASE_COMPLETED = "completed"


@dataclass(frozen=True, slots=True)
class MutationExecutionCompleted:
    """The Knowledge mutation is already durably complete."""


@dataclass(frozen=True, slots=True)
class MutationExecutionDispatch:
    """A Knowledge-owned generation that durable workers must continue."""

    execution_token: str
    deadline: datetime


class KnowledgeSpaceMutationExecutor:
    """Durable F046 upload/rename/move mutation executor.

    Formal Knowledge rows, their request link and the four durable steps share
    one DB commit. OpenFGA and parser dispatch only start after that commit.
    For uploads, successful OpenFGA writes plus scheduler acceptance complete
    the Knowledge-owned business handoff; parsing/indexing/vectorization then
    follow the ordinary file lifecycle. Rename/move external steps only accept
    read-after-verified results; absent a runner they remain pending, and the
    user-visible DB name/location is cut over last.
    """

    def __init__(
        self,
        *,
        session_factory: SessionFactory = get_async_db_session,
        authorize_file: UploadSideEffect | None = None,
        dispatch_parse: UploadSideEffect | None = None,
        execution_token_factory: Callable[[], str] | None = None,
        deadline_factory: Callable[[], datetime] | None = None,
        mutation_repository_factory: Callable[[AsyncSession], Any] | None = None,
        execution_validator: UploadExecutionValidator | None = None,
        mutation_execution_validator: MutationExecutionValidator | None = None,
        mutation_step_applier: MutationStepEffect | None = None,
        mutation_step_compensator: MutationStepEffect | None = None,
        mutation_step_owner: MutationStepOwner | None = None,
        after_step_effect: AfterStepEffect | None = None,
        delete_purge_applier: MutationStepEffect | None = None,
    ) -> None:
        self.session_factory = session_factory
        self.authorize_file = authorize_file or self._authorize_file
        self.dispatch_parse = dispatch_parse or self._dispatch_parse
        self.execution_token_factory = execution_token_factory or (lambda: str(uuid4()))
        self.deadline_factory = deadline_factory or (lambda: datetime.now(UTC) + timedelta(hours=24))
        self.mutation_repository_factory = mutation_repository_factory or KnowledgeSpaceMutationRepository
        self.execution_validator = execution_validator or self._validate_upload_execution
        self.mutation_execution_validator = mutation_execution_validator or self._validate_non_upload_execution
        self.mutation_step_applier = mutation_step_applier
        self.mutation_step_compensator = mutation_step_compensator
        self.mutation_step_owner = mutation_step_owner or ProductionMutationStepOwner()
        self.after_step_effect = after_step_effect
        self.delete_purge_applier = delete_purge_applier or self._apply_delete_purge_step

    async def execute(
        self,
        *,
        request_id: int,
    ) -> MutationExecutionCompleted | MutationExecutionDispatch:
        tenant_id = self._tenant_id()
        async with self.session_factory() as session:
            request = await KnowledgeSpaceFileChangeRequestRepository(session).get_by_id(
                tenant_id=tenant_id,
                request_id=int(request_id),
            )
        if request is None:
            raise LookupError(f"F046 request not found: {request_id}")
        action = request.action
        payload_snapshot = {
            **dict(request.action_snapshot or {}),
            "action": str(request.action),
            "change_request_id": int(request.id),
            "space_id": int(request.space_id),
            "applicant_user_name": str(request.applicant_user_id),
        }
        if action == KnowledgeSpaceFileChangeAction.UPLOAD:
            return await self._execute_upload(
                request_id=request_id,
                payload_snapshot=payload_snapshot,
            )
        if action in {
            KnowledgeSpaceFileChangeAction.RENAME,
            KnowledgeSpaceFileChangeAction.MOVE,
        }:
            return await self._execute_rename_or_move(
                request_id=request_id,
                payload_snapshot=payload_snapshot,
            )
        if action == KnowledgeSpaceFileChangeAction.DELETE:
            return await self._execute_delete_prepare(
                request_id=request_id,
                payload_snapshot=payload_snapshot,
            )
        raise NotImplementedError(f"F046 executor does not yet support action={action}")

    async def prepare_execution(
        self,
        *,
        request_id: int,
    ) -> MutationExecutionCompleted | MutationExecutionDispatch:
        """Persist the current generation without running external step effects."""

        tenant_id = self._tenant_id()
        async with self.session_factory() as session:
            request = await KnowledgeSpaceFileChangeRequestRepository(session).get_by_id(
                tenant_id=tenant_id,
                request_id=int(request_id),
            )
        if request is None:
            raise LookupError(f"F046 request not found: {request_id}")
        payload_snapshot = {
            **dict(request.action_snapshot or {}),
            "action": str(request.action),
            "change_request_id": int(request.id),
            "space_id": int(request.space_id),
            "applicant_user_name": str(request.applicant_user_id),
        }
        if request.action == KnowledgeSpaceFileChangeAction.UPLOAD:
            return await self._execute_upload(
                request_id=request_id,
                payload_snapshot=payload_snapshot,
                dispatch_after_commit=False,
            )
        if request.action in {
            KnowledgeSpaceFileChangeAction.RENAME,
            KnowledgeSpaceFileChangeAction.MOVE,
        }:
            return await self._execute_rename_or_move(
                request_id=request_id,
                payload_snapshot=payload_snapshot,
            )
        if request.action == KnowledgeSpaceFileChangeAction.DELETE:
            return await self._execute_delete_prepare(
                request_id=request_id,
                payload_snapshot=payload_snapshot,
            )
        raise NotImplementedError(f"F046 executor does not yet support action={request.action}")

    async def fail_unstarted_request(self, *, request_id: int, failure_reason: str) -> bool:
        """Terminally fail a request that never began applying.

        Used when coordination hits a *permanent* error (e.g. the approved
        applicant no longer holds the strict permission required to apply the
        change) before any step ran. Without this the request would sit in
        ``queued`` forever: the one-shot coordinate dispatch merely exhausts its
        retries, and neither the watchdog nor the compensation scan re-drive a
        ``queued`` request (both only look at ``applying``/``compensating`` rows
        that already have step records). Moving it to ``failed`` surfaces the
        error and lets the client stop showing 等待执行. Only ``not_started`` /
        ``queued`` rows are affected; an already in-flight request is left to its
        own token-bound recovery path.
        """
        tenant_id = self._tenant_id()
        async with self.session_factory() as session:
            async with session.begin():
                request_repository = KnowledgeSpaceFileChangeRequestRepository(session)
                request = await request_repository.get_by_id(
                    tenant_id=tenant_id,
                    request_id=int(request_id),
                    for_update=True,
                )
                if request is None:
                    return False
                if request.execution_state not in {
                    KnowledgeSpaceFileChangeExecutionState.NOT_STARTED,
                    KnowledgeSpaceFileChangeExecutionState.QUEUED,
                }:
                    return False
                checkpoint = dict(request.execution_checkpoint or {})
                checkpoint["failure_reason"] = str(failure_reason)[:1000]
                request.execution_checkpoint = checkpoint
                request.execution_state = KnowledgeSpaceFileChangeExecutionState.FAILED
                await request_repository.save(request)
        return True

    async def _execute_upload(
        self,
        *,
        request_id: int,
        payload_snapshot: dict,
        dispatch_after_commit: bool = True,
    ) -> MutationExecutionCompleted | MutationExecutionDispatch:
        tenant_id = self._tenant_id()
        dispatch_context: UploadStepDispatchContext | None = None
        async with self.session_factory() as session:
            async with session.begin():
                request_repository = KnowledgeSpaceFileChangeRequestRepository(session)
                request = await request_repository.get_by_id(
                    tenant_id=tenant_id,
                    request_id=int(request_id),
                    for_update=True,
                )
                if request is None:
                    raise LookupError(f"F046 request not found: {request_id}")
                self._validate_upload_request(request=request)
                if request.execution_state == KnowledgeSpaceFileChangeExecutionState.APPLIED:
                    return MutationExecutionCompleted()
                if request.execution_state == KnowledgeSpaceFileChangeExecutionState.FAILED:
                    raise RuntimeError("failed F046 upload requires the token-bound resume path")

                token = request.execution_token or self.execution_token_factory()
                if len(token) > 64 or not token:
                    raise ValueError("F046 execution token must contain 1 to 64 characters")
                mutation_repository = self.mutation_repository_factory(session)
                space = await mutation_repository.lock_space(
                    tenant_id=tenant_id,
                    space_id=int(request.space_id),
                )
                if space is None:
                    raise LookupError(f"F046 target knowledge space not found: {request.space_id}")
                if request.executed_resource_id is None:
                    stage = await mutation_repository.get_upload_stage(
                        tenant_id=tenant_id,
                        upload_stage_id=int(request.upload_stage_id or 0),
                        for_update=True,
                    )
                    if stage is None:
                        raise LookupError(f"F046 upload stage not found for request: {request_id}")
                    validation_result = self.execution_validator(
                        session=session,
                        mutation_repository=mutation_repository,
                        request=request,
                        stage=stage,
                        space=space,
                        payload_snapshot=payload_snapshot,
                    )
                    if isawaitable(validation_result):
                        await validation_result
                    from bisheng.knowledge.domain.services.knowledge_space_service import KnowledgeSpaceService

                    bundle = await KnowledgeSpaceService.add_file_in_uow(
                        session=session,
                        request=request,
                        stage=stage,
                        applicant_user_name=str(payload_snapshot.get("applicant_user_name") or ""),
                        mutation_repository=mutation_repository,
                    )
                    request.executed_resource_id = int(bundle.file.id)
                    request.execution_checkpoint = self._build_upload_checkpoint(
                        request=request,
                        file=bundle.file,
                        created_folders=bundle.created_folders,
                        deadline=self.deadline_factory(),
                    )
                else:
                    bundle_file = await mutation_repository.get_formal_file(
                        tenant_id=tenant_id,
                        space_id=int(request.space_id),
                        file_id=int(request.executed_resource_id),
                        for_update=True,
                    )
                    if bundle_file is None:
                        raise RuntimeError("F046 request points to a missing formal file")

                request.execution_token = token
                request.execution_state = KnowledgeSpaceFileChangeExecutionState.APPLYING
                await request_repository.save(request)
                steps = await KnowledgeSpaceFileChangeExecutionStepRepository(session).ensure_steps(
                    tenant_id=tenant_id,
                    request_id=int(request.id),
                    attempt_token=token,
                    step_codes=UploadExecutionStepCode.ALL,
                )
                step_map = {step.step_code: step for step in steps}
                file_id = int(request.executed_resource_id)
                file_name = str(request.file_name or payload_snapshot.get("business_name") or file_id)
                dispatch_context = UploadStepDispatchContext(
                    tenant_id=tenant_id,
                    request_id=int(request.id),
                    execution_token=token,
                    step_code="",
                    idempotency_key="",
                    file_id=file_id,
                    file_name=file_name,
                    applicant_user_id=int(request.applicant_user_id),
                    space_id=int(request.space_id),
                    checkpoint=dict(request.execution_checkpoint or {}),
                )
                deadline = self._checkpoint_deadline(request.execution_checkpoint)
                # Keep these reads inside the transaction so no side effect can
                # race ahead of the formal graph/request/step commit.
                dispatch_states = {
                    code: (step_map[code].state, step_map[code].idempotency_key)
                    for code in (UploadExecutionStepCode.FGA, UploadExecutionStepCode.PARSE)
                }

        if dispatch_context is None:
            raise RuntimeError("F046 upload transaction did not produce a dispatch context")
        if dispatch_after_commit:
            try:
                await self._dispatch_after_commit(dispatch_context, dispatch_states)
            except Exception as exc:
                await self._mark_upload_attempt_failed(
                    tenant_id=dispatch_context.tenant_id,
                    request_id=dispatch_context.request_id,
                    execution_token=dispatch_context.execution_token,
                    error_summary=str(exc),
                )
                raise
        return MutationExecutionDispatch(execution_token=dispatch_context.execution_token, deadline=deadline)

    async def _execute_rename_or_move(
        self,
        *,
        request_id: int,
        payload_snapshot: dict,
    ) -> MutationExecutionCompleted | MutationExecutionDispatch:
        tenant_id = self._tenant_id()
        context: MutationStepContext | None = None
        deadline: datetime | None = None
        external_steps: tuple[str, ...] = ()
        all_steps: tuple[str, ...] = ()
        step_states: dict[str, tuple[str, str]] = {}

        async with self.session_factory() as session:
            async with session.begin():
                request_repository = KnowledgeSpaceFileChangeRequestRepository(session)
                request = await request_repository.get_by_id(
                    tenant_id=tenant_id,
                    request_id=int(request_id),
                    for_update=True,
                )
                if request is None:
                    raise LookupError(f"F046 request not found: {request_id}")
                self._validate_non_upload_request(request=request)
                if request.execution_state == KnowledgeSpaceFileChangeExecutionState.APPLIED:
                    return MutationExecutionCompleted()
                if request.execution_state in {
                    KnowledgeSpaceFileChangeExecutionState.FAILED,
                    KnowledgeSpaceFileChangeExecutionState.COMPENSATING,
                }:
                    raise RuntimeError("failed F046 mutation requires the token-bound resume path")

                token = request.execution_token or self.execution_token_factory()
                if not token or len(token) > 64:
                    raise ValueError("F046 execution token must contain 1 to 64 characters")
                mutation_repository = self.mutation_repository_factory(session)
                manifest = (request.execution_checkpoint or {}).get("mutation_manifest")
                if manifest is None:
                    manifest = await self._build_non_upload_manifest(
                        mutation_repository=mutation_repository,
                        request=request,
                    )
                    validation_result = self.mutation_execution_validator(
                        session=session,
                        mutation_repository=mutation_repository,
                        request=request,
                        manifest=manifest,
                        payload_snapshot=payload_snapshot,
                    )
                    if isawaitable(validation_result):
                        await validation_result
                    deadline = self.deadline_factory()
                    checkpoint = dict(request.execution_checkpoint or {})
                    checkpoint.update(
                        {
                            "deadline": deadline.isoformat(),
                            "mutation_manifest": manifest,
                            "failure_reason": None,
                        }
                    )
                    request.execution_checkpoint = checkpoint
                else:
                    await mutation_repository.validate_manifest_current(
                        tenant_id=tenant_id,
                        manifest=manifest,
                    )
                    deadline = self._checkpoint_deadline(request.execution_checkpoint)

                if request.action == KnowledgeSpaceFileChangeAction.RENAME:
                    external_steps = RenameExecutionStepCode.EXTERNAL
                    all_steps = RenameExecutionStepCode.ALL
                else:
                    external_steps = MoveExecutionStepCode.EXTERNAL
                    all_steps = MoveExecutionStepCode.ALL
                steps = await KnowledgeSpaceFileChangeExecutionStepRepository(session).ensure_steps(
                    tenant_id=tenant_id,
                    request_id=int(request.id),
                    attempt_token=token,
                    step_codes=all_steps,
                )
                if any(
                    step.state
                    in {
                        KnowledgeSpaceFileChangeExecutionStepState.COMPENSATING,
                        KnowledgeSpaceFileChangeExecutionStepState.COMPENSATED,
                    }
                    for step in steps
                ):
                    raise RuntimeError("compensated F046 mutation requires the token-bound resume path")
                request.execution_token = token
                request.execution_state = KnowledgeSpaceFileChangeExecutionState.APPLYING
                await request_repository.save(request)
                step_states = {step.step_code: (str(step.state), str(step.idempotency_key)) for step in steps}
                root = manifest["root"]
                context = MutationStepContext(
                    tenant_id=tenant_id,
                    request_id=int(request.id),
                    execution_token=str(token),
                    action=str(request.action),
                    step_code="",
                    idempotency_key="",
                    resource_type=str(request.resource_type),
                    resource_id=int(request.resource_id),
                    applicant_user_id=int(request.applicant_user_id),
                    source_space_id=int(request.space_id),
                    target_space_id=(
                        int(request.target_space_id)
                        if request.target_space_id is not None
                        else int(root["old_space_id"])
                    ),
                    manifest=dict(manifest),
                )

        if context is None or deadline is None:
            raise RuntimeError("F046 mutation preparation did not produce an execution context")
        if self.mutation_step_applier is None:
            return MutationExecutionDispatch(execution_token=context.execution_token, deadline=deadline)

        active_step: str | None = None
        try:
            for step_code in external_steps:
                state, idempotency_key = step_states[step_code]
                if state == KnowledgeSpaceFileChangeExecutionStepState.SUCCEEDED:
                    continue
                active_step = step_code
                step_context = self._mutation_step_context(context, step_code, idempotency_key)
                async with self.session_factory() as session:
                    async with session.begin():
                        marked = await KnowledgeSpaceFileChangeExecutionStepRepository(session).mark_dispatched(
                            tenant_id=context.tenant_id,
                            request_id=context.request_id,
                            step_code=step_code,
                            attempt_token=context.execution_token,
                            task_id=None,
                        )
                        if not marked:
                            raise RuntimeError("stale F046 mutation step dispatch")
                result = await self._invoke_verified_mutation_effect(self.mutation_step_applier, step_context)
                if self.after_step_effect is not None:
                    callback_result = self.after_step_effect(step_context)
                    if isawaitable(callback_result):
                        await callback_result
                async with self.session_factory() as session:
                    async with session.begin():
                        marked = await KnowledgeSpaceFileChangeExecutionStepRepository(session).mark_succeeded(
                            tenant_id=context.tenant_id,
                            request_id=context.request_id,
                            step_code=step_code,
                            attempt_token=context.execution_token,
                            result_digest=result.result_digest,
                        )
                        if not marked:
                            raise RuntimeError("stale F046 mutation step acknowledgement")
                step_states[step_code] = (
                    KnowledgeSpaceFileChangeExecutionStepState.SUCCEEDED,
                    idempotency_key,
                )

            await self._cutover_non_upload_mutation(
                context=context,
                all_steps=all_steps,
                external_steps=external_steps,
                payload_snapshot=payload_snapshot,
            )
            return MutationExecutionCompleted()
        except Exception as exc:
            if active_step is not None:
                await self._mark_mutation_step_failed(
                    context=context,
                    step_code=active_step,
                    error_summary=str(exc),
                )
            try:
                await self._compensate_non_upload_mutation(
                    context=context,
                    external_steps=external_steps,
                )
            except Exception as compensation_error:
                await self._mark_non_upload_attempt_failed(
                    context=context,
                    error_summary=f"{exc}; compensation failed: {compensation_error}",
                )
                raise compensation_error from exc
            await self._mark_non_upload_attempt_failed(
                context=context,
                error_summary=str(exc),
            )
            raise

    async def _execute_delete_prepare(
        self,
        *,
        request_id: int,
        payload_snapshot: dict,
    ) -> MutationExecutionCompleted | MutationExecutionDispatch:
        """Persist a complete delete manifest without destructive side effects."""

        tenant_id = self._tenant_id()
        async with self.session_factory() as session:
            async with session.begin():
                request_repository = KnowledgeSpaceFileChangeRequestRepository(session)
                request = await request_repository.get_by_id(
                    tenant_id=tenant_id,
                    request_id=int(request_id),
                    for_update=True,
                )
                if request is None:
                    raise LookupError(f"F046 request not found: {request_id}")
                self._validate_non_upload_request(request=request)
                if request.execution_state == KnowledgeSpaceFileChangeExecutionState.APPLIED:
                    return MutationExecutionCompleted()
                if request.execution_state in {
                    KnowledgeSpaceFileChangeExecutionState.FAILED,
                    KnowledgeSpaceFileChangeExecutionState.COMPENSATING,
                }:
                    raise RuntimeError("failed F046 delete requires the token-bound resume path")
                token = request.execution_token or self.execution_token_factory()
                if not token or len(token) > 64:
                    raise ValueError("F046 execution token must contain 1 to 64 characters")

                mutation_repository = self.mutation_repository_factory(session)
                checkpoint = dict(request.execution_checkpoint or {})
                manifest = checkpoint.get("delete_manifest")
                if manifest is None:
                    snapshot = dict(request.action_snapshot or {})
                    manifest = await mutation_repository.build_delete_manifest(
                        tenant_id=tenant_id,
                        space_id=int(request.space_id),
                        resource_id=int(request.resource_id),
                        resource_type=str(request.resource_type),
                        source_name=snapshot.get("old_name", request.file_name),
                        source_path=snapshot.get("old_path", snapshot.get("source_path")),
                        source_level=snapshot.get("old_level", snapshot.get("source_level")),
                    )
                    validation_result = self.mutation_execution_validator(
                        session=session,
                        mutation_repository=mutation_repository,
                        request=request,
                        manifest=manifest,
                        payload_snapshot=payload_snapshot,
                    )
                    if isawaitable(validation_result):
                        await validation_result
                    deadline = self.deadline_factory()
                    checkpoint.update(
                        {
                            "deadline": deadline.isoformat(),
                            "delete_manifest": manifest,
                            "delete_validation_snapshot": {
                                "action": KnowledgeSpaceFileChangeAction.DELETE,
                                "applicant_user_name": str(
                                    payload_snapshot.get("applicant_user_name") or request.applicant_user_id
                                ),
                            },
                            DELETE_PHASE_CHECKPOINT_KEY: DELETE_PHASE_PREPARED,
                            "failure_reason": None,
                        }
                    )
                    request.execution_checkpoint = checkpoint
                else:
                    await mutation_repository.validate_delete_manifest_current(
                        tenant_id=tenant_id,
                        manifest=manifest,
                    )
                    deadline = self._checkpoint_deadline(checkpoint)

                request.execution_token = str(token)
                request.execution_state = KnowledgeSpaceFileChangeExecutionState.APPLYING
                await request_repository.save(request)
                step_repository = KnowledgeSpaceFileChangeExecutionStepRepository(session)
                steps = await step_repository.ensure_steps(
                    tenant_id=tenant_id,
                    request_id=int(request.id),
                    attempt_token=str(token),
                    step_codes=DeleteExecutionStepCode.ALL,
                )
                prepare_step = next(step for step in steps if step.step_code == DeleteExecutionStepCode.PREPARE)
                if prepare_step.state != KnowledgeSpaceFileChangeExecutionStepState.SUCCEEDED:
                    marked = await step_repository.mark_succeeded(
                        tenant_id=tenant_id,
                        request_id=int(request.id),
                        step_code=DeleteExecutionStepCode.PREPARE,
                        attempt_token=str(token),
                        result_digest=f"manifest:v{manifest.get('version', 1)}:{len(manifest.get('rows', []))}",
                    )
                    if not marked:
                        raise RuntimeError("stale F046 delete prepare acknowledgement")
        return MutationExecutionDispatch(execution_token=str(token), deadline=deadline)

    async def cutover_delete(
        self,
        *,
        request_id: int,
        execution_token: str,
    ) -> bool:
        """Atomically apply the Knowledge logical deletion cutover."""

        tenant_id = self._tenant_id()
        async with self.session_factory() as session:
            async with session.begin():
                request_repository = KnowledgeSpaceFileChangeRequestRepository(session)
                observed = await request_repository.get_by_id(
                    tenant_id=tenant_id,
                    request_id=int(request_id),
                    for_update=False,
                )
                if observed is None:
                    raise LookupError(f"F046 delete request not found: {request_id}")
                if observed.execution_state == KnowledgeSpaceFileChangeExecutionState.APPLIED:
                    return True
                if observed.action != KnowledgeSpaceFileChangeAction.DELETE:
                    raise ValueError("F046 delete cutover received a non-delete request")
                if observed.execution_token != str(execution_token):
                    raise RuntimeError("stale F046 delete cutover attempt")

                request = await request_repository.get_by_id(
                    tenant_id=tenant_id,
                    request_id=int(request_id),
                    for_update=True,
                )
                if (
                    request is None
                    or request.action != KnowledgeSpaceFileChangeAction.DELETE
                    or request.execution_state != KnowledgeSpaceFileChangeExecutionState.APPLYING
                    or request.execution_token != str(execution_token)
                ):
                    raise RuntimeError("stale F046 delete cutover attempt")
                checkpoint = dict(request.execution_checkpoint or {})
                if checkpoint.get(DELETE_PHASE_CHECKPOINT_KEY) == DELETE_PHASE_PURGING and bool(
                    checkpoint.get("deletion_cutover_active")
                ):
                    return True
                manifest = checkpoint.get("delete_manifest")
                if not isinstance(manifest, dict):
                    raise RuntimeError("F046 delete cutover requires a durable manifest")
                mutation_repository = self.mutation_repository_factory(session)
                validation_result = self.mutation_execution_validator(
                    session=session,
                    mutation_repository=mutation_repository,
                    request=request,
                    manifest=manifest,
                    payload_snapshot=dict(checkpoint.get("delete_validation_snapshot") or {}),
                )
                if isawaitable(validation_result):
                    await validation_result

                step_repository = KnowledgeSpaceFileChangeExecutionStepRepository(session)
                steps = await step_repository.list_by_request(
                    tenant_id=tenant_id,
                    request_id=int(request_id),
                    for_update=True,
                )
                by_code = {step.step_code: step for step in steps}
                prepare_step = by_code.get(DeleteExecutionStepCode.PREPARE)
                if (
                    prepare_step is None
                    or prepare_step.state != KnowledgeSpaceFileChangeExecutionStepState.SUCCEEDED
                    or prepare_step.attempt_token != str(execution_token)
                ):
                    raise RuntimeError("F046 delete cutover requires current verified prepare")
                await mutation_repository.apply_delete_cutover(
                    tenant_id=tenant_id,
                    manifest=manifest,
                )
                marked = await step_repository.mark_succeeded(
                    tenant_id=tenant_id,
                    request_id=int(request_id),
                    step_code=DeleteExecutionStepCode.DB_CUTOVER,
                    attempt_token=str(execution_token),
                    result_digest=f"cutover:delete:{int(request.resource_id)}",
                )
                if not marked:
                    raise RuntimeError("stale F046 delete cutover acknowledgement")
                from bisheng.knowledge.domain.services.knowledge_space_deletion_guard import (
                    DELETION_CUTOVER_ACTIVE_CHECKPOINT_KEY,
                )

                checkpoint[DELETION_CUTOVER_ACTIVE_CHECKPOINT_KEY] = True
                checkpoint[DELETE_PHASE_CHECKPOINT_KEY] = DELETE_PHASE_PURGING
                checkpoint["cutover_completed_at"] = datetime.now(UTC).isoformat()
                checkpoint.pop("failure_reason", None)
                request.execution_checkpoint = checkpoint
                request.execution_state = KnowledgeSpaceFileChangeExecutionState.APPLYING
                await request_repository.save(request)
        return True

    async def purge_delete(self, *, request_id: int, execution_token: str) -> bool:
        """Idempotently purge post-cutover FGA/object/index/vector residue."""

        if self.delete_purge_applier is None:
            return False
        tenant_id = self._tenant_id()
        async with self.session_factory() as session:
            request = await KnowledgeSpaceFileChangeRequestRepository(session).get_by_id(
                tenant_id=tenant_id,
                request_id=int(request_id),
                for_update=False,
            )
            checkpoint = dict(request.execution_checkpoint or {}) if request is not None else {}
            if (
                request is None
                or request.action != KnowledgeSpaceFileChangeAction.DELETE
                or request.execution_state != KnowledgeSpaceFileChangeExecutionState.APPLYING
                or checkpoint.get(DELETE_PHASE_CHECKPOINT_KEY) != DELETE_PHASE_PURGING
                or not bool(checkpoint.get("deletion_cutover_active"))
            ):
                raise RuntimeError("F046 delete purge requires a cut-over delete")
            if request.execution_token != str(execution_token):
                raise RuntimeError("stale F046 delete purge attempt")
            manifest = checkpoint.get("delete_manifest")
            if not isinstance(manifest, dict):
                raise RuntimeError("F046 delete purge requires a durable manifest")
            context = MutationStepContext(
                tenant_id=tenant_id,
                request_id=int(request.id),
                execution_token=str(execution_token),
                action=KnowledgeSpaceFileChangeAction.DELETE,
                step_code="",
                idempotency_key="",
                resource_type=str(request.resource_type),
                resource_id=int(request.resource_id),
                applicant_user_id=int(request.applicant_user_id),
                source_space_id=int(request.space_id),
                target_space_id=None,
                manifest=dict(manifest),
            )

        for step_code in DeleteExecutionStepCode.PURGE:
            async with self.session_factory() as session:
                async with session.begin():
                    step_repository = KnowledgeSpaceFileChangeExecutionStepRepository(session)
                    step = await step_repository.lock_step(
                        tenant_id=tenant_id,
                        request_id=int(request_id),
                        step_code=step_code,
                    )
                    if step is None or step.attempt_token != str(execution_token):
                        raise RuntimeError("stale F046 delete purge step")
                    if step.state == KnowledgeSpaceFileChangeExecutionStepState.SUCCEEDED:
                        continue
                    marked = await step_repository.mark_dispatched(
                        tenant_id=tenant_id,
                        request_id=int(request_id),
                        step_code=step_code,
                        attempt_token=str(execution_token),
                        task_id=None,
                    )
                    if not marked:
                        raise RuntimeError("stale F046 delete purge dispatch")
                    idempotency_key = str(step.idempotency_key)
            step_context = self._mutation_step_context(context, step_code, idempotency_key)
            try:
                result = await self._invoke_verified_mutation_effect(
                    self.delete_purge_applier,
                    step_context,
                )
            except Exception as error:
                await self._mark_mutation_step_failed(
                    context=context,
                    step_code=step_code,
                    error_summary=str(error),
                )
                await self._record_delete_purge_failure(context=context, error_summary=str(error))
                raise
            async with self.session_factory() as session:
                async with session.begin():
                    marked = await KnowledgeSpaceFileChangeExecutionStepRepository(session).mark_succeeded(
                        tenant_id=tenant_id,
                        request_id=int(request_id),
                        step_code=step_code,
                        attempt_token=str(execution_token),
                        result_digest=result.result_digest,
                    )
                    if not marked:
                        raise RuntimeError("stale F046 delete purge acknowledgement")

        return await self.finalize_delete_execution(
            request_id=int(request_id),
            execution_token=str(execution_token),
        )

    async def _record_delete_purge_failure(
        self,
        *,
        context: MutationStepContext,
        error_summary: str,
    ) -> None:
        async with self.session_factory() as session:
            async with session.begin():
                repository = KnowledgeSpaceFileChangeRequestRepository(session)
                request = await repository.get_by_id(
                    tenant_id=context.tenant_id,
                    request_id=context.request_id,
                    for_update=True,
                )
                if request is None or request.execution_state != KnowledgeSpaceFileChangeExecutionState.APPLYING:
                    raise RuntimeError("stale F046 delete purge failure")
                checkpoint = dict(request.execution_checkpoint or {})
                checkpoint["purge_failure_reason"] = str(error_summary)[:1000]
                checkpoint["failure_reason"] = str(error_summary)[:1000]
                checkpoint[DELETE_PHASE_CHECKPOINT_KEY] = DELETE_PHASE_PURGE_FAILED
                request.execution_checkpoint = checkpoint
                request.execution_state = KnowledgeSpaceFileChangeExecutionState.FAILED
                await repository.save(request)

    async def finalize_delete_execution(
        self,
        *,
        request_id: int,
        execution_token: str,
    ) -> bool:
        """Publish Knowledge success only after every purge is verified."""

        tenant_id = self._tenant_id()
        async with self.session_factory() as session:
            async with session.begin():
                request_repository = KnowledgeSpaceFileChangeRequestRepository(session)
                request = await request_repository.get_by_id(
                    tenant_id=tenant_id,
                    request_id=int(request_id),
                    for_update=True,
                )
                if request is None:
                    raise RuntimeError("stale F046 delete finalization")
                if request.execution_state == KnowledgeSpaceFileChangeExecutionState.APPLIED:
                    return True
                checkpoint = dict(request.execution_checkpoint or {})
                if (
                    request.action != KnowledgeSpaceFileChangeAction.DELETE
                    or request.execution_state != KnowledgeSpaceFileChangeExecutionState.APPLYING
                    or request.execution_token != str(execution_token)
                    or checkpoint.get(DELETE_PHASE_CHECKPOINT_KEY) != DELETE_PHASE_PURGING
                    or not bool(checkpoint.get("deletion_cutover_active"))
                ):
                    raise RuntimeError("F046 delete finalization requires a cut-over delete")

                from bisheng.knowledge.domain.repositories.knowledge_space_file_change_footprint_repository import (
                    KnowledgeSpaceFileChangeFootprintRepository,
                )
                from bisheng.knowledge.domain.services.knowledge_space_deletion_guard import (
                    DELETION_CUTOVER_ACTIVE_CHECKPOINT_KEY,
                )

                # Retire before step locks to preserve request -> footprint ->
                # step order. Any failed verification rolls this delete back.
                await KnowledgeSpaceFileChangeFootprintRepository(session).retire_delete_guard(
                    tenant_id=tenant_id,
                    request_id=int(request_id),
                )
                steps = await KnowledgeSpaceFileChangeExecutionStepRepository(session).list_by_request(
                    tenant_id=tenant_id,
                    request_id=int(request_id),
                    for_update=True,
                )
                by_code = {step.step_code: step for step in steps}
                if any(
                    by_code.get(step_code) is None
                    or by_code[step_code].state != KnowledgeSpaceFileChangeExecutionStepState.SUCCEEDED
                    or by_code[step_code].attempt_token != str(execution_token)
                    for step_code in DeleteExecutionStepCode.ALL
                ):
                    raise RuntimeError("F046 delete finalization requires every verified current-generation step")

                checkpoint[DELETION_CUTOVER_ACTIVE_CHECKPOINT_KEY] = False
                checkpoint[DELETE_PHASE_CHECKPOINT_KEY] = DELETE_PHASE_COMPLETED
                checkpoint["purge_completed_at"] = datetime.now(UTC).isoformat()
                checkpoint.pop("purge_failure_reason", None)
                checkpoint.pop("failure_reason", None)
                request.execution_checkpoint = checkpoint
                request.execution_state = KnowledgeSpaceFileChangeExecutionState.APPLIED
                await request_repository.save(request)
        return True

    @staticmethod
    async def _apply_delete_purge_step(context: MutationStepContext) -> VerifiedMutationStepResult:
        """Run one authoritative, idempotent post-cutover cleanup step."""

        manifest = context.manifest
        file_ids = sorted({int(file_id) for file_id in manifest.get("file_ids", [])})
        if context.step_code == DeleteExecutionStepCode.FGA:
            from bisheng.permission.domain.services.owner_service import OwnerService

            deleted_count = 0
            for resource in manifest.get("fga_resources", []):
                deleted_count += await OwnerService.delete_resource_tuples_strict(
                    str(resource["resource_type"]),
                    str(resource["resource_id"]),
                )
            return VerifiedMutationStepResult(result_digest=f"fga:verified:{deleted_count}")

        if context.step_code == DeleteExecutionStepCode.MINIO:
            from bisheng.core.storage.minio.minio_manager import get_minio_storage

            storage = await get_minio_storage()
            object_names = sorted({str(name) for name in manifest.get("object_names", []) if name})
            for object_name in object_names:
                await storage.remove_object(bucket_name=storage.bucket, object_name=object_name)
                if await storage.object_exists(bucket_name=storage.bucket, object_name=object_name):
                    raise RuntimeError("F046 MinIO purge verification found object residue")
            return VerifiedMutationStepResult(result_digest=f"minio:verified:{len(object_names)}")

        from bisheng.knowledge.domain.knowledge_rag import KnowledgeRag
        from bisheng.knowledge.domain.models.knowledge import KnowledgeDao

        knowledge = await asyncio.to_thread(KnowledgeDao.query_by_id, int(context.source_space_id))
        if knowledge is None:
            raise RuntimeError("F046 delete purge knowledge space no longer exists")
        if context.step_code == DeleteExecutionStepCode.ES:
            es_client = await asyncio.to_thread(
                KnowledgeRag.init_knowledge_es_vectorstore_sync,
                knowledge=knowledge,
            )
            exists = await asyncio.to_thread(
                es_client.client.indices.exists,
                index=knowledge.index_name,
            )
            deleted = 0
            if exists and file_ids:
                response = await asyncio.to_thread(
                    es_client.client.delete_by_query,
                    index=knowledge.index_name,
                    query={"terms": {"metadata.document_id": file_ids}},
                )
                failures = response.get("failures") if isinstance(response, dict) else None
                if failures:
                    raise RuntimeError("F046 Elasticsearch purge returned shard failures")
                deleted = int(response.get("deleted", 0)) if isinstance(response, dict) else 0
                await asyncio.to_thread(es_client.client.indices.refresh, index=knowledge.index_name)
                remaining = await asyncio.to_thread(
                    ProductionMutationStepOwner._count_es_chunks,
                    es_client,
                    knowledge.index_name,
                    file_ids,
                )
                if remaining:
                    raise RuntimeError("F046 Elasticsearch purge verification found file residue")
            return VerifiedMutationStepResult(result_digest=f"es:verified:{deleted}")

        if context.step_code == DeleteExecutionStepCode.MILVUS:
            from bisheng.core.ai import FakeEmbeddings

            vector_client = await asyncio.to_thread(
                KnowledgeRag.init_knowledge_milvus_vectorstore_sync,
                0,
                knowledge=knowledge,
                embeddings=FakeEmbeddings(),
            )
            if vector_client.col and file_ids:
                await asyncio.to_thread(
                    vector_client.col.delete,
                    expr=f"document_id in {file_ids}",
                    timeout=10,
                )
                flush = getattr(vector_client.col, "flush", None)
                if flush is not None:
                    await asyncio.to_thread(flush)
                remaining = await asyncio.to_thread(
                    ProductionMutationStepOwner._count_milvus_chunks,
                    vector_client,
                    file_ids,
                )
                if remaining:
                    raise RuntimeError("F046 Milvus purge verification found file residue")
            return VerifiedMutationStepResult(result_digest=f"milvus:verified:{len(file_ids)}")
        raise ValueError(f"unsupported F046 delete purge step: {context.step_code}")

    async def _build_non_upload_manifest(self, *, mutation_repository, request) -> dict:
        snapshot = dict(request.action_snapshot or {})
        if request.action == KnowledgeSpaceFileChangeAction.RENAME:
            old_name = snapshot.get("old_name") or request.file_name
            new_name = snapshot.get("new_name") or snapshot.get("target_name")
            if not old_name or not new_name:
                raise ValueError("F046 rename snapshot requires old_name and new_name")
            await mutation_repository.lock_space(
                tenant_id=int(request.tenant_id),
                space_id=int(request.space_id),
            )
            return await mutation_repository.build_rename_manifest(
                tenant_id=int(request.tenant_id),
                space_id=int(request.space_id),
                resource_id=int(request.resource_id),
                resource_type=str(request.resource_type),
                old_name=str(old_name),
                new_name=str(new_name),
            )
        return await mutation_repository.build_move_manifest(
            tenant_id=int(request.tenant_id),
            source_space_id=int(request.space_id),
            target_space_id=int(request.target_space_id),
            target_parent_id=(int(request.target_parent_id) if request.target_parent_id is not None else None),
            resource_id=int(request.resource_id),
            resource_type=str(request.resource_type),
            source_path=snapshot.get("source_path", snapshot.get("old_path")),
            source_level=snapshot.get("source_level", snapshot.get("old_level")),
        )

    async def _cutover_non_upload_mutation(
        self,
        *,
        context: MutationStepContext,
        all_steps: tuple[str, ...],
        external_steps: tuple[str, ...],
        payload_snapshot: dict,
    ) -> None:
        cutover_step = all_steps[-1]
        prepared = False
        target_ready = False
        await self._set_mutation_transition(context=context, active=True, phase="old_view")
        try:
            # Owner prepare is crash-safe and may have written a new parent
            # before its read-after verification raises. Mark the rollback
            # obligation before entering it; rollback itself is idempotent.
            prepared = True
            self._owner_result_digest(await self.mutation_step_owner.prepare_cutover_and_verify(context))
            self._owner_result_digest(await self.mutation_step_owner.finalize_cutover_and_verify(context))
            target_ready = True
            async with self.session_factory() as session:
                async with session.begin():
                    request_repository = KnowledgeSpaceFileChangeRequestRepository(session)
                    request = await request_repository.get_by_id(
                        tenant_id=context.tenant_id,
                        request_id=context.request_id,
                        for_update=True,
                    )
                    if request is None or request.execution_token != context.execution_token:
                        raise RuntimeError("stale F046 mutation cutover attempt")
                    if request.execution_state == KnowledgeSpaceFileChangeExecutionState.APPLIED:
                        return
                    mutation_repository = self.mutation_repository_factory(session)
                    # The validator obtains source/target space and immutable
                    # resource locks. It must precede execution-step locks to
                    # preserve instance -> outbox -> request -> resource -> step.
                    validation_result = self.mutation_execution_validator(
                        session=session,
                        mutation_repository=mutation_repository,
                        request=request,
                        manifest=context.manifest,
                        payload_snapshot=payload_snapshot,
                    )
                    if isawaitable(validation_result):
                        await validation_result
                    step_repository = KnowledgeSpaceFileChangeExecutionStepRepository(session)
                    steps = await step_repository.list_by_request(
                        tenant_id=context.tenant_id,
                        request_id=context.request_id,
                        for_update=True,
                    )
                    by_code = {step.step_code: step for step in steps}
                    if any(
                        code not in by_code
                        or by_code[code].state != KnowledgeSpaceFileChangeExecutionStepState.SUCCEEDED
                        or (code.endswith(".verify") and by_code[code].attempt_token != context.execution_token)
                        for code in external_steps
                    ):
                        raise RuntimeError("F046 mutation cutover requires verified external steps")
                    cutover_row = by_code.get(cutover_step)
                    db_already_cutover = bool(
                        cutover_row is not None
                        and cutover_row.state == KnowledgeSpaceFileChangeExecutionStepState.SUCCEEDED
                    )
                    if db_already_cutover:
                        raise RuntimeError("F046 cutover step cannot be terminal while request remains APPLYING")
                    if context.action == KnowledgeSpaceFileChangeAction.RENAME:
                        await mutation_repository.apply_rename_cutover(
                            tenant_id=context.tenant_id,
                            manifest=context.manifest,
                            updater_user_id=context.applicant_user_id,
                            updater_user_name=str(
                                payload_snapshot.get("applicant_user_name") or context.applicant_user_id
                            ),
                        )
                    else:
                        await mutation_repository.apply_move_cutover(
                            tenant_id=context.tenant_id,
                            manifest=context.manifest,
                            updater_user_id=context.applicant_user_id,
                            updater_user_name=str(
                                payload_snapshot.get("applicant_user_name") or context.applicant_user_id
                            ),
                        )
                    marked = await step_repository.mark_succeeded(
                        tenant_id=context.tenant_id,
                        request_id=context.request_id,
                        step_code=cutover_step,
                        attempt_token=context.execution_token,
                        result_digest=f"cutover:{context.action}:{context.resource_id}",
                    )
                    if not marked:
                        raise RuntimeError("stale F046 mutation cutover acknowledgement")
                    checkpoint = dict(request.execution_checkpoint or {})
                    checkpoint["db_cutover_completed_at"] = datetime.now(UTC).isoformat()
                    from bisheng.knowledge.domain.services.knowledge_space_mutation_read_projection_service import (
                        MUTATION_TRANSITION_ACTIVE_CHECKPOINT_KEY,
                        MUTATION_TRANSITION_NEW_VIEW,
                        MUTATION_TRANSITION_PHASE_CHECKPOINT_KEY,
                    )

                    checkpoint[MUTATION_TRANSITION_ACTIVE_CHECKPOINT_KEY] = True
                    checkpoint[MUTATION_TRANSITION_PHASE_CHECKPOINT_KEY] = MUTATION_TRANSITION_NEW_VIEW
                    checkpoint.pop("failure_reason", None)
                    checkpoint["cutover_completed_at"] = datetime.now(UTC).isoformat()
                    request.execution_checkpoint = checkpoint
                    request.execution_state = KnowledgeSpaceFileChangeExecutionState.APPLIED
                    await request_repository.save(request)
        except Exception:
            commit_state = await self._read_mutation_cutover_commit_state(
                context=context,
            )
            if commit_state == "committed":
                await self._continue_post_cutover_cleanup(context)
                return
            if commit_state == "not_committed" and (prepared or target_ready):
                self._owner_result_digest(await self.mutation_step_owner.rollback_cutover_and_verify(context))
                await self._set_mutation_transition(context=context, active=False, phase="old_view")
            raise

        await self._continue_post_cutover_cleanup(context)

    async def _read_mutation_cutover_commit_state(
        self,
        *,
        context: MutationStepContext,
    ) -> str:
        """Resolve commit-ACK ambiguity without undoing a committed NEW_VIEW.

        ``unknown`` deliberately leaves OLD/NEW projection and dual-parent
        protection active so the durable token can be retried safely.
        """

        from bisheng.knowledge.domain.services.knowledge_space_mutation_read_projection_service import (
            MUTATION_TRANSITION_ACTIVE_CHECKPOINT_KEY,
            MUTATION_TRANSITION_NEW_VIEW,
            MUTATION_TRANSITION_OLD_VIEW,
            MUTATION_TRANSITION_PHASE_CHECKPOINT_KEY,
        )

        try:
            async with self.session_factory() as session:
                request = await KnowledgeSpaceFileChangeRequestRepository(session).get_by_id(
                    tenant_id=context.tenant_id,
                    request_id=context.request_id,
                )
                if request is None or request.execution_token != context.execution_token:
                    return "unknown"
                checkpoint = dict(request.execution_checkpoint or {})
                phase = str(checkpoint.get(MUTATION_TRANSITION_PHASE_CHECKPOINT_KEY) or MUTATION_TRANSITION_OLD_VIEW)
                if (
                    request.execution_state == KnowledgeSpaceFileChangeExecutionState.APPLIED
                    and phase == MUTATION_TRANSITION_NEW_VIEW
                    and checkpoint.get(MUTATION_TRANSITION_ACTIVE_CHECKPOINT_KEY) is True
                ):
                    await self.mutation_repository_factory(session).validate_manifest_applied(
                        tenant_id=context.tenant_id,
                        manifest=context.manifest,
                    )
                    return "committed"
                if (
                    request.execution_state == KnowledgeSpaceFileChangeExecutionState.APPLYING
                    and phase == MUTATION_TRANSITION_OLD_VIEW
                ):
                    return "not_committed"
                return "unknown"
        except Exception:
            return "unknown"

    async def _continue_post_cutover_cleanup(self, context: MutationStepContext) -> None:
        self._owner_result_digest(await self.mutation_step_owner.cleanup_cutover_and_verify(context))
        async with self.session_factory() as session:
            async with session.begin():
                request_repository = KnowledgeSpaceFileChangeRequestRepository(session)
                request = await request_repository.get_by_id(
                    tenant_id=context.tenant_id,
                    request_id=context.request_id,
                    for_update=True,
                )
                if request is None or request.execution_token != context.execution_token:
                    raise RuntimeError("stale F046 mutation finalization attempt")
                mutation_repository = self.mutation_repository_factory(session)
                await mutation_repository.validate_manifest_applied(
                    tenant_id=context.tenant_id,
                    manifest=context.manifest,
                )
                checkpoint = dict(request.execution_checkpoint or {})
                from bisheng.knowledge.domain.services.knowledge_space_mutation_read_projection_service import (
                    MUTATION_TRANSITION_ACTIVE_CHECKPOINT_KEY,
                )

                checkpoint[MUTATION_TRANSITION_ACTIVE_CHECKPOINT_KEY] = False
                checkpoint.pop("failure_reason", None)
                checkpoint["post_cutover_cleanup_completed_at"] = datetime.now(UTC).isoformat()
                request.execution_checkpoint = checkpoint
                request.execution_state = KnowledgeSpaceFileChangeExecutionState.APPLIED
                await request_repository.save(request)
                from bisheng.knowledge.domain.repositories.knowledge_space_file_change_footprint_repository import (
                    KnowledgeSpaceFileChangeFootprintRepository,
                )

                await KnowledgeSpaceFileChangeFootprintRepository(session).retire_mutation_projection(
                    tenant_id=context.tenant_id,
                    request_id=context.request_id,
                )

    async def _set_mutation_transition(self, *, context: MutationStepContext, active: bool, phase: str) -> None:
        from bisheng.knowledge.domain.repositories.knowledge_space_file_change_footprint_repository import (
            FootprintEntry,
            KnowledgeSpaceFileChangeFootprintRepository,
        )
        from bisheng.knowledge.domain.services.knowledge_space_mutation_read_projection_service import (
            MUTATION_TRANSITION_ACTIVE_CHECKPOINT_KEY,
            MUTATION_TRANSITION_PHASE_CHECKPOINT_KEY,
        )

        async with self.session_factory() as session:
            async with session.begin():
                request_repository = KnowledgeSpaceFileChangeRequestRepository(session)
                request = await request_repository.get_by_id(
                    tenant_id=context.tenant_id,
                    request_id=context.request_id,
                    for_update=True,
                )
                if request is None or request.execution_token != context.execution_token:
                    raise RuntimeError("stale F046 mutation fence attempt")
                checkpoint = dict(request.execution_checkpoint or {})
                already_in_state = bool(checkpoint.get(MUTATION_TRANSITION_ACTIVE_CHECKPOINT_KEY)) == bool(
                    active
                ) and str(checkpoint.get(MUTATION_TRANSITION_PHASE_CHECKPOINT_KEY) or phase) == str(phase)
                if already_in_state and active:
                    return
                footprint_repository = KnowledgeSpaceFileChangeFootprintRepository(session)
                if active:
                    existing = await footprint_repository.list_by_request_id(
                        tenant_id=context.tenant_id,
                        request_id=context.request_id,
                    )
                    existing_keys = {
                        (int(row.space_id), str(row.resource_type), int(row.resource_id or 0)) for row in existing
                    }
                    additions: list[FootprintEntry] = []
                    for row in context.manifest.get("rows", []):
                        resource_type = "folder" if int(row["file_type"]) == 0 else "knowledge_file"
                        resource_id = int(row["id"])
                        space_ids = {int(row["old_space_id"])}
                        if context.action == KnowledgeSpaceFileChangeAction.MOVE:
                            space_ids.add(int(row["new_space_id"]))
                        for space_id in sorted(space_ids):
                            if (space_id, resource_type, resource_id) not in existing_keys:
                                additions.append(
                                    FootprintEntry(
                                        space_id=space_id,
                                        resource_type=resource_type,
                                        resource_id=resource_id,
                                    )
                                )
                    if additions:
                        await footprint_repository.add_many(
                            tenant_id=context.tenant_id,
                            request_id=context.request_id,
                            footprints=additions,
                        )
                else:
                    await footprint_repository.retire_mutation_projection(
                        tenant_id=context.tenant_id,
                        request_id=context.request_id,
                    )
                checkpoint[MUTATION_TRANSITION_ACTIVE_CHECKPOINT_KEY] = bool(active)
                checkpoint[MUTATION_TRANSITION_PHASE_CHECKPOINT_KEY] = str(phase)
                checkpoint["mutation_transition_updated_at"] = datetime.now(UTC).isoformat()
                request.execution_checkpoint = checkpoint
                await request_repository.save(request)

    async def _mark_mutation_step_failed(
        self,
        *,
        context: MutationStepContext,
        step_code: str,
        error_summary: str,
    ) -> None:
        async with self.session_factory() as session:
            async with session.begin():
                await KnowledgeSpaceFileChangeExecutionStepRepository(session).mark_failed(
                    tenant_id=context.tenant_id,
                    request_id=context.request_id,
                    step_code=step_code,
                    attempt_token=context.execution_token,
                    error_summary=error_summary,
                )

    async def _compensate_non_upload_mutation(
        self,
        *,
        context: MutationStepContext,
        external_steps: tuple[str, ...],
    ) -> None:
        if self.mutation_step_compensator is None:
            return
        async with self.session_factory() as session:
            async with session.begin():
                request_repository = KnowledgeSpaceFileChangeRequestRepository(session)
                request = await request_repository.get_by_id(
                    tenant_id=context.tenant_id,
                    request_id=context.request_id,
                    for_update=True,
                )
                if request is None or request.execution_token != context.execution_token:
                    return
                request.execution_state = KnowledgeSpaceFileChangeExecutionState.COMPENSATING
                await request_repository.save(request)
                steps = await KnowledgeSpaceFileChangeExecutionStepRepository(session).list_by_request(
                    tenant_id=context.tenant_id,
                    request_id=context.request_id,
                    for_update=True,
                )
                states = {step.step_code: step.state for step in steps}

        for step_code in reversed(external_steps):
            if step_code.endswith(".verify"):
                continue
            if states.get(step_code) not in {
                KnowledgeSpaceFileChangeExecutionStepState.SUCCEEDED,
                KnowledgeSpaceFileChangeExecutionStepState.FAILED,
            }:
                continue
            async with self.session_factory() as session:
                async with session.begin():
                    marked = await KnowledgeSpaceFileChangeExecutionStepRepository(session).mark_compensating(
                        tenant_id=context.tenant_id,
                        request_id=context.request_id,
                        step_code=step_code,
                        attempt_token=context.execution_token,
                    )
                    if not marked:
                        raise RuntimeError("stale F046 mutation compensation attempt")
            step_context = self._mutation_step_context(
                context,
                step_code,
                f"f046:{context.request_id}:{step_code}",
            )
            result = await self._invoke_verified_mutation_effect(self.mutation_step_compensator, step_context)
            async with self.session_factory() as session:
                async with session.begin():
                    marked = await KnowledgeSpaceFileChangeExecutionStepRepository(session).mark_compensated(
                        tenant_id=context.tenant_id,
                        request_id=context.request_id,
                        step_code=step_code,
                        attempt_token=context.execution_token,
                        result_digest=result.result_digest,
                    )
                    if not marked:
                        raise RuntimeError("stale F046 mutation compensation acknowledgement")

    async def _mark_non_upload_attempt_failed(
        self,
        *,
        context: MutationStepContext,
        error_summary: str,
    ) -> None:
        async with self.session_factory() as session:
            async with session.begin():
                repository = KnowledgeSpaceFileChangeRequestRepository(session)
                request = await repository.get_by_id(
                    tenant_id=context.tenant_id,
                    request_id=context.request_id,
                    for_update=True,
                )
                if request is None or request.execution_token != context.execution_token:
                    return
                if request.execution_state == KnowledgeSpaceFileChangeExecutionState.APPLIED:
                    return
                checkpoint = dict(request.execution_checkpoint or {})
                checkpoint["failure_reason"] = str(error_summary)[:1000]
                request.execution_checkpoint = checkpoint
                request.execution_state = KnowledgeSpaceFileChangeExecutionState.FAILED
                await repository.save(request)

    @staticmethod
    async def _invoke_verified_mutation_effect(
        effect: MutationStepEffect,
        context: MutationStepContext,
    ) -> VerifiedMutationStepResult:
        result = effect(context)
        if isawaitable(result):
            result = await result
        if not isinstance(result, VerifiedMutationStepResult):
            raise TypeError("F046 external step must return a verified mutation step result")
        if not result.result_digest or len(result.result_digest) > 255:
            raise ValueError("F046 verified mutation step result requires a 1 to 255 character digest")
        return result

    @staticmethod
    def _mutation_step_context(
        base: MutationStepContext,
        step_code: str,
        idempotency_key: str,
    ) -> MutationStepContext:
        return MutationStepContext(
            tenant_id=base.tenant_id,
            request_id=base.request_id,
            execution_token=base.execution_token,
            action=base.action,
            step_code=step_code,
            idempotency_key=idempotency_key,
            resource_type=base.resource_type,
            resource_id=base.resource_id,
            applicant_user_id=base.applicant_user_id,
            source_space_id=base.source_space_id,
            target_space_id=base.target_space_id,
            manifest=base.manifest,
        )

    async def execute_and_verify_step(self, broker_context):
        """Execute one current owner step from durable DB truth.

        The broker payload is only an identity hint. Action, idempotency key,
        manifest and applicant/resource bindings are reloaded and compared
        before the owner can observe the call.
        """

        from bisheng.knowledge.domain.services.knowledge_space_file_change_execution_coordinator import (
            VerifiedExecutionStepResult,
        )

        if str(broker_context.action) == KnowledgeSpaceFileChangeAction.UPLOAD:
            durable_upload = await self._load_durable_upload_step_context(broker_context)
            effect = (
                self.authorize_file if durable_upload.step_code == UploadExecutionStepCode.FGA else self.dispatch_parse
            )
            digest = await self._invoke_side_effect(effect, durable_upload)
            return VerifiedExecutionStepResult(result_digest=digest or durable_upload.idempotency_key)

        durable = await self._load_durable_mutation_step_context(broker_context)
        result = await self.mutation_step_owner.execute_and_verify(durable)
        digest = self._owner_result_digest(result)
        return VerifiedExecutionStepResult(result_digest=digest)

    async def continue_compensation(self, *, request_id: int, execution_token: str) -> bool:
        """Continue a token-bound durable compensation in reverse order."""

        tenant_id = self._tenant_id()
        async with self.session_factory() as session:
            request = await KnowledgeSpaceFileChangeRequestRepository(session).get_by_id(
                tenant_id=tenant_id,
                request_id=int(request_id),
            )
            if (
                request is None
                or request.execution_token != str(execution_token)
                or request.execution_state != KnowledgeSpaceFileChangeExecutionState.COMPENSATING
                or request.action
                not in {
                    KnowledgeSpaceFileChangeAction.RENAME,
                    KnowledgeSpaceFileChangeAction.MOVE,
                }
            ):
                return False
            manifest = (request.execution_checkpoint or {}).get("mutation_manifest")
            if not isinstance(manifest, dict):
                raise RuntimeError("F046 compensation requires a durable mutation manifest")
            steps = await KnowledgeSpaceFileChangeExecutionStepRepository(session).list_by_request(
                tenant_id=tenant_id,
                request_id=int(request_id),
            )
            external = (
                RenameExecutionStepCode.EXTERNAL
                if request.action == KnowledgeSpaceFileChangeAction.RENAME
                else MoveExecutionStepCode.EXTERNAL
            )
            base = self._mutation_context_from_request(
                request=request,
                manifest=manifest,
            )
            states = {row.step_code: row.state for row in steps}

        for step_code in reversed(external):
            if step_code.endswith(".verify"):
                continue
            state = states.get(step_code)
            if state == KnowledgeSpaceFileChangeExecutionStepState.COMPENSATED:
                continue
            if state not in {
                KnowledgeSpaceFileChangeExecutionStepState.SUCCEEDED,
                KnowledgeSpaceFileChangeExecutionStepState.FAILED,
                KnowledgeSpaceFileChangeExecutionStepState.COMPENSATING,
            }:
                continue
            async with self.session_factory() as session:
                async with session.begin():
                    current = await KnowledgeSpaceFileChangeRequestRepository(session).get_by_id(
                        tenant_id=tenant_id,
                        request_id=int(request_id),
                        for_update=True,
                    )
                    if (
                        current is None
                        or current.execution_token != str(execution_token)
                        or current.execution_state != KnowledgeSpaceFileChangeExecutionState.COMPENSATING
                    ):
                        return False
                    if state != KnowledgeSpaceFileChangeExecutionStepState.COMPENSATING:
                        marked = await KnowledgeSpaceFileChangeExecutionStepRepository(session).mark_compensating(
                            tenant_id=tenant_id,
                            request_id=int(request_id),
                            step_code=step_code,
                            attempt_token=str(execution_token),
                        )
                        if not marked:
                            return False
            durable = self._mutation_step_context(
                base,
                step_code,
                f"f046:{int(request_id)}:{step_code}",
            )
            result = await self.mutation_step_owner.compensate_and_verify(durable)
            digest = self._owner_result_digest(result)
            async with self.session_factory() as session:
                async with session.begin():
                    marked = await KnowledgeSpaceFileChangeExecutionStepRepository(session).mark_compensated(
                        tenant_id=tenant_id,
                        request_id=int(request_id),
                        step_code=step_code,
                        attempt_token=str(execution_token),
                        result_digest=digest,
                    )
                    if not marked:
                        return False

        async with self.session_factory() as session:
            async with session.begin():
                repository = KnowledgeSpaceFileChangeRequestRepository(session)
                current = await repository.get_by_id(
                    tenant_id=tenant_id,
                    request_id=int(request_id),
                    for_update=True,
                )
                if (
                    current is None
                    or current.execution_token != str(execution_token)
                    or current.execution_state != KnowledgeSpaceFileChangeExecutionState.COMPENSATING
                ):
                    return False
                checkpoint = dict(current.execution_checkpoint or {})
                checkpoint["compensation_completed_at"] = datetime.now(UTC).isoformat()
                current.execution_checkpoint = checkpoint
                current.execution_state = KnowledgeSpaceFileChangeExecutionState.FAILED
                await repository.save(current)
        return True

    async def continue_post_cutover_cleanup(self, *, request_id: int, execution_token: str) -> bool:
        """Resume token-bound rename/move residue cleanup after the atomic view switch."""

        tenant_id = self._tenant_id()
        async with self.session_factory() as session:
            request = await KnowledgeSpaceFileChangeRequestRepository(session).get_by_id(
                tenant_id=tenant_id,
                request_id=int(request_id),
            )
            if (
                request is None
                or request.execution_token != str(execution_token)
                or request.execution_state != KnowledgeSpaceFileChangeExecutionState.APPLIED
                or request.action
                not in {
                    KnowledgeSpaceFileChangeAction.RENAME,
                    KnowledgeSpaceFileChangeAction.MOVE,
                }
            ):
                return False
            from bisheng.knowledge.domain.services.knowledge_space_mutation_read_projection_service import (
                MUTATION_TRANSITION_ACTIVE_CHECKPOINT_KEY,
                MUTATION_TRANSITION_NEW_VIEW,
                MUTATION_TRANSITION_PHASE_CHECKPOINT_KEY,
            )

            checkpoint = request.execution_checkpoint or {}
            if not bool(checkpoint.get(MUTATION_TRANSITION_ACTIVE_CHECKPOINT_KEY)):
                return False
            if checkpoint.get(MUTATION_TRANSITION_PHASE_CHECKPOINT_KEY) != MUTATION_TRANSITION_NEW_VIEW:
                raise RuntimeError("F046 post-cutover cleanup requires the durable new-view phase")
            manifest = checkpoint.get("mutation_manifest")
            if not isinstance(manifest, dict):
                raise RuntimeError("F046 post-cutover cleanup requires a durable mutation manifest")
            context = self._mutation_context_from_request(
                request=request,
                manifest=manifest,
            )
        await self._continue_post_cutover_cleanup(context)
        return True

    async def _load_durable_mutation_step_context(self, broker_context) -> MutationStepContext:
        tenant_id = self._tenant_id()
        if int(broker_context.tenant_id) != tenant_id:
            raise RuntimeError("F046 broker tenant does not match the restored tenant context")
        async with self.session_factory() as session:
            async with session.begin():
                request = await KnowledgeSpaceFileChangeRequestRepository(session).get_by_id(
                    tenant_id=tenant_id,
                    request_id=int(broker_context.request_id),
                    for_update=True,
                )
                if (
                    request is None
                    or request.execution_token != str(broker_context.execution_token)
                    or request.execution_state != KnowledgeSpaceFileChangeExecutionState.APPLYING
                    or request.action
                    not in {
                        KnowledgeSpaceFileChangeAction.RENAME,
                        KnowledgeSpaceFileChangeAction.MOVE,
                    }
                ):
                    raise RuntimeError("F046 broker payload does not identify a current mutation generation")
                row = await KnowledgeSpaceFileChangeExecutionStepRepository(session).lock_step(
                    tenant_id=tenant_id,
                    request_id=int(request.id),
                    step_code=str(broker_context.step_code),
                )
                expected_steps = (
                    RenameExecutionStepCode.EXTERNAL
                    if request.action == KnowledgeSpaceFileChangeAction.RENAME
                    else MoveExecutionStepCode.EXTERNAL
                )
                if (
                    row is None
                    or row.step_code not in expected_steps
                    or row.attempt_token != str(broker_context.execution_token)
                    or str(broker_context.action) != str(request.action)
                    or str(broker_context.idempotency_key) != str(row.idempotency_key)
                ):
                    raise RuntimeError("F046 broker payload does not match the durable step identity")
                if row.state not in {
                    KnowledgeSpaceFileChangeExecutionStepState.PENDING,
                    KnowledgeSpaceFileChangeExecutionStepState.DISPATCHED,
                }:
                    raise RuntimeError("F046 durable step is not executable")
                manifest = (request.execution_checkpoint or {}).get("mutation_manifest")
                if not isinstance(manifest, dict):
                    raise RuntimeError("F046 durable mutation manifest is missing")
                return self._mutation_step_context(
                    self._mutation_context_from_request(
                        request=request,
                        manifest=manifest,
                    ),
                    str(row.step_code),
                    str(row.idempotency_key),
                )

    async def _load_durable_upload_step_context(self, broker_context) -> UploadStepDispatchContext:
        tenant_id = self._tenant_id()
        if int(broker_context.tenant_id) != tenant_id:
            raise RuntimeError("F046 broker tenant does not match the restored tenant context")
        async with self.session_factory() as session:
            async with session.begin():
                request = await KnowledgeSpaceFileChangeRequestRepository(session).get_by_id(
                    tenant_id=tenant_id,
                    request_id=int(broker_context.request_id),
                    for_update=True,
                )
                if (
                    request is None
                    or request.execution_token != str(broker_context.execution_token)
                    or request.execution_state != KnowledgeSpaceFileChangeExecutionState.APPLYING
                    or request.action != KnowledgeSpaceFileChangeAction.UPLOAD
                    or request.executed_resource_id is None
                ):
                    raise RuntimeError("F046 broker payload does not identify a current upload generation")
                row = await KnowledgeSpaceFileChangeExecutionStepRepository(session).lock_step(
                    tenant_id=tenant_id,
                    request_id=int(request.id),
                    step_code=str(broker_context.step_code),
                )
                if (
                    row is None
                    or row.step_code not in UploadExecutionStepCode.BUSINESS_REQUIRED
                    or row.attempt_token != str(broker_context.execution_token)
                    or str(broker_context.action) != str(request.action)
                    or str(broker_context.idempotency_key) != str(row.idempotency_key)
                    or row.state
                    not in {
                        KnowledgeSpaceFileChangeExecutionStepState.PENDING,
                        KnowledgeSpaceFileChangeExecutionStepState.DISPATCHED,
                    }
                ):
                    raise RuntimeError("F046 broker payload does not match the durable upload step identity")
                checkpoint = dict(request.execution_checkpoint or {})
                return UploadStepDispatchContext(
                    tenant_id=tenant_id,
                    request_id=int(request.id),
                    execution_token=str(request.execution_token),
                    step_code=str(row.step_code),
                    idempotency_key=str(row.idempotency_key),
                    file_id=int(request.executed_resource_id),
                    file_name=str(request.file_name or request.executed_resource_id),
                    applicant_user_id=int(request.applicant_user_id),
                    space_id=int(request.space_id),
                    checkpoint=checkpoint,
                )

    @staticmethod
    def _mutation_context_from_request(*, request, manifest: dict) -> MutationStepContext:
        root = manifest["root"]
        return MutationStepContext(
            tenant_id=int(request.tenant_id),
            request_id=int(request.id),
            execution_token=str(request.execution_token),
            action=str(request.action),
            step_code="",
            idempotency_key="",
            resource_type=str(request.resource_type),
            resource_id=int(request.resource_id),
            applicant_user_id=int(request.applicant_user_id),
            source_space_id=int(request.space_id),
            target_space_id=(
                int(request.target_space_id) if request.target_space_id is not None else int(root["old_space_id"])
            ),
            manifest=dict(manifest),
        )

    @staticmethod
    def _owner_result_digest(result) -> str:
        if not isinstance(result, (OwnerStepResult, VerifiedMutationStepResult)):
            raise TypeError("F046 owner must return an authoritative verified step result")
        if not result.result_digest or len(result.result_digest) > 255:
            raise ValueError("F046 owner verified digest must contain 1 to 255 characters")
        return str(result.result_digest)

    async def cutover_verified_mutation(
        self,
        *,
        request_id: int,
        execution_token: str,
    ) -> bool:
        """Apply the internal rename/move DB cutover after external verification."""

        tenant_id = self._tenant_id()
        async with self.session_factory() as session:
            request = await KnowledgeSpaceFileChangeRequestRepository(session).get_by_id(
                tenant_id=tenant_id,
                request_id=int(request_id),
            )
            if request is None:
                raise LookupError(f"F046 rename/move request not found: {request_id}")
            if request.action not in {
                KnowledgeSpaceFileChangeAction.RENAME,
                KnowledgeSpaceFileChangeAction.MOVE,
            }:
                raise ValueError("F046 verified mutation cutover requires rename or move")
            if request.execution_token != str(execution_token):
                raise RuntimeError("stale F046 mutation cutover attempt")
            manifest = (request.execution_checkpoint or {}).get("mutation_manifest")
            if not isinstance(manifest, dict):
                raise RuntimeError("F046 mutation cutover requires a durable manifest")
            if request.action == KnowledgeSpaceFileChangeAction.RENAME:
                external_steps = RenameExecutionStepCode.EXTERNAL
                all_steps = RenameExecutionStepCode.ALL
            else:
                external_steps = MoveExecutionStepCode.EXTERNAL
                all_steps = MoveExecutionStepCode.ALL
            root = manifest["root"]
            context = MutationStepContext(
                tenant_id=tenant_id,
                request_id=int(request.id),
                execution_token=str(execution_token),
                action=str(request.action),
                step_code="",
                idempotency_key="",
                resource_type=str(request.resource_type),
                resource_id=int(request.resource_id),
                applicant_user_id=int(request.applicant_user_id),
                source_space_id=int(request.space_id),
                target_space_id=(
                    int(request.target_space_id) if request.target_space_id is not None else int(root["old_space_id"])
                ),
                manifest=dict(manifest),
            )
            payload_snapshot = {
                "change_request_id": int(request.id),
                "space_id": int(request.space_id),
                "action": str(request.action),
                "applicant_user_name": str(request.applicant_user_id),
            }
            cleanup_only = request.execution_state == KnowledgeSpaceFileChangeExecutionState.APPLIED

        if cleanup_only:
            from bisheng.knowledge.domain.services.knowledge_space_mutation_read_projection_service import (
                MUTATION_TRANSITION_ACTIVE_CHECKPOINT_KEY,
            )

            if bool((request.execution_checkpoint or {}).get(MUTATION_TRANSITION_ACTIVE_CHECKPOINT_KEY)):
                await self._continue_post_cutover_cleanup(context)
        else:
            await self._cutover_non_upload_mutation(
                context=context,
                all_steps=all_steps,
                external_steps=external_steps,
                payload_snapshot=payload_snapshot,
            )
        return True

    async def prepare_mutation_resume_in_uow(
        self,
        *,
        session: AsyncSession,
        request_id: int,
        new_token: str,
    ) -> MutationExecutionDispatch:
        """Reset a failed rename/move generation in a Knowledge-owned UoW."""
        tenant_id = self._tenant_id()
        request_repository = KnowledgeSpaceFileChangeRequestRepository(session)
        request = await request_repository.get_by_id(
            tenant_id=tenant_id,
            request_id=int(request_id),
            for_update=True,
        )
        if request is None or request.action not in {
            KnowledgeSpaceFileChangeAction.RENAME,
            KnowledgeSpaceFileChangeAction.MOVE,
        }:
            raise LookupError(f"F046 rename/move request not found: {request_id}")
        if request.execution_state != KnowledgeSpaceFileChangeExecutionState.FAILED:
            raise RuntimeError("only failed F046 rename/move requests can be resumed")
        if not new_token or len(new_token) > 64 or new_token == request.execution_token:
            raise ValueError("F046 resume requires a distinct 1 to 64 character token")
        checkpoint = dict(request.execution_checkpoint or {})
        if not checkpoint.get("mutation_manifest"):
            raise RuntimeError("F046 rename/move resume requires a durable mutation manifest")
        deadline = self.deadline_factory()
        checkpoint["deadline"] = deadline.isoformat()
        checkpoint.pop("failure_reason", None)
        request.execution_checkpoint = checkpoint
        request.execution_token = str(new_token)
        request.execution_state = KnowledgeSpaceFileChangeExecutionState.APPLYING
        await request_repository.save(request)
        verify_step = (
            RenameExecutionStepCode.VERIFY
            if request.action == KnowledgeSpaceFileChangeAction.RENAME
            else MoveExecutionStepCode.VERIFY
        )
        await KnowledgeSpaceFileChangeExecutionStepRepository(session).reset_incomplete_for_resume(
            tenant_id=tenant_id,
            request_id=int(request.id),
            new_token=str(new_token),
            # A previously verified shadow must be read-after-verified again in
            # the new generation, while successful reversible preparation can
            # retain its stable idempotency result.
            reset_succeeded_step_codes=(verify_step,),
        )
        return MutationExecutionDispatch(execution_token=str(new_token), deadline=deadline)

    async def prepare_delete_resume_in_uow(
        self,
        *,
        session: AsyncSession,
        request_id: int,
        new_token: str,
    ) -> MutationExecutionDispatch:
        """Resume only the irreversible post-cutover purge with a fresh token."""

        tenant_id = self._tenant_id()
        request_repository = KnowledgeSpaceFileChangeRequestRepository(session)
        request = await request_repository.get_by_id(
            tenant_id=tenant_id,
            request_id=int(request_id),
            for_update=True,
        )
        if request is None or request.action != KnowledgeSpaceFileChangeAction.DELETE:
            raise LookupError(f"F046 delete request not found: {request_id}")
        checkpoint = dict(request.execution_checkpoint or {})
        if (
            request.execution_state != KnowledgeSpaceFileChangeExecutionState.FAILED
            or checkpoint.get(DELETE_PHASE_CHECKPOINT_KEY) != DELETE_PHASE_PURGE_FAILED
            or not bool(checkpoint.get("deletion_cutover_active"))
        ):
            raise RuntimeError("F046 delete resume requires a failed post-cutover purge")
        if not new_token or len(str(new_token)) > 64:
            raise ValueError("F046 execution token must contain 1 to 64 characters")

        step_repository = KnowledgeSpaceFileChangeExecutionStepRepository(session)
        steps = await step_repository.list_by_request(
            tenant_id=tenant_id,
            request_id=int(request_id),
            for_update=True,
        )
        by_code = {step.step_code: step for step in steps}
        if any(code not in by_code for code in DeleteExecutionStepCode.ALL):
            raise RuntimeError("F046 delete resume requires its durable step set")
        if by_code[DeleteExecutionStepCode.DB_CUTOVER].state != KnowledgeSpaceFileChangeExecutionStepState.SUCCEEDED:
            raise RuntimeError("F046 delete resume cannot precede DB cutover")

        for step in steps:
            step.attempt_token = str(new_token)
            if (
                step.step_code in DeleteExecutionStepCode.PURGE
                and step.state != KnowledgeSpaceFileChangeExecutionStepState.SUCCEEDED
            ):
                step.state = KnowledgeSpaceFileChangeExecutionStepState.PENDING
                step.task_id = None
                step.error_summary = None
                step.next_retry_at = None
            session.add(step)

        deadline = self.deadline_factory()
        checkpoint[DELETE_PHASE_CHECKPOINT_KEY] = DELETE_PHASE_PURGING
        checkpoint["deadline"] = deadline.isoformat()
        checkpoint.pop("failure_reason", None)
        checkpoint.pop("purge_failure_reason", None)
        request.execution_checkpoint = checkpoint
        request.execution_state = KnowledgeSpaceFileChangeExecutionState.APPLYING
        request.execution_token = str(new_token)
        await request_repository.save(request)
        await session.flush()
        return MutationExecutionDispatch(execution_token=str(new_token), deadline=deadline)

    async def prepare_upload_resume_in_uow(
        self,
        *,
        session: AsyncSession,
        request_id: int,
        new_token: str,
    ) -> MutationExecutionDispatch:
        """Reset an upload generation inside a Knowledge-owned resume UoW."""
        tenant_id = self._tenant_id()
        request_repository = KnowledgeSpaceFileChangeRequestRepository(session)
        request = await request_repository.get_by_id(
            tenant_id=tenant_id,
            request_id=int(request_id),
            for_update=True,
        )
        if request is None or request.action != KnowledgeSpaceFileChangeAction.UPLOAD:
            raise LookupError(f"F046 upload request not found: {request_id}")
        if request.executed_resource_id is None:
            raise RuntimeError("F046 upload resume requires an existing formal file")
        if request.execution_state != KnowledgeSpaceFileChangeExecutionState.FAILED:
            raise RuntimeError("only failed F046 uploads can be resumed")
        if not new_token or len(new_token) > 64 or new_token == request.execution_token:
            raise ValueError("F046 resume requires a distinct 1 to 64 character token")
        deadline = self.deadline_factory()
        checkpoint = dict(request.execution_checkpoint or {})
        checkpoint["deadline"] = deadline.isoformat()
        checkpoint.pop("failure_reason", None)
        request.execution_checkpoint = checkpoint
        request.execution_token = str(new_token)
        request.execution_state = KnowledgeSpaceFileChangeExecutionState.APPLYING
        await request_repository.save(request)
        await KnowledgeSpaceFileChangeExecutionStepRepository(session).reset_incomplete_for_resume(
            tenant_id=tenant_id,
            request_id=int(request.id),
            new_token=str(new_token),
        )
        return MutationExecutionDispatch(execution_token=str(new_token), deadline=deadline)

    async def _dispatch_after_commit(
        self,
        base_context: UploadStepDispatchContext,
        dispatch_states: dict[str, tuple[str, str]],
    ) -> None:
        fga_state, fga_key = dispatch_states[UploadExecutionStepCode.FGA]
        if fga_state != KnowledgeSpaceFileChangeExecutionStepState.SUCCEEDED:
            context = self._step_context(base_context, UploadExecutionStepCode.FGA, fga_key)
            digest = await self._invoke_side_effect(self.authorize_file, context)
            async with self.session_factory() as session:
                async with session.begin():
                    marked = await KnowledgeSpaceFileChangeExecutionStepRepository(session).mark_succeeded(
                        tenant_id=context.tenant_id,
                        request_id=context.request_id,
                        step_code=context.step_code,
                        attempt_token=context.execution_token,
                        result_digest=digest,
                    )
                    if not marked:
                        raise RuntimeError("stale F046 FGA acknowledgement")

        parse_state, parse_key = dispatch_states[UploadExecutionStepCode.PARSE]
        if parse_state != KnowledgeSpaceFileChangeExecutionStepState.SUCCEEDED:
            context = self._step_context(base_context, UploadExecutionStepCode.PARSE, parse_key)
            digest = await self._invoke_side_effect(self.dispatch_parse, context)
            async with self.session_factory() as session:
                async with session.begin():
                    marked = await KnowledgeSpaceFileChangeExecutionStepRepository(session).mark_succeeded(
                        tenant_id=context.tenant_id,
                        request_id=context.request_id,
                        step_code=context.step_code,
                        attempt_token=context.execution_token,
                        result_digest=digest,
                    )
                    if not marked:
                        raise RuntimeError("stale F046 parse dispatch acknowledgement")

    async def _mark_upload_attempt_failed(
        self,
        *,
        tenant_id: int,
        request_id: int,
        execution_token: str,
        error_summary: str,
    ) -> None:
        async with self.session_factory() as session:
            async with session.begin():
                repository = KnowledgeSpaceFileChangeRequestRepository(session)
                request = await repository.get_by_id(
                    tenant_id=tenant_id,
                    request_id=request_id,
                    for_update=True,
                )
                if request is None or request.execution_token != execution_token:
                    return
                if request.execution_state == KnowledgeSpaceFileChangeExecutionState.APPLIED:
                    return
                checkpoint = dict(request.execution_checkpoint or {})
                checkpoint["failure_reason"] = error_summary[:1000]
                request.execution_checkpoint = checkpoint
                request.execution_state = KnowledgeSpaceFileChangeExecutionState.FAILED
                await repository.save(request)

    @staticmethod
    async def _invoke_side_effect(effect: UploadSideEffect, context: UploadStepDispatchContext) -> str | None:
        result = effect(context)
        if isawaitable(result):
            result = await result
        return None if result is None else str(result)

    @staticmethod
    async def _validate_upload_execution(
        *,
        session: AsyncSession,
        mutation_repository: KnowledgeSpaceMutationRepository,
        request,
        stage,
        space,
        payload_snapshot: dict,
    ) -> None:
        """Fail-closed revalidation immediately before formal registration."""
        from bisheng.common.dependencies.user_deps import UserPayload
        from bisheng.common.errcode.knowledge_space import (
            SpaceFileSizeLimitError,
            SpaceFolderNotFoundError,
            SpaceNotFoundError,
            SpacePermissionDeniedError,
        )
        from bisheng.knowledge.domain.models.knowledge import KnowledgeState, KnowledgeTypeEnum
        from bisheng.knowledge.domain.repositories.knowledge_space_file_change_repository import (
            KnowledgeSpaceFileChangeRepository,
        )
        from bisheng.knowledge.domain.repositories.knowledge_space_upload_stage_repository import (
            KnowledgeSpaceUploadStageRepository,
        )
        from bisheng.role.domain.services.quota_service import QuotaService

        tenant_id = int(request.tenant_id)
        space_id = int(request.space_id)
        applicant_user_id = int(request.applicant_user_id)
        if (
            int(space.tenant_id) != tenant_id
            or int(space.id) != space_id
            or int(space.type) != KnowledgeTypeEnum.SPACE.value
            or int(space.state) != KnowledgeState.PUBLISHED.value
        ):
            raise SpaceNotFoundError()

        if request.source_parent_id is not None:
            parent_id = int(request.source_parent_id)
            parent = await mutation_repository.get_folder(
                tenant_id=tenant_id,
                space_id=space_id,
                folder_id=parent_id,
                for_update=True,
            )
            if parent is None:
                raise SpaceFolderNotFoundError()
            permission_object_type = "folder"
            permission_object_id = parent_id
        else:
            permission_object_type = "knowledge_space"
            permission_object_id = space_id

        applicant_role_ids = await mutation_repository.get_current_user_role_ids(
            tenant_id=tenant_id,
            user_id=applicant_user_id,
        )
        applicant = UserPayload(
            user_id=applicant_user_id,
            user_name=str(payload_snapshot.get("applicant_user_name") or applicant_user_id),
            tenant_id=tenant_id,
            user_role=applicant_role_ids,
        )
        from bisheng.knowledge.domain.services.knowledge_space_service import KnowledgeSpaceService

        permission_id_allowed = await KnowledgeSpaceService(
            request=None,
            login_user=applicant,
        ).has_effective_permission_id_strict(
            permission_object_type,
            permission_object_id,
            "upload_file",
            space_id=space_id,
            locked_space=space,
        )
        if not permission_id_allowed:
            raise SpacePermissionDeniedError()

        # Stage registration/attachment and execution serialize quota decisions
        # through the same tenant policy row. The current ATTACHED stage is
        # already included in reserved bytes, so execution adds zero bytes here.
        await KnowledgeSpaceFileChangeRepository(session).ensure_policy_row(
            tenant_id=tenant_id,
            for_update=True,
        )
        stage_repository = KnowledgeSpaceUploadStageRepository(session)
        reserved_user = await stage_repository.get_reserved_bytes(
            tenant_id=tenant_id,
            uploader_user_id=applicant_user_id,
        )
        user_used = await mutation_repository.get_user_uploaded_file_size(
            tenant_id=tenant_id,
            user_id=applicant_user_id,
        )
        user_limit = await QuotaService.get_knowledge_space_upload_limit_bytes(applicant)
        if user_limit is not None and user_used + reserved_user > int(user_limit):
            raise SpaceFileSizeLimitError()

        reserved_tenant = await stage_repository.get_reserved_bytes(tenant_id=tenant_id)
        tenant_remaining = await QuotaService.get_tenant_storage_remaining_bytes(tenant_id)
        if tenant_remaining is not None and reserved_tenant > int(tenant_remaining):
            tenant_used = await QuotaService.get_tenant_storage_used_bytes(tenant_id)
            blocker = (
                tenant_id,
                "tenant_limit",
                round((tenant_used + reserved_tenant) / (1024**3), 2),
                round((tenant_used + int(tenant_remaining)) / (1024**3), 2),
                "",
            )
            raise QuotaService._make_storage_quota_error(blocker, "storage_gb")

    @staticmethod
    async def _validate_non_upload_execution(
        *,
        session: AsyncSession,
        mutation_repository: KnowledgeSpaceMutationRepository,
        request,
        manifest: dict,
        payload_snapshot: dict,
    ) -> None:
        del session
        from bisheng.common.dependencies.user_deps import UserPayload
        from bisheng.common.errcode.knowledge_space import (
            SpaceNotFoundError,
            SpacePermissionDeniedError,
        )
        from bisheng.knowledge.domain.models.knowledge import KnowledgeState
        from bisheng.knowledge.domain.services.knowledge_space_service import KnowledgeSpaceService

        tenant_id = int(request.tenant_id)
        source_space_id = int(request.space_id)
        target_space_id = (
            int(request.target_space_id) if request.action == KnowledgeSpaceFileChangeAction.MOVE else source_space_id
        )
        spaces = await mutation_repository.lock_spaces(
            tenant_id=tenant_id,
            space_ids=[source_space_id, target_space_id],
        )
        if len(spaces) != len({source_space_id, target_space_id}) or any(
            int(space.state) != KnowledgeState.PUBLISHED.value for space in spaces
        ):
            raise SpaceNotFoundError()
        spaces_by_id = {int(space.id): space for space in spaces}

        applicant_user_id = int(request.applicant_user_id)
        applicant_role_ids = await mutation_repository.get_current_user_role_ids(
            tenant_id=tenant_id,
            user_id=applicant_user_id,
        )
        applicant = UserPayload(
            user_id=applicant_user_id,
            user_name=str(payload_snapshot.get("applicant_user_name") or request.applicant_user_id),
            tenant_id=tenant_id,
            user_role=applicant_role_ids,
        )
        service = KnowledgeSpaceService(request=None, login_user=applicant)
        source_type = "folder" if request.resource_type == "folder" else "knowledge_file"
        if request.action == KnowledgeSpaceFileChangeAction.RENAME:
            source_permission = "rename_folder" if source_type == "folder" else "rename_file"
        elif request.action == KnowledgeSpaceFileChangeAction.MOVE:
            source_permission = "move_folder" if source_type == "folder" else "move_file"
        else:
            source_permission = "delete_folder" if source_type == "folder" else "delete_file"
        source_allowed = await service.has_effective_permission_id_strict(
            source_type,
            int(request.resource_id),
            source_permission,
            space_id=source_space_id,
            locked_space=spaces_by_id[source_space_id],
        )
        if not source_allowed:
            raise SpacePermissionDeniedError()

        if request.action == KnowledgeSpaceFileChangeAction.MOVE:
            if request.target_parent_id is None:
                target_type = "knowledge_space"
                target_id = target_space_id
            else:
                target_type = "folder"
                target_id = int(request.target_parent_id)
            target_allowed = await service.has_effective_permission_id_strict(
                target_type,
                target_id,
                "upload_file",
                space_id=target_space_id,
                locked_space=spaces_by_id[target_space_id],
            )
            if not target_allowed:
                raise SpacePermissionDeniedError()
        if request.action == KnowledgeSpaceFileChangeAction.DELETE:
            await mutation_repository.validate_delete_manifest_current(
                tenant_id=tenant_id,
                manifest=manifest,
            )
        else:
            await mutation_repository.validate_manifest_current(
                tenant_id=tenant_id,
                manifest=manifest,
            )

    @staticmethod
    def _step_context(
        base: UploadStepDispatchContext,
        step_code: str,
        idempotency_key: str,
    ) -> UploadStepDispatchContext:
        return UploadStepDispatchContext(
            tenant_id=base.tenant_id,
            request_id=base.request_id,
            execution_token=base.execution_token,
            step_code=step_code,
            idempotency_key=idempotency_key,
            file_id=base.file_id,
            file_name=base.file_name,
            applicant_user_id=base.applicant_user_id,
            space_id=base.space_id,
            checkpoint=base.checkpoint,
        )

    @staticmethod
    def _validate_upload_request(*, request) -> None:
        if request.action != KnowledgeSpaceFileChangeAction.UPLOAD:
            raise ValueError("F046 upload executor received a non-upload request")
        if request.upload_stage_id is None:
            raise ValueError("F046 upload request has no stage")

    @staticmethod
    def _validate_non_upload_request(*, request) -> None:
        if request.action not in {
            KnowledgeSpaceFileChangeAction.RENAME,
            KnowledgeSpaceFileChangeAction.MOVE,
            KnowledgeSpaceFileChangeAction.DELETE,
        }:
            raise ValueError("F046 formal mutation executor received an unsupported request")
        if request.resource_id is None:
            raise ValueError("F046 formal mutation request has no resource")

    @classmethod
    def _build_upload_checkpoint(cls, *, request, file, created_folders, deadline: datetime) -> dict[str, Any]:
        resources: list[dict[str, Any]] = []
        for resource in (*created_folders, file):
            parent_parts = [part for part in (resource.file_level_path or "").split("/") if part]
            parent_type = "folder" if parent_parts else "knowledge_space"
            parent_id = int(parent_parts[-1]) if parent_parts else int(request.space_id)
            resources.append(
                {
                    "resource_type": "folder" if int(resource.file_type) == 0 else "knowledge_file",
                    "resource_id": int(resource.id),
                    "parent_type": parent_type,
                    "parent_id": parent_id,
                    "owner_user_id": int(request.applicant_user_id),
                }
            )
        return {
            "deadline": deadline.isoformat(),
            "formal_file_id": int(file.id),
            # Publication guards consume only this small business manifest;
            # they must not parse the unrelated OpenFGA dispatch structure.
            "formal_resource_ids": [
                {
                    "resource_type": resource["resource_type"],
                    "resource_id": int(resource["resource_id"]),
                }
                for resource in resources
            ],
            "fga_resources": resources,
            "publication_required_steps": list(UploadExecutionStepCode.BUSINESS_REQUIRED),
        }

    @staticmethod
    def _checkpoint_deadline(checkpoint: dict | None) -> datetime:
        raw = (checkpoint or {}).get("deadline")
        if not raw:
            raise RuntimeError("F046 upload checkpoint has no deferred deadline")
        deadline = datetime.fromisoformat(str(raw))
        return deadline if deadline.tzinfo is not None else deadline.replace(tzinfo=UTC)

    @staticmethod
    async def _authorize_file(context: UploadStepDispatchContext) -> str:
        from bisheng.permission.domain.schemas.tuple_operation import TupleOperation
        from bisheng.permission.domain.services.owner_service import OwnerService
        from bisheng.permission.domain.services.permission_service import PermissionService

        resources = context.checkpoint.get("fga_resources") or []
        if not resources:
            raise RuntimeError("F046 upload checkpoint has no FGA resource manifest")
        for resource in resources:
            await PermissionService.batch_write_tuples(
                [
                    TupleOperation(
                        action="write",
                        user=f"{resource['parent_type']}:{int(resource['parent_id'])}",
                        relation="parent",
                        object=f"{resource['resource_type']}:{int(resource['resource_id'])}",
                    )
                ],
                crash_safe=True,
                raise_on_failure=True,
                stop_on_failure=True,
            )
            await OwnerService.write_owner_tuple(
                int(resource["owner_user_id"]),
                str(resource["resource_type"]),
                str(resource["resource_id"]),
                enforce_fga_success=True,
            )
        return f"fga:{context.idempotency_key}"

    @staticmethod
    async def _dispatch_parse(context: UploadStepDispatchContext) -> str:
        from bisheng.knowledge.domain.services.knowledge_space_service import KnowledgeSpaceService
        from bisheng.worker.knowledge import scheduler as file_scheduler

        file_scheduler.enqueue_or_dispatch(
            user_id=context.applicant_user_id,
            file_id=context.file_id,
            file_name=context.file_name,
            preview_cache_key=KnowledgeSpaceService.get_preview_cache_key(
                context.space_id,
                context.file_name,
            ),
            callback_url=None,
            idempotency_key=context.idempotency_key,
        )
        # Scheduler acceptance completes the approval-owned handoff. Parsing,
        # indexing and vectorization continue through the regular upload flow.
        return f"scheduler:{context.idempotency_key}"

    @staticmethod
    def _tenant_id() -> int:
        tenant_id = get_current_tenant_id()
        if tenant_id is None:
            raise RuntimeError("tenant context is required for F046 mutation execution")
        return int(tenant_id)

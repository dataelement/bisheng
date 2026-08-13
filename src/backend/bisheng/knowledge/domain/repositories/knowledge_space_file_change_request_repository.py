from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import and_, exists, or_, update
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.knowledge.domain.models.knowledge import Knowledge, KnowledgeTypeEnum
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile
from bisheng.knowledge.domain.models.knowledge_space_file_change_execution_step import (
    KnowledgeSpaceFileChangeExecutionStep,
    KnowledgeSpaceFileChangeExecutionStepState,
)
from bisheng.knowledge.domain.models.knowledge_space_file_change_request import (
    KnowledgeSpaceFileChangeAction,
    KnowledgeSpaceFileChangeCleanupState,
    KnowledgeSpaceFileChangeExecutionState,
    KnowledgeSpaceFileChangeRequest,
)
from bisheng.knowledge.domain.models.knowledge_space_upload_stage import KnowledgeSpaceUploadStage

RESOURCE_LOCK_BLOCKING_STATUSES = frozenset(
    {
        KnowledgeSpaceFileChangeExecutionState.NOT_STARTED,
        KnowledgeSpaceFileChangeExecutionState.QUEUED,
        KnowledgeSpaceFileChangeExecutionState.APPLYING,
        KnowledgeSpaceFileChangeExecutionState.FAILED,
        KnowledgeSpaceFileChangeExecutionState.COMPENSATING,
    }
)

# EXCEPTION is only reconcilable when its current open exception is
# APPROVER_EMPTY. The constant deliberately does not imply that every
# exception instance is eligible; the repository query applies that predicate.
APPROVER_RECONCILABLE_STATUSES = frozenset(
    {
        KnowledgeSpaceFileChangeExecutionState.NOT_STARTED,
    }
)

FILE_CHANGE_SCENARIO_CODE = "knowledge_space_file_change_request"


@dataclass(frozen=True)
class FileChangeReconcileCandidate:
    tenant_id: int
    request_id: int
    instance_id: int
    space_id: int
    update_time: datetime


@dataclass(frozen=True)
class FileChangeRequestReadRow:
    """Knowledge-owned, tenant-bound read projection for F046 APIs."""

    request: KnowledgeSpaceFileChangeRequest
    upload_id: str | None
    stage_state: str | None
    applicant_user_name: str | None
    resource_name: str


class KnowledgeSpaceFileChangeRequestRepository:
    """Session-bound persistence for change requests and their space locks."""

    MAX_RECONCILE_BATCH_SIZE = 500

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def add(
        self,
        *,
        tenant_id: int,
        request: KnowledgeSpaceFileChangeRequest,
    ) -> KnowledgeSpaceFileChangeRequest:
        request.tenant_id = int(tenant_id)
        self.session.add(request)
        await self.session.flush()
        return request

    async def save(
        self,
        request: KnowledgeSpaceFileChangeRequest,
    ) -> KnowledgeSpaceFileChangeRequest:
        """Flush a caller-locked request without owning the transaction."""
        self.session.add(request)
        await self.session.flush()
        return request

    @staticmethod
    def build_get_statement(*, tenant_id: int, request_id: int, for_update: bool = False):
        statement = select(KnowledgeSpaceFileChangeRequest).where(
            KnowledgeSpaceFileChangeRequest.tenant_id == int(tenant_id),
            KnowledgeSpaceFileChangeRequest.id == int(request_id),
        )
        return statement.with_for_update() if for_update else statement

    async def get_by_id(
        self,
        *,
        tenant_id: int,
        request_id: int,
        for_update: bool = False,
    ) -> KnowledgeSpaceFileChangeRequest | None:
        statement = self.build_get_statement(
            tenant_id=tenant_id,
            request_id=request_id,
            for_update=for_update,
        )
        return (await self.session.exec(statement)).first()

    @staticmethod
    def _read_base_statement(*, tenant_id: int, space_id: int):
        tenant_id = int(tenant_id)
        space_id = int(space_id)
        return (
            select(
                KnowledgeSpaceFileChangeRequest,
                KnowledgeSpaceUploadStage.upload_id,
                KnowledgeSpaceUploadStage.state,
            )
            .outerjoin(
                KnowledgeSpaceUploadStage,
                and_(
                    KnowledgeSpaceUploadStage.tenant_id == tenant_id,
                    KnowledgeSpaceUploadStage.id == KnowledgeSpaceFileChangeRequest.upload_stage_id,
                ),
            )
            .where(
                KnowledgeSpaceFileChangeRequest.tenant_id == tenant_id,
                KnowledgeSpaceFileChangeRequest.space_id == space_id,
            )
        )

    @staticmethod
    def _to_read_rows(rows) -> list[FileChangeRequestReadRow]:
        result: list[FileChangeRequestReadRow] = []
        for request, upload_id, stage_state in rows:
            snapshot = dict(request.action_snapshot or {})
            result.append(
                FileChangeRequestReadRow(
                    request=request,
                    upload_id=upload_id,
                    stage_state=stage_state,
                    applicant_user_name=snapshot.get("applicant_user_name"),
                    resource_name=str(snapshot.get("resource_name") or request.file_name or ""),
                )
            )
        return result

    async def get_request_view(
        self,
        *,
        tenant_id: int,
        space_id: int,
        request_id: int,
    ) -> FileChangeRequestReadRow | None:
        statement = self._read_base_statement(tenant_id=tenant_id, space_id=space_id).where(
            KnowledgeSpaceFileChangeRequest.id == int(request_id)
        )
        rows = list((await self.session.exec(statement)).all())
        result = self._to_read_rows(rows)
        return result[0] if result else None

    async def list_upload_request_views(
        self,
        *,
        tenant_id: int,
        space_id: int,
        parent_id: int | None,
        applicant_user_id: int | None,
        execution_states: Sequence[str] | None = None,
        after_create_time: datetime | None,
        after_request_id: int,
        limit: int,
    ) -> tuple[list[FileChangeRequestReadRow], bool]:
        bounded_limit = max(1, min(int(limit), 100))
        statement = self._read_base_statement(tenant_id=tenant_id, space_id=space_id).where(
            KnowledgeSpaceFileChangeRequest.action == KnowledgeSpaceFileChangeAction.UPLOAD,
            KnowledgeSpaceFileChangeRequest.upload_stage_id.is_not(None),
            KnowledgeSpaceFileChangeRequest.cleanup_state != KnowledgeSpaceFileChangeCleanupState.SUCCESS,
        )
        if parent_id is None:
            statement = statement.where(KnowledgeSpaceFileChangeRequest.source_parent_id.is_(None))
        else:
            statement = statement.where(KnowledgeSpaceFileChangeRequest.source_parent_id == int(parent_id))
        if applicant_user_id is not None:
            statement = statement.where(KnowledgeSpaceFileChangeRequest.applicant_user_id == int(applicant_user_id))
        if execution_states:
            statement = statement.where(KnowledgeSpaceFileChangeRequest.execution_state.in_(tuple(execution_states)))
        if after_create_time is not None:
            statement = statement.where(
                or_(
                    KnowledgeSpaceFileChangeRequest.create_time < after_create_time,
                    and_(
                        KnowledgeSpaceFileChangeRequest.create_time == after_create_time,
                        KnowledgeSpaceFileChangeRequest.id < int(after_request_id),
                    ),
                )
            )
        statement = statement.order_by(
            KnowledgeSpaceFileChangeRequest.create_time.desc(),
            KnowledgeSpaceFileChangeRequest.id.desc(),
        ).limit(bounded_limit + 1)
        rows = list((await self.session.exec(statement)).all())
        has_more = len(rows) > bounded_limit
        return (
            self._to_read_rows(rows[:bounded_limit]),
            has_more,
        )

    async def _get_request_views_by_ids(
        self,
        *,
        tenant_id: int,
        space_id: int,
        request_ids: Sequence[int] | None = None,
        instance_ids: Sequence[int] | None = None,
    ) -> list[FileChangeRequestReadRow]:
        statement = self._read_base_statement(tenant_id=tenant_id, space_id=space_id)
        if request_ids is not None:
            statement = statement.where(KnowledgeSpaceFileChangeRequest.id.in_([int(row) for row in request_ids]))
        if instance_ids is not None:
            statement = statement.where(
                KnowledgeSpaceFileChangeRequest.approval_instance_id.in_([int(row) for row in instance_ids])
            )
        rows = list((await self.session.exec(statement)).all())
        return self._to_read_rows(rows)

    async def get_request_views_by_request_ids(
        self,
        *,
        tenant_id: int,
        space_id: int,
        request_ids: Sequence[int],
    ) -> list[FileChangeRequestReadRow]:
        if not request_ids:
            return []
        return await self._get_request_views_by_ids(
            tenant_id=tenant_id,
            space_id=space_id,
            request_ids=request_ids,
        )

    async def get_request_views_by_instance_ids(
        self,
        *,
        tenant_id: int,
        space_id: int,
        instance_ids: Sequence[int],
    ) -> list[FileChangeRequestReadRow]:
        if not instance_ids:
            return []
        return await self._get_request_views_by_ids(
            tenant_id=tenant_id,
            space_id=space_id,
            instance_ids=instance_ids,
        )

    async def get_executed_file_status(
        self,
        *,
        tenant_id: int,
        request: KnowledgeSpaceFileChangeRequest,
    ) -> int | None:
        """Read the formal upload status through the request's durable link."""
        if request.executed_resource_id is None:
            return None
        statement = select(KnowledgeFile.status).where(
            KnowledgeFile.tenant_id == int(tenant_id),
            KnowledgeFile.knowledge_id == int(request.space_id),
            KnowledgeFile.id == int(request.executed_resource_id),
        )
        return (await self.session.exec(statement)).first()

    async def load_business_projection_facts(
        self,
        *,
        tenant_id: int,
        requests: Sequence[KnowledgeSpaceFileChangeRequest],
    ) -> tuple[dict[int, int], dict[int, list[KnowledgeSpaceFileChangeExecutionStep]]]:
        """Load one page's file statuses and durable steps in two queries."""

        if not requests:
            return {}, {}
        tenant_id = int(tenant_id)
        request_ids = sorted({int(request.id) for request in requests})
        file_to_request_and_space = {
            int(request.executed_resource_id): (int(request.id), int(request.space_id))
            for request in requests
            if request.executed_resource_id is not None
        }
        file_status_by_request: dict[int, int] = {}
        if file_to_request_and_space:
            file_rows = list(
                (
                    await self.session.exec(
                        select(KnowledgeFile.id, KnowledgeFile.knowledge_id, KnowledgeFile.status).where(
                            KnowledgeFile.tenant_id == tenant_id,
                            KnowledgeFile.id.in_(sorted(file_to_request_and_space)),
                        )
                    )
                ).all()
            )
            for file_id, knowledge_id, status in file_rows:
                request_id, expected_space_id = file_to_request_and_space[int(file_id)]
                if int(knowledge_id) == expected_space_id:
                    file_status_by_request[request_id] = int(status)
        step_rows = list(
            (
                await self.session.exec(
                    select(KnowledgeSpaceFileChangeExecutionStep)
                    .where(
                        KnowledgeSpaceFileChangeExecutionStep.tenant_id == tenant_id,
                        KnowledgeSpaceFileChangeExecutionStep.request_id.in_(request_ids),
                    )
                    .order_by(
                        KnowledgeSpaceFileChangeExecutionStep.request_id.asc(),
                        KnowledgeSpaceFileChangeExecutionStep.id.asc(),
                    )
                )
            ).all()
        )
        steps_by_request: dict[int, list[KnowledgeSpaceFileChangeExecutionStep]] = {
            request_id: [] for request_id in request_ids
        }
        for step in step_rows:
            steps_by_request[int(step.request_id)].append(step)
        return file_status_by_request, steps_by_request

    async def get_by_upload_stage_id(
        self,
        *,
        tenant_id: int,
        upload_stage_id: int,
        for_update: bool = False,
    ) -> KnowledgeSpaceFileChangeRequest | None:
        """Find the single request attached to a staged upload.

        The explicit tenant predicate is required because this lookup is also
        used to recover the winning request after a uniqueness race.
        """
        statement = select(KnowledgeSpaceFileChangeRequest).where(
            KnowledgeSpaceFileChangeRequest.tenant_id == int(tenant_id),
            KnowledgeSpaceFileChangeRequest.upload_stage_id == int(upload_stage_id),
        )
        if for_update:
            statement = statement.with_for_update()
        return (await self.session.exec(statement)).first()

    async def get_by_approval_instance_id(
        self,
        *,
        tenant_id: int,
        approval_instance_id: int,
    ) -> KnowledgeSpaceFileChangeRequest | None:
        statement = select(KnowledgeSpaceFileChangeRequest).where(
            KnowledgeSpaceFileChangeRequest.tenant_id == int(tenant_id),
            KnowledgeSpaceFileChangeRequest.approval_instance_id == int(approval_instance_id),
        )
        return (await self.session.exec(statement)).first()

    @staticmethod
    def build_unpublished_upload_candidates_statement(
        *,
        tenant_id: int,
        space_ids: Sequence[int],
        required_step_codes: Sequence[str],
    ):
        """Select only upload requests whose formal resources remain guarded.

        Correlated ``EXISTS`` checks avoid fetching every historical published
        request while remaining portable to MySQL and DM8. Checkpoint JSON is
        intentionally not inspected by SQL.
        """
        normalized_space_ids = sorted({int(space_id) for space_id in space_ids})
        missing_step_conditions = []
        for step_code in required_step_codes:
            succeeded_step_exists = exists(
                select(KnowledgeSpaceFileChangeExecutionStep.id).where(
                    KnowledgeSpaceFileChangeExecutionStep.tenant_id == int(tenant_id),
                    KnowledgeSpaceFileChangeExecutionStep.request_id == KnowledgeSpaceFileChangeRequest.id,
                    KnowledgeSpaceFileChangeExecutionStep.step_code == str(step_code),
                    KnowledgeSpaceFileChangeExecutionStep.state == KnowledgeSpaceFileChangeExecutionStepState.SUCCEEDED,
                )
            )
            missing_step_conditions.append(~succeeded_step_exists)
        return (
            select(KnowledgeSpaceFileChangeRequest)
            .where(
                KnowledgeSpaceFileChangeRequest.tenant_id == int(tenant_id),
                KnowledgeSpaceFileChangeRequest.space_id.in_(normalized_space_ids),
                KnowledgeSpaceFileChangeRequest.action == KnowledgeSpaceFileChangeAction.UPLOAD,
                KnowledgeSpaceFileChangeRequest.executed_resource_id.is_not(None),
                or_(
                    KnowledgeSpaceFileChangeRequest.execution_state != KnowledgeSpaceFileChangeExecutionState.APPLIED,
                    *missing_step_conditions,
                ),
            )
            .order_by(KnowledgeSpaceFileChangeRequest.id.asc())
        )

    async def list_unpublished_upload_candidates(
        self,
        *,
        tenant_id: int,
        space_ids: Sequence[int],
        required_step_codes: Sequence[str],
    ) -> list[KnowledgeSpaceFileChangeRequest]:
        if not space_ids:
            return []
        statement = self.build_unpublished_upload_candidates_statement(
            tenant_id=tenant_id,
            space_ids=space_ids,
            required_step_codes=required_step_codes,
        )
        return list((await self.session.exec(statement)).all())

    async def list_delete_cutover_candidates(
        self,
        *,
        tenant_id: int,
        space_ids: Sequence[int],
    ) -> list[KnowledgeSpaceFileChangeRequest]:
        """Return applied deletes; the Service verifies the explicit cutover flag."""
        if not space_ids:
            return []
        normalized_space_ids = sorted({int(space_id) for space_id in space_ids})
        statement = (
            select(KnowledgeSpaceFileChangeRequest)
            .where(
                KnowledgeSpaceFileChangeRequest.tenant_id == int(tenant_id),
                KnowledgeSpaceFileChangeRequest.space_id.in_(normalized_space_ids),
                KnowledgeSpaceFileChangeRequest.action == KnowledgeSpaceFileChangeAction.DELETE,
                KnowledgeSpaceFileChangeRequest.execution_state == KnowledgeSpaceFileChangeExecutionState.APPLIED,
            )
            .order_by(KnowledgeSpaceFileChangeRequest.id.asc())
        )
        return list((await self.session.exec(statement)).all())

    async def attach_approval_instance(
        self,
        *,
        tenant_id: int,
        request_id: int,
        approval_instance_id: int,
    ) -> bool:
        """Attach the F025 instance without relying on SELECT tenant injection."""
        statement = (
            update(KnowledgeSpaceFileChangeRequest)
            .where(
                KnowledgeSpaceFileChangeRequest.tenant_id == int(tenant_id),
                KnowledgeSpaceFileChangeRequest.id == int(request_id),
            )
            .values(approval_instance_id=int(approval_instance_id))
        )
        result = await self.session.exec(statement)
        await self.session.flush()
        return bool(result.rowcount)

    @staticmethod
    def build_lock_spaces_statement(*, tenant_id: int, space_ids: Sequence[int]):
        normalized_ids = sorted({int(space_id) for space_id in space_ids})
        return (
            select(Knowledge)
            .where(
                Knowledge.tenant_id == int(tenant_id),
                Knowledge.id.in_(normalized_ids),
                Knowledge.type == KnowledgeTypeEnum.SPACE.value,
            )
            .order_by(Knowledge.id.asc())
            .with_for_update()
        )

    async def lock_spaces(
        self,
        *,
        tenant_id: int,
        space_ids: Sequence[int],
    ) -> list[Knowledge]:
        """Lock source and destination spaces in one deterministic order."""
        if not space_ids:
            return []
        statement = self.build_lock_spaces_statement(
            tenant_id=tenant_id,
            space_ids=space_ids,
        )
        return list((await self.session.exec(statement)).all())

    @staticmethod
    def build_reconcilable_instance_statement(
        *,
        tenant_id: int,
        space_ids: Sequence[int],
        after_instance_id: int,
        limit: int,
        missing_pending_approver_user_id: int | None = None,
    ):
        tenant_id = int(tenant_id)
        normalized_space_ids = sorted({int(space_id) for space_id in space_ids})
        bounded_limit = max(1, min(int(limit), KnowledgeSpaceFileChangeRequestRepository.MAX_RECONCILE_BATCH_SIZE))
        statement = (
            select(KnowledgeSpaceFileChangeRequest.approval_instance_id)
            .where(
                KnowledgeSpaceFileChangeRequest.tenant_id == tenant_id,
                KnowledgeSpaceFileChangeRequest.space_id.in_(normalized_space_ids),
                KnowledgeSpaceFileChangeRequest.approval_instance_id.is_not(None),
                KnowledgeSpaceFileChangeRequest.approval_instance_id > int(after_instance_id),
                KnowledgeSpaceFileChangeRequest.execution_state == KnowledgeSpaceFileChangeExecutionState.NOT_STARTED,
            )
            .order_by(KnowledgeSpaceFileChangeRequest.approval_instance_id.asc())
            .limit(bounded_limit)
        )
        del missing_pending_approver_user_id
        return statement

    async def list_reconcilable_instance_ids(
        self,
        *,
        tenant_id: int,
        space_ids: Sequence[int],
        after_instance_id: int = 0,
        limit: int = 100,
        missing_pending_approver_user_id: int | None = None,
    ) -> list[int]:
        if not space_ids:
            return []
        statement = self.build_reconcilable_instance_statement(
            tenant_id=tenant_id,
            space_ids=space_ids,
            after_instance_id=after_instance_id,
            limit=limit,
            missing_pending_approver_user_id=missing_pending_approver_user_id,
        )
        return [int(instance_id) for instance_id in (await self.session.exec(statement)).all()]

    @staticmethod
    def build_reconcile_candidates_statement(
        *,
        tenant_id: int,
        after_update_time: datetime | None,
        after_request_id: int,
        limit: int,
    ):
        """Build a tenant-explicit keyset page of reconcilable F046 requests."""

        tenant_id = int(tenant_id)
        statement = (
            select(
                KnowledgeSpaceFileChangeRequest.tenant_id,
                KnowledgeSpaceFileChangeRequest.id,
                KnowledgeSpaceFileChangeRequest.approval_instance_id,
                KnowledgeSpaceFileChangeRequest.space_id,
                KnowledgeSpaceFileChangeRequest.update_time,
            )
            .where(
                KnowledgeSpaceFileChangeRequest.tenant_id == tenant_id,
                KnowledgeSpaceFileChangeRequest.approval_instance_id.is_not(None),
                KnowledgeSpaceFileChangeRequest.execution_state == KnowledgeSpaceFileChangeExecutionState.NOT_STARTED,
            )
        )
        if after_update_time is not None:
            statement = statement.where(
                or_(
                    KnowledgeSpaceFileChangeRequest.update_time > after_update_time,
                    and_(
                        KnowledgeSpaceFileChangeRequest.update_time == after_update_time,
                        KnowledgeSpaceFileChangeRequest.id > int(after_request_id),
                    ),
                )
            )
        return statement.order_by(
            KnowledgeSpaceFileChangeRequest.update_time.asc(),
            KnowledgeSpaceFileChangeRequest.id.asc(),
        ).limit(int(limit))

    async def list_reconcile_candidates(
        self,
        *,
        tenant_id: int,
        after_update_time: datetime | None,
        after_request_id: int = 0,
        limit: int = 100,
    ) -> tuple[list[FileChangeReconcileCandidate], bool]:
        """Return one bounded `(update_time, request_id)` page.

        `limit + 1` is read only to determine whether a continuation is
        necessary; at most `limit` candidates are returned to the caller.
        """

        bounded_limit = max(1, min(int(limit), self.MAX_RECONCILE_BATCH_SIZE))
        statement = self.build_reconcile_candidates_statement(
            tenant_id=tenant_id,
            after_update_time=after_update_time,
            after_request_id=after_request_id,
            limit=bounded_limit + 1,
        )
        rows = list((await self.session.exec(statement)).all())
        has_more = len(rows) > bounded_limit
        candidates: list[FileChangeReconcileCandidate] = []
        seen_instance_ids: set[int] = set()
        for row in rows[:bounded_limit]:
            row_tenant_id, request_id, instance_id, space_id, update_time = row
            if update_time is None:
                raise ValueError(f"F046 reconcile request has no update_time: request_id={request_id}")
            normalized_instance_id = int(instance_id)
            if normalized_instance_id in seen_instance_ids:
                continue
            seen_instance_ids.add(normalized_instance_id)
            candidates.append(
                FileChangeReconcileCandidate(
                    tenant_id=int(row_tenant_id),
                    request_id=int(request_id),
                    instance_id=normalized_instance_id,
                    space_id=int(space_id),
                    update_time=update_time,
                )
            )
        return candidates, has_more

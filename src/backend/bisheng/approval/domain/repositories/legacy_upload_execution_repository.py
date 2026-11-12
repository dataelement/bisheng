"""Read current evidence for the retired, still reachable upload decision path."""

from copy import deepcopy
from dataclasses import dataclass

from sqlalchemy import update
from sqlmodel import select

from bisheng.approval.domain.models.approval_request import ApprovalRequest
from bisheng.common.errcode.approval import ApprovalRequestPermissionDeniedError
from bisheng.common.models.space_channel_member import (
    BusinessTypeEnum,
    MembershipStatusEnum,
    SpaceChannelMember,
    UserRoleEnum,
)
from bisheng.core.context.tenant import strict_tenant_filter
from bisheng.knowledge.domain.models.knowledge import Knowledge
from bisheng.knowledge.domain.models.knowledge_file import FileType, KnowledgeFile

_COLUMNS = (
    "id",
    "tenant_id",
    "request_type",
    "status",
    "space_id",
    "department_id",
    "parent_folder_id",
    "applicant_user_id",
    "applicant_user_name",
    "file_count",
    "safety_status",
    "decided_by",
    "decided_at",
    "update_time",
)


def _deny():
    raise ApprovalRequestPermissionDeniedError()


def _stamp(row):
    return tuple(getattr(row, name) for name in _COLUMNS)


@dataclass(frozen=True)
class ApprovedUpload:
    row: ApprovalRequest
    stamp: tuple
    payload: dict
    paths: tuple[str, ...]


class LegacyUploadExecutionRepository:
    async def acapture(self, session, *, request_id, operator_id, tenant_id):
        with session.no_autoflush, strict_tenant_filter():
            row = (
                await session.exec(
                    select(ApprovalRequest).where(
                        ApprovalRequest.id == request_id,
                    )
                )
            ).one_or_none()
            if (
                row is None
                or row.tenant_id != tenant_id
                or row.status != "approved"
                or row.decided_by != operator_id
                or row.request_type != "department_knowledge_space_file_upload"
                or row.applicant_user_id == operator_id
                or row.safety_status == "rejected"
            ):
                _deny()
            payload = deepcopy(row.payload_json)
            files = payload.get("files") if type(payload) is dict else None
            if (
                type(files) is not list
                or not files
                or len(files) != row.file_count
                or any(
                    type(item) is not dict or type(item.get("file_path")) is not str or not item["file_path"]
                    for item in files
                )
                or payload.get("space_id", row.space_id) != row.space_id
                or payload.get("parent_folder_id", row.parent_folder_id) != row.parent_folder_id
            ):
                _deny()
            return ApprovedUpload(row, _stamp(row), payload, tuple(item["file_path"] for item in files))

    async def acheck(self, session, evidence):
        with session.no_autoflush, strict_tenant_filter():
            row = evidence.row
            current = (
                await session.exec(
                    select(*(getattr(ApprovalRequest, name) for name in _COLUMNS)).where(
                        ApprovalRequest.id == row.id,
                    )
                )
            ).one_or_none()
            if current is None or tuple(current) != evidence.stamp:
                _deny()
            root = (
                await session.exec(
                    select(Knowledge.id, Knowledge.tenant_id, Knowledge.type).where(
                        Knowledge.id == row.space_id,
                    )
                )
            ).one_or_none()
            if root is None or tuple(root) != (row.space_id, row.tenant_id, 3):
                _deny()
            if row.parent_folder_id is not None:
                parent = (
                    await session.exec(
                        select(KnowledgeFile.id, KnowledgeFile.tenant_id).where(
                            KnowledgeFile.id == row.parent_folder_id,
                            KnowledgeFile.knowledge_id == row.space_id,
                            KnowledgeFile.file_type == FileType.DIR.value,
                        )
                    )
                ).one_or_none()
                if parent is None or tuple(parent) != (row.parent_folder_id, row.tenant_id):
                    _deny()
            reviewer = (
                await session.exec(
                    select(SpaceChannelMember.id)
                    .where(
                        SpaceChannelMember.business_id == str(row.space_id),
                        SpaceChannelMember.business_type == BusinessTypeEnum.SPACE,
                        SpaceChannelMember.user_id == row.decided_by,
                        SpaceChannelMember.status == MembershipStatusEnum.ACTIVE,
                        SpaceChannelMember.user_role.in_((UserRoleEnum.CREATOR, UserRoleEnum.ADMIN)),
                    )
                    .limit(1)
                )
            ).first()
            if reviewer is None:
                _deny()

    async def afinalize(self, session, evidence, created_ids):
        with session.no_autoflush, strict_tenant_filter():
            await self.acheck(session, evidence)
            row = (
                await session.exec(
                    select(ApprovalRequest)
                    .where(
                        ApprovalRequest.id == evidence.row.id,
                    )
                    .with_for_update()
                    .execution_options(populate_existing=True)
                )
            ).one_or_none()
            if row is None or _stamp(row) != evidence.stamp or row.payload_json != evidence.payload:
                _deny()
            payload = {**evidence.payload, "finalized_file_ids": list(created_ids)}
            from sqlalchemy import func

            result = await session.exec(
                update(ApprovalRequest)
                .where(
                    ApprovalRequest.id == row.id,
                    ApprovalRequest.tenant_id == row.tenant_id,
                    ApprovalRequest.status == "approved",
                    ApprovalRequest.decided_by == row.decided_by,
                )
                .values(status="finalized", payload_json=payload, finalized_at=func.now())
            )
            if result.rowcount != 1:
                _deny()

    async def amark_failed(self, session, *, row, operator_id, error):
        from sqlalchemy import func

        result = await session.exec(
            update(ApprovalRequest)
            .where(
                ApprovalRequest.id == row.id,
                ApprovalRequest.tenant_id == row.tenant_id,
                ApprovalRequest.space_id == row.space_id,
                ApprovalRequest.parent_folder_id == row.parent_folder_id,
                ApprovalRequest.applicant_user_id == row.applicant_user_id,
                ApprovalRequest.decided_by == operator_id,
                ApprovalRequest.status == "approved",
            )
            .values(status="finalize_failed", safety_reason=str(error), finalized_at=func.now())
        )
        if result.rowcount != 1:
            _deny()

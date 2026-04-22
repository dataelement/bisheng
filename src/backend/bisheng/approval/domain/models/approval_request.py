from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional

from sqlalchemy import JSON, Column, DateTime, String, Text, or_, text
from sqlmodel import Field, func, select, update

from bisheng.common.models.base import SQLModelSerializable
from bisheng.core.database import get_async_db_session


class ApprovalRequestTypeEnum(str, Enum):
    DEPARTMENT_KNOWLEDGE_SPACE_FILE_UPLOAD = 'department_knowledge_space_file_upload'


class ApprovalRequestStatusEnum(str, Enum):
    PENDING_REVIEW = 'pending_review'
    SENSITIVE_REJECTED = 'sensitive_rejected'
    APPROVED = 'approved'
    REJECTED = 'rejected'
    FINALIZED = 'finalized'
    FINALIZE_FAILED = 'finalize_failed'


class ApprovalSafetyStatusEnum(str, Enum):
    SKIPPED = 'skipped'
    PASSED = 'passed'
    REJECTED = 'rejected'


class ApprovalReviewModeEnum(str, Enum):
    FIRST_RESPONSE_WINS = 'first_response_wins'


class ApprovalRequestBase(SQLModelSerializable):
    tenant_id: int = Field(default=1, index=True)
    request_type: str = Field(
        default=ApprovalRequestTypeEnum.DEPARTMENT_KNOWLEDGE_SPACE_FILE_UPLOAD.value,
        sa_column=Column(String(64), nullable=False, index=True),
    )
    status: str = Field(
        default=ApprovalRequestStatusEnum.PENDING_REVIEW.value,
        sa_column=Column(String(32), nullable=False, index=True),
    )
    review_mode: str = Field(
        default=ApprovalReviewModeEnum.FIRST_RESPONSE_WINS.value,
        sa_column=Column(String(32), nullable=False, server_default=text("'first_response_wins'")),
    )
    space_id: int = Field(default=0, index=True)
    department_id: int = Field(default=0, index=True)
    parent_folder_id: Optional[int] = Field(default=None, index=True)
    applicant_user_id: int = Field(default=0, index=True)
    applicant_user_name: str = Field(default='', sa_column=Column(String(255), nullable=False))
    reviewer_user_ids: Optional[List[int]] = Field(default=None, sa_column=Column(JSON, nullable=True))
    file_count: int = Field(default=0, index=False)
    payload_json: Dict = Field(default_factory=dict, sa_column=Column(JSON, nullable=False))
    safety_status: str = Field(
        default=ApprovalSafetyStatusEnum.SKIPPED.value,
        sa_column=Column(String(32), nullable=False, server_default=text("'skipped'")),
    )
    safety_reason: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
    decision_reason: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
    decided_by: Optional[int] = Field(default=None, index=True)
    decided_at: Optional[datetime] = Field(default=None, sa_column=Column(DateTime, nullable=True))
    finalized_at: Optional[datetime] = Field(default=None, sa_column=Column(DateTime, nullable=True))
    message_id: Optional[int] = Field(default=None, index=True)
    create_time: Optional[datetime] = Field(
        default=None,
        sa_column=Column(DateTime, nullable=False, server_default=text('CURRENT_TIMESTAMP')),
    )
    update_time: Optional[datetime] = Field(
        default=None,
        sa_column=Column(
            DateTime,
            nullable=False,
            server_default=text('CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP'),
        ),
    )


class ApprovalRequest(ApprovalRequestBase, table=True):
    __tablename__ = 'approval_request'
    id: Optional[int] = Field(default=None, primary_key=True)


class ApprovalRequestDao(ApprovalRequestBase):
    @classmethod
    async def acreate(cls, row: ApprovalRequest) -> ApprovalRequest:
        async with get_async_db_session() as session:
            session.add(row)
            await session.commit()
            await session.refresh(row)
            return row

    @classmethod
    async def aget_by_id(cls, request_id: int) -> Optional[ApprovalRequest]:
        async with get_async_db_session() as session:
            return await session.get(ApprovalRequest, request_id)

    @classmethod
    async def aupdate(cls, row: ApprovalRequest) -> ApprovalRequest:
        async with get_async_db_session() as session:
            session.add(row)
            await session.commit()
            await session.refresh(row)
            return row

    @classmethod
    async def atry_decide(
        cls,
        *,
        request_id: int,
        expected_status: str,
        new_status: str,
        decided_by: int,
        decision_reason: Optional[str],
    ) -> bool:
        async with get_async_db_session() as session:
            stmt = (
                update(ApprovalRequest)
                .where(
                    ApprovalRequest.id == request_id,
                    ApprovalRequest.status == expected_status,
                )
                .values(
                    status=new_status,
                    decided_by=decided_by,
                    decision_reason=decision_reason,
                    decided_at=func.now(),
                )
            )
            result = await session.exec(stmt)
            await session.commit()
            return bool(result.rowcount)

    @classmethod
    async def aset_final_status(
        cls,
        *,
        request_id: int,
        status: str,
        payload_json: Optional[Dict] = None,
        safety_reason: Optional[str] = None,
    ) -> None:
        values = {'status': status}
        if payload_json is not None:
            values['payload_json'] = payload_json
        if safety_reason is not None:
            values['safety_reason'] = safety_reason
        if status in (
            ApprovalRequestStatusEnum.FINALIZED.value,
            ApprovalRequestStatusEnum.FINALIZE_FAILED.value,
        ):
            values['finalized_at'] = func.now()
        async with get_async_db_session() as session:
            stmt = (
                update(ApprovalRequest)
                .where(ApprovalRequest.id == request_id)
                .values(**values)
            )
            await session.exec(stmt)
            await session.commit()

    @classmethod
    async def aupdate_message_id(cls, request_id: int, message_id: int) -> None:
        async with get_async_db_session() as session:
            stmt = (
                update(ApprovalRequest)
                .where(ApprovalRequest.id == request_id)
                .values(message_id=message_id)
            )
            await session.exec(stmt)
            await session.commit()

    @classmethod
    async def alist_all(
        cls,
        *,
        space_id: Optional[int] = None,
        statuses: Optional[List[str]] = None,
    ) -> List[ApprovalRequest]:
        filters = []
        if space_id is not None:
            filters.append(ApprovalRequest.space_id == space_id)
        if statuses:
            filters.append(ApprovalRequest.status.in_(statuses))

        async with get_async_db_session() as session:
            stmt = select(ApprovalRequest)
            if filters:
                for cond in filters:
                    stmt = stmt.where(cond)
            stmt = stmt.order_by(ApprovalRequest.create_time.desc())
            rows = (await session.exec(stmt)).all()
        return rows

    @classmethod
    async def alist(
        cls,
        *,
        space_id: Optional[int] = None,
        applicant_user_id: Optional[int] = None,
        reviewer_user_id: Optional[int] = None,
        statuses: Optional[List[str]] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[List[ApprovalRequest], int]:
        filters = []
        if space_id is not None:
            filters.append(ApprovalRequest.space_id == space_id)
        if applicant_user_id is not None and reviewer_user_id is not None:
            filters.append(
                or_(
                    ApprovalRequest.applicant_user_id == applicant_user_id,
                    ApprovalRequest.reviewer_user_ids.contains([reviewer_user_id]),
                )
            )
        elif applicant_user_id is not None:
            filters.append(ApprovalRequest.applicant_user_id == applicant_user_id)
        elif reviewer_user_id is not None:
            filters.append(
                ApprovalRequest.reviewer_user_ids.contains([reviewer_user_id])
            )
        if statuses:
            filters.append(ApprovalRequest.status.in_(statuses))

        async with get_async_db_session() as session:
            stmt = select(ApprovalRequest)
            if filters:
                for cond in filters:
                    stmt = stmt.where(cond)
            stmt = stmt.order_by(ApprovalRequest.create_time.desc()).offset(
                (page - 1) * page_size
            ).limit(page_size)
            rows = (await session.exec(stmt)).all()

            count_stmt = select(func.count()).select_from(ApprovalRequest)
            if filters:
                for cond in filters:
                    count_stmt = count_stmt.where(cond)
            total = await session.scalar(count_stmt)
        return rows, int(total or 0)

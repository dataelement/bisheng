"""Audit-only session queries (F003 design decision 7).

The application-usage list keeps its ``select(MessageSession)`` assembly in
``AuditLogService``; the clauses and lookups F003 adds live here.
"""

from __future__ import annotations

from collections.abc import Iterable

from sqlalchemy import and_, exists, not_
from sqlmodel import col, select

from bisheng.core.database import get_async_db_session
from bisheng.database.models.flow import FlowType
from bisheng.database.models.session import MessageSession
from bisheng.linsight.domain.models.linsight_session_version import LinsightSessionVersion

USAGE_DAILY = "daily"
USAGE_ASSISTANT = "assistant"
USAGE_WORKFLOW = "workflow"
USAGE_TASK = "task"
USAGE_TYPES = (USAGE_DAILY, USAGE_ASSISTANT, USAGE_WORKFLOW, USAGE_TASK)

#: Session types the application-usage tab lists. HOSTED_APP (35) is not a
#: conversation and stays out.
AUDIT_SESSION_FLOW_TYPES = (
    FlowType.ASSISTANT.value,
    FlowType.WORKFLOW.value,
    FlowType.WORKSTATION.value,
    FlowType.LINSIGHT.value,
    FlowType.CHANNEL_ARTICLE.value,
    FlowType.KNOLEDGE_SPACE.value,
)
#: Workbench-side types: a daily conversation until a task version exists.
_WORKBENCH_FLOW_TYPES = (
    FlowType.WORKSTATION.value,
    FlowType.LINSIGHT.value,
    FlowType.CHANNEL_ARTICLE.value,
    FlowType.KNOLEDGE_SPACE.value,
)


def _has_task_version():
    # EXISTS rather than JOIN: a session with several versions must still be
    # one row in the page and one in the count.
    return exists(select(LinsightSessionVersion.id).where(LinsightSessionVersion.session_id == MessageSession.chat_id))


class AuditSessionRepository:
    @staticmethod
    def usage_type_clause(usage_type: str | None):
        """``WHERE`` clause for one usage type, or ``None`` when not filtering."""
        if not usage_type:
            return None
        if usage_type == USAGE_ASSISTANT:
            return MessageSession.flow_type == FlowType.ASSISTANT.value
        if usage_type == USAGE_WORKFLOW:
            return MessageSession.flow_type == FlowType.WORKFLOW.value
        workbench = col(MessageSession.flow_type).in_(_WORKBENCH_FLOW_TYPES)
        if usage_type == USAGE_TASK:
            return and_(workbench, _has_task_version())
        if usage_type == USAGE_DAILY:
            return and_(workbench, not_(_has_task_version()))
        raise ValueError(f"unknown usage_type {usage_type!r}")

    @staticmethod
    def usage_type_of(flow_type: int, has_task_version: bool) -> str:
        if flow_type == FlowType.ASSISTANT.value:
            return USAGE_ASSISTANT
        if flow_type == FlowType.WORKFLOW.value:
            return USAGE_WORKFLOW
        return USAGE_TASK if has_task_version else USAGE_DAILY

    @classmethod
    async def chat_ids_with_task_version(cls, chat_ids: Iterable[str]) -> set[str]:
        """One query per page: which of these sessions have a task version."""
        ids = sorted({one for one in chat_ids if one})
        if not ids:
            return set()
        statement = select(LinsightSessionVersion.session_id).where(col(LinsightSessionVersion.session_id).in_(ids))
        async with get_async_db_session() as session:
            return set((await session.exec(statement.distinct())).all())

    @classmethod
    async def is_annotator_of(cls, user_id: int, app_id: str) -> bool:
        """The user is assigned to an annotation task covering ``app_id``."""
        from bisheng.database.models.mark_app_user import MarkAppUser

        statement = select(MarkAppUser.id).where(MarkAppUser.user_id == user_id, MarkAppUser.app_id == app_id).limit(1)
        async with get_async_db_session() as session:
            return (await session.exec(statement)).first() is not None

    @classmethod
    async def matches(cls, chat_id: str, conditions: list) -> bool:
        """``chat_id`` is one of the rows the list ``conditions`` would return."""
        statement = select(MessageSession.chat_id).where(MessageSession.chat_id == chat_id, *conditions).limit(1)
        async with get_async_db_session() as session:
            return (await session.exec(statement)).first() is not None

    @classmethod
    async def session_users(cls, conditions: list, keyword: str | None, limit: int) -> list[tuple[int, str]]:
        """Distinct ``(user_id, user_name)`` of sessions matching ``conditions``.

        ``conditions`` is the list's own scope (tenant, types, department), so
        the user picker never offers someone whose sessions the caller cannot
        list (AC-18).
        """
        from bisheng.user.domain.models.user import User

        statement = (
            select(User.user_id, User.user_name)
            .where(User.user_id.in_(select(MessageSession.user_id).where(and_(*conditions))))
            .order_by(User.user_id)
            .limit(limit)
        )
        if keyword:
            pattern = f"%{keyword.strip()}%"
            statement = statement.where(col(User.user_name).like(pattern))
        async with get_async_db_session() as session:
            return [(row[0], row[1]) for row in (await session.exec(statement)).all()]


__all__ = [
    "AUDIT_SESSION_FLOW_TYPES",
    "USAGE_ASSISTANT",
    "USAGE_DAILY",
    "USAGE_TASK",
    "USAGE_TYPES",
    "USAGE_WORKFLOW",
    "AuditSessionRepository",
]

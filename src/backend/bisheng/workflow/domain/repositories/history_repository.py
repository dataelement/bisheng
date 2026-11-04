"""Metadata for already-authorized history; never expose workflow definitions.

Callers retain their existing session/audit authorization. This repository does
not decide access and must not be used to resolve a runnable resource.
"""

from dataclasses import dataclass

from sqlmodel import select

from bisheng.core.database import get_async_db_session, get_sync_db_session
from bisheng.database.models.flow import Flow


@dataclass(frozen=True)
class WorkflowHistoryMetadata:
    id: str
    name: str
    description: str | None
    logo: str | None
    flow_type: int | None


def _metadata_query():
    return select(Flow.id, Flow.name, Flow.description, Flow.logo, Flow.flow_type)


class WorkflowHistoryRepository:
    @staticmethod
    def search_by_name(name: str) -> list[WorkflowHistoryMetadata]:
        with get_sync_db_session() as session:
            rows = session.exec(_metadata_query().where(Flow.name.like(f"%{name}%"))).all()
            return [WorkflowHistoryMetadata(*row) for row in rows]

    @staticmethod
    async def aget_by_ids(flow_ids: list[str]) -> list[WorkflowHistoryMetadata]:
        if not flow_ids:
            return []
        async with get_async_db_session() as session:
            rows = (await session.exec(_metadata_query().where(Flow.id.in_(flow_ids)))).all()
            return [WorkflowHistoryMetadata(*row) for row in rows]

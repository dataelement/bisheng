from collections.abc import Collection

from sqlalchemy import func, update
from sqlmodel import select

from bisheng.chat_session.domain.models.answer_correction import AnswerCorrection, CorrectionState
from bisheng.core.context.tenant import strict_tenant_filter
from bisheng.core.database import get_async_db_session


class AnswerCorrectionRepository:
    @staticmethod
    async def create(record: AnswerCorrection) -> AnswerCorrection:
        with strict_tenant_filter():
            async with get_async_db_session() as session:
                session.add(record)
                await session.commit()
                await session.refresh(record)
                return record

    @staticmethod
    async def get(record_id: int) -> AnswerCorrection | None:
        with strict_tenant_filter():
            async with get_async_db_session() as session:
                return (await session.exec(
                    select(AnswerCorrection).where(AnswerCorrection.id == record_id)
                )).first()

    @staticmethod
    async def list_for_actor(
        *,
        page: int,
        page_size: int,
        submitter_id: int | None = None,
        assignee_id: int | None = None,
        app_ids: Collection[str] | None = None,
        authorized_ids: Collection[int] | None = None,
    ) -> tuple[list[AnswerCorrection], int]:
        filters = []
        if submitter_id is not None:
            filters.append(AnswerCorrection.submitter_id == submitter_id)
        if assignee_id is not None:
            filters.append(AnswerCorrection.assignee_id == assignee_id)
        if app_ids is not None:
            filters.append(AnswerCorrection.app_id.in_(app_ids))
        if authorized_ids is not None:
            filters.append(AnswerCorrection.id.in_(authorized_ids))
        if not filters:
            raise ValueError("Feedback queries require an actor scope")

        with strict_tenant_filter():
            async with get_async_db_session() as session:
                rows = await session.exec(
                    select(AnswerCorrection)
                    .where(*filters)
                    .order_by(AnswerCorrection.created_at.desc(), AnswerCorrection.id.desc())
                    .offset((page - 1) * page_size)
                    .limit(page_size)
                )
                total = await session.exec(
                    select(func.count()).select_from(AnswerCorrection).where(*filters)
                )
                return list(rows.all()), total.one()

    @staticmethod
    async def transition(
        record: AnswerCorrection,
        expected: CorrectionState,
        target: CorrectionState,
        **fields: object,
    ) -> bool:
        with strict_tenant_filter():
            async with get_async_db_session() as session:
                result = await session.exec(
                    update(AnswerCorrection)
                    .where(
                        AnswerCorrection.id == record.id,
                        AnswerCorrection.tenant_id == record.tenant_id,
                        AnswerCorrection.state == expected.value,
                    )
                    .values(state=target.value, updated_at=func.current_timestamp(), **fields)
                )
                await session.commit()
                return result.rowcount == 1

    @staticmethod
    async def review_candidates(assignee_id: int | None) -> list[AnswerCorrection]:
        statement = select(AnswerCorrection).order_by(
            AnswerCorrection.created_at.desc(), AnswerCorrection.id.desc(),
        )
        if assignee_id is not None:
            statement = statement.where(AnswerCorrection.assignee_id == assignee_id)
        with strict_tenant_filter():
            async with get_async_db_session() as session:
                return list((await session.exec(statement)).all())

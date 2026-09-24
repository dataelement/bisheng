"""以数据库租约保证重试预算和同一权限元组的操作顺序。"""

from datetime import datetime, timedelta

from sqlalchemy import case, exists, or_, update
from sqlalchemy.orm import aliased
from sqlmodel import select

from bisheng.database.models.failed_tuple import FailedTuple
from bisheng.permission.domain.repositories.interfaces.failed_tuple_repository import FailedTupleRepository


class FailedTupleRepositoryImpl(FailedTupleRepository):
    def __init__(self, session):
        self.session = session

    def claim(self, owner: str, now: datetime, limit: int = 100) -> list[FailedTuple]:
        self.session.execute(
            update(FailedTuple)
            .where(
                FailedTuple.status == "processing",
                FailedTuple.lease_until <= now,
            )
            .values(
                status=case((FailedTuple.retry_count >= FailedTuple.max_retries, "dead"), else_="pending"),
                lease_owner=None,
                lease_until=None,
                next_retry_at=now + timedelta(minutes=5),
                error_message="retry_interrupted",
            )
        )
        self.session.execute(
            update(FailedTuple)
            .where(
                FailedTuple.status == "pending",
                FailedTuple.retry_count >= FailedTuple.max_retries,
            )
            .values(status="dead", next_retry_at=None)
        )
        previous = aliased(FailedTuple)
        older = exists(
            select(previous.id).where(
                previous.tenant_id == FailedTuple.tenant_id,
                previous.fga_user == FailedTuple.fga_user,
                previous.relation == FailedTuple.relation,
                previous.object == FailedTuple.object,
                previous.id < FailedTuple.id,
                previous.status != "succeeded",
            )
        )
        rows = list(
            self.session.exec(
                select(FailedTuple)
                .where(
                    FailedTuple.status == "pending",
                    FailedTuple.retry_count < FailedTuple.max_retries,
                    or_(FailedTuple.next_retry_at.is_(None), FailedTuple.next_retry_at <= now),
                    ~older,
                )
                .order_by(FailedTuple.id)
                .limit(limit)
                .with_for_update()
                .execution_options(populate_existing=True)
            ).all()
        )
        for row in rows:
            row.status, row.lease_owner = "processing", owner
            row.lease_until = now + timedelta(minutes=5)
            row.retry_count += 1
        self.session.flush()
        return [FailedTuple.model_validate(row.model_dump()) for row in rows]

    def renew(self, owner: str, now: datetime) -> None:
        self.session.execute(
            update(FailedTuple)
            .where(
                FailedTuple.status == "processing",
                FailedTuple.lease_owner == owner,
                FailedTuple.lease_until > now,
            )
            .values(lease_until=now + timedelta(minutes=5))
        )

    def settle(self, owner: str, outcomes: dict[int, str | None], now: datetime) -> int:
        if not outcomes:
            return 0
        succeeded = [row_id for row_id, error in outcomes.items() if error is None]
        result = self.session.execute(
            update(FailedTuple)
            .where(
                FailedTuple.id.in_(list(outcomes)),
                FailedTuple.status == "processing",
                FailedTuple.lease_owner == owner,
                FailedTuple.lease_until > now,
            )
            .values(
                status=case(
                    (FailedTuple.id.in_(succeeded), "succeeded"),
                    (FailedTuple.retry_count >= FailedTuple.max_retries, "dead"),
                    else_="pending",
                ),
                error_message=case(outcomes, value=FailedTuple.id),
                next_retry_at=case((FailedTuple.id.in_(succeeded), None), else_=now + timedelta(minutes=5)),
                lease_owner=None,
                lease_until=None,
                update_time=now,
            )
        )
        return result.rowcount

"""Bounded, tenant-scoped projections for DSH administration."""

from datetime import UTC

from sqlmodel import Session, select

from bisheng.core.context.tenant import strict_tenant_filter
from bisheng.dsh.domain.models.model_call import DshModelCall
from bisheng.dsh.domain.repositories.admin_operation import require_tenant
from bisheng.dsh.domain.schemas.admin import LastCallSnapshot


class DshAdminQueryRepository:
    def __init__(self, session: Session):
        self.session = session

    def last_call(self, user_id: int) -> dict | None:
        tenant_id = require_tenant()
        with strict_tenant_filter():
            row = self.session.exec(
                select(DshModelCall)
                .where(DshModelCall.tenant_id == tenant_id, DshModelCall.user_id == user_id)
                .order_by(DshModelCall.started_at.desc(), DshModelCall.request_id.desc())
                .limit(1)
            ).one_or_none()
        if row is None:
            return None

        def utc(value):
            if value is None:
                return None
            value = value.replace(tzinfo=UTC) if value.tzinfo is None else value
            return value.astimezone(UTC).isoformat().replace("+00:00", "Z")

        return LastCallSnapshot(
            request_id=row.request_id,
            model_id=row.model_id,
            status=row.status,
            started_at=utc(row.started_at),
            finished_at=utc(row.ended_at),
            total_tokens=row.total_tokens,
            projected_at=utc(row.update_time),
        ).model_dump()

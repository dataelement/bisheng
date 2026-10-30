"""Scoped read adapters. Source transactions never write export progress."""

from contextlib import contextmanager
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from sqlalchemy import and_, case, func, or_
from sqlmodel import select

from bisheng.app_governance.domain.models.runtime_audit import RuntimeAuditQuerySnapshot
from bisheng.app_governance.domain.schemas.runtime_audit import FIELDS
from bisheng.app_publish.domain.models.capability_call_record import AppCapabilityCallRecord
from bisheng.core.context.tenant import bypass_tenant_filter, tenant_execution_scope
from bisheng.core.database import get_async_db_session
from bisheng.database.models.app_access_log import AppAccessLog
from bisheng.open_api.domain.models.model_call_record import ModelCallRecord

SOURCES = {"model": ModelCallRecord, "capability": AppCapabilityCallRecord, "access": AppAccessLog}


@contextmanager
def read_scope(scope):
    if scope.tenant_id is None:
        with bypass_tenant_filter():
            yield
    else:
        with tenant_execution_scope(scope.tenant_id):
            yield


def source_time(value, filters):
    return (
        datetime.fromisoformat(value)
        .replace(tzinfo=UTC)
        .astimezone(ZoneInfo(filters.get("source_timezone", "UTC")))
        .replace(tzinfo=None)
    )


def project(row, kind, filters):
    result = dict(row)
    key = "entry_time" if kind == "access" else "create_time"
    value = result.get(key)
    if value is not None:
        result[key] = value.replace(tzinfo=ZoneInfo(filters.get("source_timezone", "UTC"))).astimezone(UTC)
    return result


class RuntimeAuditRepository:
    def __init__(self, session_factory=get_async_db_session):
        self.factory = session_factory

    async def current_user(self, user_id):
        from bisheng.user.domain.models.user import User

        with bypass_tenant_filter():
            async with self.factory() as session:
                return (await session.exec(select(User).where(User.user_id == user_id, User.delete == 0))).first()

    def statement(self, scope, kind, filters, watermark=None):
        model = SOURCES[kind]
        time = model.entry_time if kind == "access" else model.create_time
        stmt = select(*[getattr(model, f).label(f) for f in FIELDS[kind]])
        if scope.tenant_id is not None:
            stmt = stmt.where(model.tenant_id == scope.tenant_id)
        if scope.authorized_app_ids is not None:
            ids = scope.authorized_app_ids
            stmt = stmt.where(
                or_(*(model.app_id.in_(ids[i : i + 500]) for i in range(0, len(ids), 500)))
                if ids
                else model.app_id.in_(())
            )
        if watermark is not None:
            stmt = stmt.where(model.id <= watermark)
        if filters.get("start_time"):
            stmt = stmt.where(time >= source_time(filters["start_time"], filters))
        if filters.get("end_time"):
            stmt = stmt.where(time <= source_time(filters["end_time"], filters))
        upper = source_time(filters["upper_time"], filters)
        stmt = stmt.where(or_(time <= upper, time.is_(None)))
        if filters.get("app_id"):
            stmt = stmt.where(model.app_id == filters["app_id"])
        if filters.get("visitor_id"):
            if kind == "model":
                stmt = stmt.where(
                    model.subject_kind.in_(["user", "natural_person"]), model.subject_id == filters["visitor_id"]
                )
            else:
                visitor = model.user_id if kind == "access" else model.subject_user_id
                stmt = stmt.where(visitor == filters["visitor_id"])
        if filters.get("credential_id"):
            stmt = stmt.where(model.credential_id == filters["credential_id"])
        return stmt, model, time

    async def watermark(self, scope, kind, filters):
        stmt, _, _ = self.statement(scope, kind, filters)
        with read_scope(scope):
            async with self.factory() as s:
                return int((await s.execute(select(func.max(stmt.subquery().c.id)))).scalar() or 0)

    async def page(self, scope, kind, filters, watermark, *, after=None, limit=50):
        stmt, model, time = self.statement(scope, kind, filters, watermark)
        if after:
            when, record_id = after
            if when is None:
                stmt = stmt.where(time.is_(None), model.id < record_id)
            else:
                dt = source_time(when, filters)
                stmt = stmt.where(or_(time < dt, and_(time == dt, model.id < record_id), time.is_(None)))
        stmt = stmt.order_by(case((time.is_(None), 1), else_=0), time.desc(), model.id.desc()).limit(limit)
        with read_scope(scope):
            async with self.factory() as s:
                return [project(row, kind, filters) for row in (await s.execute(stmt)).mappings().all()]

    async def stream_export(self, scope, kind, filters, watermark, *, batch_size=500):
        stmt, model, time = self.statement(scope, kind, filters, watermark)
        stmt = stmt.order_by(case((time.is_(None), 1), else_=0), time.desc(), model.id.desc())
        # SQLAlchemy stream uses the dialect server cursor, not buffered exec/all.
        # The single SELECT preserves one read view; the caller writes progress
        # through a different session. DM8 driver behavior remains a deployment gate.
        with read_scope(scope):
            async with self.factory() as s:
                result = await s.stream(
                    stmt.execution_options(stream_results=True, yield_per=batch_size, max_row_buffer=batch_size)
                )
                try:
                    async for batch in result.mappings().partitions(batch_size):
                        yield [project(row, kind, filters) for row in batch]
                finally:
                    await result.close()

    async def save_snapshot(self, row):
        with tenant_execution_scope(row.tenant_id):
            async with self.factory() as s:
                s.add(row)
                await s.commit()
        return row

    async def snapshot(self, scope, snapshot_id):
        with tenant_execution_scope(scope.owner_tenant_id):
            async with self.factory() as s:
                return (
                    await s.exec(
                        select(RuntimeAuditQuerySnapshot).where(
                            RuntimeAuditQuerySnapshot.id == snapshot_id,
                            RuntimeAuditQuerySnapshot.tenant_id == scope.owner_tenant_id,
                            RuntimeAuditQuerySnapshot.creator_user_id == scope.creator_user_id,
                        )
                    )
                ).first()

    async def candidates(self, scope, kind, dimension, filters, *, query="", offset=0, limit=25):
        from bisheng.common.errcode.app_governance import RuntimeAuditFilterInvalidError

        stmt, model, _ = self.statement(scope, kind, filters)
        if dimension == "app":
            key = "app_id"
            label = {"capability": "app_name", "access": "app_name_snapshot"}.get(kind)
        elif dimension == "visitor":
            key = {"model": "subject_id", "capability": "subject_user_id", "access": "user_id"}[kind]
            label = "user_name" if kind == "access" else None
            if kind == "model":
                stmt = stmt.where(model.subject_kind.in_(["user", "natural_person"]))
        elif dimension == "credential" and kind == "model":
            key = "credential_id"
            label = "credential_mask"
        else:
            raise RuntimeAuditFilterInvalidError()
        sub = stmt.subquery()
        ident = sub.c[key]
        name = func.max(sub.c[label]) if label else None
        statement = (
            select(ident.label("id"), (name if name is not None else ident).label("label"))
            .where(ident.is_not(None))
            .group_by(ident)
        )
        if query:
            from sqlalchemy import String, cast

            statement = statement.having(
                or_(
                    cast(ident, String).contains(query, autoescape=True),
                    name.contains(query, autoescape=True) if name is not None else False,
                )
            )
        with read_scope(scope):
            async with self.factory() as s:
                rows = (await s.execute(statement.order_by(ident).offset(offset).limit(limit + 1))).mappings().all()
        # A historical fact does not prove present existence; unknown is explicit.
        return {
            "items": [
                {"id": str(x["id"]), "label": str(x["label"] or x["id"]), "deleted_or_revoked": None}
                for x in rows[:limit]
            ],
            "has_more": len(rows) > limit,
        }

    async def selector_exists(self, scope, kind, filters, key, value):
        # Resolve only within the source's authorized history. Unknown and foreign
        # identifiers deliberately share the same external refusal.
        base = {
            "time_range": "all",
            "upper_time": datetime.utcnow().isoformat(),
            "source_timezone": filters.get("source_timezone", "UTC"),
            key: value,
        }
        stmt, _, _ = self.statement(scope, kind, base)
        with read_scope(scope):
            async with self.factory() as s:
                return (await s.execute(stmt.limit(1))).first() is not None

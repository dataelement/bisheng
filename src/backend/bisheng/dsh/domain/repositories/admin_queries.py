"""Bounded, tenant-scoped projections for DSH administration."""

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import case, func
from sqlmodel import Session, select

from bisheng.core.context.tenant import strict_tenant_filter
from bisheng.database.models.department import Department, UserDepartment
from bisheng.database.models.tenant import Tenant, UserTenant
from bisheng.dsh.domain.models.model_call import DshModelCall
from bisheng.dsh.domain.repositories.admin_operation import require_tenant
from bisheng.dsh.domain.schemas.admin import LastCallSnapshot, UsageOverviewPage, UsageTimeSummary
from bisheng.user.domain.models.user import User

BEIJING_TIMEZONE = "Asia/Shanghai"
MESSAGE_STATUSES = ("SUCCEEDED", "FAILED", "CANCELLED", "RUNNING", "USAGE_UNKNOWN")


class DshAdminQueryRepository:
    @staticmethod
    def _counted_usage_filter():
        """Usage pages include only calls with platform-owned token accounting."""
        return DshModelCall.usage_source.in_(("PROVIDER", "RECONCILED"))

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

    @staticmethod
    def _empty_metrics():
        return {
            "message_count": 0,
            "qa_count": 0,
            "failed_count": 0,
            "cancelled_count": 0,
            "running_count": 0,
            "usage_unknown_count": 0,
            "recorded_usage_count": 0,
            "missing_usage_count": 0,
            "input_tokens": 0,
            "output_tokens": 0,
            "total_tokens": 0,
        }

    @staticmethod
    def _usage_columns():
        return (
            func.count(DshModelCall.request_id),
            func.sum(case((DshModelCall.status == "SUCCEEDED", 1), else_=0)),
            func.sum(case((DshModelCall.status == "FAILED", 1), else_=0)),
            func.sum(case((DshModelCall.status == "CANCELLED", 1), else_=0)),
            func.sum(case((DshModelCall.status == "RUNNING", 1), else_=0)),
            func.sum(case((DshModelCall.status == "USAGE_UNKNOWN", 1), else_=0)),
            func.count(DshModelCall.total_tokens),
            func.sum(case((DshModelCall.total_tokens.is_(None), 1), else_=0)),
            func.coalesce(func.sum(DshModelCall.input_tokens), 0),
            func.coalesce(func.sum(DshModelCall.output_tokens), 0),
            func.coalesce(func.sum(DshModelCall.total_tokens), 0),
        )

    @classmethod
    def _metrics(cls, row) -> dict:
        if row is None:
            return cls._empty_metrics()
        values = [int(value or 0) for value in row]
        result = dict(zip(cls._empty_metrics(), values, strict=True))
        if result["message_count"] > 0 and result["recorded_usage_count"] == 0:
            result["input_tokens"] = None
            result["output_tokens"] = None
            result["total_tokens"] = None
        return result

    def usage_overview(
        self,
        *,
        start_at: datetime,
        end_at: datetime,
        after_user_id: int,
        limit: int,
        keyword: str,
        department_ids: list[int] | None,
        selected_department_id: int | None,
        include_summary: bool = False,
        granularity: str | None = None,
    ) -> dict:
        """Return a tenant-scoped user page plus one aggregate for the full filter."""
        tenant_id = require_tenant()
        start_utc = start_at.astimezone(UTC)
        end_utc = end_at.astimezone(UTC)
        start_naive = start_utc.replace(tzinfo=None)
        end_naive = end_utc.replace(tzinfo=None)
        timezone = ZoneInfo(BEIJING_TIMEZONE)

        user_scope = (
            select(User.user_id)
            .join(UserTenant, UserTenant.user_id == User.user_id)
            .join(Tenant, Tenant.id == UserTenant.tenant_id)
            .where(
                UserTenant.tenant_id == tenant_id,
                UserTenant.is_active == 1,
                UserTenant.status == "active",
                Tenant.status == "active",
                User.delete == 0,
            )
        )
        if keyword:
            user_scope = user_scope.where(User.user_name.contains(keyword))
        if department_ids is not None:
            user_scope = user_scope.join(UserDepartment, UserDepartment.user_id == User.user_id).where(
                UserDepartment.department_id.in_(department_ids)
            )
        user_scope = user_scope.distinct().subquery()

        with strict_tenant_filter():
            page_rows = list(
                self.session.exec(
                    select(User.user_id, User.user_name)
                    .where(
                        User.user_id.in_(select(user_scope.c.user_id)),
                        User.user_id > after_user_id,
                    )
                    .order_by(User.user_id)
                    .limit(limit + 1)
                ).all()
            )
            total_row = self.session.exec(
                select(*self._usage_columns()).where(
                    DshModelCall.tenant_id == tenant_id,
                    DshModelCall.user_id.in_(select(user_scope.c.user_id)),
                    self._counted_usage_filter(),
                    DshModelCall.started_at >= start_naive,
                    DshModelCall.started_at < end_naive,
                )
            ).one()

        has_more = len(page_rows) > limit
        page_rows = page_rows[:limit]
        page_user_ids = [int(user_id) for user_id, _name in page_rows]
        metrics_by_user: dict[int, dict] = {}
        departments_by_user: dict[int, tuple[int, str]] = {}
        if page_user_ids:
            with strict_tenant_filter():
                metric_rows = self.session.exec(
                    select(DshModelCall.user_id, *self._usage_columns())
                    .where(
                        DshModelCall.tenant_id == tenant_id,
                        DshModelCall.user_id.in_(page_user_ids),
                        self._counted_usage_filter(),
                        DshModelCall.started_at >= start_naive,
                        DshModelCall.started_at < end_naive,
                    )
                    .group_by(DshModelCall.user_id)
                ).all()
                department_rows = self.session.exec(
                    select(UserDepartment.user_id, Department.id, Department.name)
                    .join(Department, Department.id == UserDepartment.department_id)
                    .where(
                        UserDepartment.user_id.in_(page_user_ids),
                        UserDepartment.is_primary == 1,
                        Department.tenant_id == tenant_id,
                        Department.status == "active",
                    )
                    .order_by(UserDepartment.user_id, UserDepartment.id)
                ).all()
            for row in metric_rows:
                metrics_by_user[int(row[0])] = self._metrics(row[1:])
            for user_id, department_id, department_name in department_rows:
                departments_by_user.setdefault(int(user_id), (int(department_id), department_name))

        start_local = start_utc.astimezone(timezone).isoformat()
        end_local = end_utc.astimezone(timezone).isoformat()
        summary = (
            self._usage_time_summary(
                DshModelCall.user_id.in_(select(user_scope.c.user_id)),
                start_at=start_at,
                end_at=end_at,
                granularity=granularity or ("hour" if end_at - start_at <= timedelta(hours=48) else "day"),
            )
            if include_summary
            else None
        )
        result = {
            "tenant_id": tenant_id,
            "start_at": start_local,
            "end_at": end_local,
            "timezone": BEIJING_TIMEZONE,
            "department_id": selected_department_id,
            "totals": summary["totals"] if summary else self._metrics(total_row),
            "summary": summary,
            "items": [
                {
                    "user_id": int(user_id),
                    "user_name": user_name,
                    "department_id": departments_by_user.get(int(user_id), (None, None))[0],
                    "department_name": departments_by_user.get(int(user_id), (None, None))[1],
                    "metrics": metrics_by_user.get(int(user_id), self._empty_metrics()),
                }
                for user_id, user_name in page_rows
            ],
            "next_cursor": str(page_rows[-1][0]) if has_more and page_rows else None,
            "has_more": has_more,
        }
        return UsageOverviewPage.model_validate(result).model_dump()

    def usage_time_summary(
        self,
        user_id: int,
        *,
        start_at: datetime,
        end_at: datetime,
        granularity: str,
    ) -> dict:
        return self._usage_time_summary(
            DshModelCall.user_id == user_id,
            start_at=start_at,
            end_at=end_at,
            granularity=granularity,
        )

    def _usage_time_summary(self, user_filter, *, start_at: datetime, end_at: datetime, granularity: str) -> dict:
        """Aggregate one request row as one message using UTC storage and Beijing buckets."""
        tenant_id = require_tenant()
        start_utc = start_at.astimezone(UTC)
        end_utc = end_at.astimezone(UTC)
        start_naive = start_utc.replace(tzinfo=None)
        end_naive = end_utc.replace(tzinfo=None)
        timezone = ZoneInfo(BEIJING_TIMEZONE)
        start_local = start_utc.astimezone(timezone)
        end_local = end_utc.astimezone(timezone)
        step = timedelta(hours=1) if granularity == "hour" else timedelta(days=1)
        anchor = (
            start_local.replace(minute=0, second=0, microsecond=0)
            if granularity == "hour"
            else start_local.replace(hour=0, minute=0, second=0, microsecond=0)
        )

        buckets = []
        by_anchor = {}
        while anchor < end_local:
            following = anchor + step
            point = {
                "start_at": max(anchor, start_local).isoformat(),
                "end_at": min(following, end_local).isoformat(),
                **self._empty_metrics(),
            }
            buckets.append(point)
            by_anchor[anchor.isoformat()] = point
            anchor = following

        totals = self._empty_metrics()

        def add(metrics, status, input_tokens, output_tokens, total_tokens):
            metrics["message_count"] += 1
            metrics[
                {
                    "SUCCEEDED": "qa_count",
                    "FAILED": "failed_count",
                    "CANCELLED": "cancelled_count",
                    "RUNNING": "running_count",
                    "USAGE_UNKNOWN": "usage_unknown_count",
                }[status]
            ] += 1
            if total_tokens is None:
                metrics["missing_usage_count"] += 1
                return
            if input_tokens is None or output_tokens is None:
                raise ValueError("Recorded DSH token usage must be complete")
            metrics["recorded_usage_count"] += 1
            metrics["input_tokens"] += input_tokens
            metrics["output_tokens"] += output_tokens
            metrics["total_tokens"] += total_tokens

        with strict_tenant_filter():
            rows = self.session.exec(
                select(
                    DshModelCall.started_at,
                    DshModelCall.status,
                    DshModelCall.input_tokens,
                    DshModelCall.output_tokens,
                    DshModelCall.total_tokens,
                )
                .where(
                    DshModelCall.tenant_id == tenant_id,
                    user_filter,
                    self._counted_usage_filter(),
                    DshModelCall.started_at >= start_naive,
                    DshModelCall.started_at < end_naive,
                )
                .order_by(DshModelCall.started_at, DshModelCall.request_id)
            ).yield_per(1000)
            for started_at, status, input_tokens, output_tokens, total_tokens in rows:
                if started_at is None or status not in MESSAGE_STATUSES:
                    raise ValueError("Stored DSH call is outside the usage aggregation contract")
                recorded_at = (
                    started_at.replace(tzinfo=UTC) if started_at.tzinfo is None else started_at.astimezone(UTC)
                )
                local = recorded_at.astimezone(timezone)
                row_anchor = (
                    local.replace(minute=0, second=0, microsecond=0)
                    if granularity == "hour"
                    else local.replace(hour=0, minute=0, second=0, microsecond=0)
                )
                point = by_anchor.get(row_anchor.isoformat())
                if point is None:
                    raise ValueError("Stored DSH call is outside the requested buckets")
                add(point, status, input_tokens, output_tokens, total_tokens)
                add(totals, status, input_tokens, output_tokens, total_tokens)

        def preserve_unknown(metrics):
            if metrics["message_count"] > 0 and metrics["recorded_usage_count"] == 0:
                metrics["input_tokens"] = None
                metrics["output_tokens"] = None
                metrics["total_tokens"] = None
            return metrics

        return UsageTimeSummary.model_validate(
            {
                "start_at": start_local.isoformat(),
                "end_at": end_local.isoformat(),
                "timezone": BEIJING_TIMEZONE,
                "granularity": granularity,
                "totals": preserve_unknown(totals),
                "points": [preserve_unknown(point) for point in buckets],
            }
        ).model_dump()

from __future__ import annotations

from collections.abc import Iterable
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, ClassVar

from elasticsearch import helpers
from loguru import logger

from bisheng.core.cache.redis_manager import get_redis_client, get_redis_client_sync
from bisheng.core.context.tenant import DEFAULT_TENANT_ID
from bisheng.database.models.department import DepartmentDao, UserDepartmentDao
from bisheng.telemetry.domain.mid_table.base import BaseMidTable, BaseRecord
from bisheng.telemetry.domain.mid_table.user_engagement_shared import (
    METRIC_SOURCE_PARTICIPATION,
    USER_ENGAGEMENT_ES_INDEX,
)

CHINA_STANDARD_TIME = timezone(timedelta(hours=8))


def participation_day(
    value: datetime | date | None = None,
) -> tuple[str, int]:
    """Return the China-local business date and its midnight epoch second."""
    if value is None:
        local_value = datetime.now(CHINA_STANDARD_TIME)
    elif isinstance(value, datetime):
        local_value = (
            value.replace(tzinfo=CHINA_STANDARD_TIME)
            if value.tzinfo is None
            else value.astimezone(CHINA_STANDARD_TIME)
        )
    else:
        local_value = datetime.combine(value, time.min, CHINA_STANDARD_TIME)
    local_date = local_value.date()
    midnight = datetime.combine(local_date, time.min, CHINA_STANDARD_TIME)
    return local_date.isoformat(), int(midnight.timestamp())


def aggregate_historical_login_hits(
    hits: Iterable[dict[str, Any]],
) -> dict[tuple[int, str, int], dict[str, Any]]:
    """Group durable login events by tenant, China-local day and employee."""
    aggregates: dict[tuple[int, str, int], dict[str, Any]] = {}
    for hit in hits:
        source = hit.get("_source") or {}
        user_context = source.get("user_context") or {}
        try:
            timestamp = int(source.get("timestamp"))
            user_id = int(user_context.get("user_id"))
            tenant_id = int(source.get("tenant_id") or 1)
        except (TypeError, ValueError):
            continue
        local_date = datetime.fromtimestamp(
            timestamp,
            CHINA_STANDARD_TIME,
        ).date().isoformat()
        key = (tenant_id, local_date, user_id)
        aggregate = aggregates.setdefault(
            key,
            {
                "tenant_id": tenant_id,
                "local_date": local_date,
                "user_id": user_id,
                "user_name": str(user_context.get("user_name") or user_id),
                "login_count": 0,
                "first_login_at": timestamp,
                "last_login_at": timestamp,
            },
        )
        aggregate["login_count"] += 1
        aggregate["first_login_at"] = min(
            aggregate["first_login_at"],
            timestamp,
        )
        aggregate["last_login_at"] = max(
            aggregate["last_login_at"],
            timestamp,
        )
    return aggregates


class DailyParticipationRecord(BaseRecord):
    metric_source: str = METRIC_SOURCE_PARTICIPATION
    tenant_id: int = DEFAULT_TENANT_ID
    local_date: str
    active_employee: int = 1
    logged_in: bool = False
    login_count: int = 0
    first_login_at: int | None = None
    last_login_at: int | None = None
    primary_department_id: int | None = None
    primary_department_name: str | None = None
    department_source: str = "current_roster"
    sync_run_id: str | None = None
    projection_updated_at: int


class DailyParticipationFact(BaseMidTable):
    """One mutable document per tenant, business date and active employee."""

    _index_name = USER_ENGAGEMENT_ES_INDEX
    _update_mappings_on_existing = True
    ROSTER_SCHEDULED_KEY: ClassVar[str] = (
        "telemetry:user_daily_participation:roster_scheduled"
    )
    ROSTER_SCHEDULE_TTL_SECONDS: ClassVar[int] = 5
    _mappings: dict[str, Any] = {
        "metric_source": {"type": "keyword"},
        "tenant_id": {"type": "keyword"},
        "local_date": {"type": "keyword"},
        "active_employee": {"type": "integer"},
        "logged_in": {"type": "boolean"},
        "login_count": {"type": "integer"},
        "first_login_at": {
            "type": "date",
            "format": "strict_date_optional_time||epoch_second",
        },
        "last_login_at": {
            "type": "date",
            "format": "strict_date_optional_time||epoch_second",
        },
        "primary_department_id": {"type": "keyword"},
        "primary_department_name": {
            "type": "keyword",
            "fields": {
                "text": {"type": "text", "analyzer": "single_char_analyzer"},
            },
        },
        "department_source": {"type": "keyword"},
        "sync_run_id": {"type": "keyword"},
        "projection_updated_at": {
            "type": "date",
            "format": "strict_date_optional_time||epoch_second",
        },
    }

    @staticmethod
    def build_es_id(tenant_id: int, local_date: str, user_id: int) -> str:
        return f"participation_{tenant_id}_{local_date}_{user_id}"

    @classmethod
    def schedule_roster_reconcile_sync(cls, countdown: int = 2) -> None:
        """Debounce roster mutations into one near-real-time reconciliation."""
        try:
            redis_client = get_redis_client_sync()
            if not redis_client.setNx(
                cls.ROSTER_SCHEDULED_KEY,
                1,
                expiration=cls.ROSTER_SCHEDULE_TTL_SECONDS,
            ):
                return
            from bisheng.worker.telemetry.mid_table import (
                sync_mid_user_daily_participation_fact,
            )

            sync_mid_user_daily_participation_fact.apply_async(
                countdown=countdown
            )
        except Exception:
            logger.exception("Failed to schedule participation roster sync.")

    @classmethod
    async def schedule_roster_reconcile_async(cls, countdown: int = 2) -> None:
        try:
            redis_client = await get_redis_client()
            if not await redis_client.asetNx(
                cls.ROSTER_SCHEDULED_KEY,
                1,
                expiration=cls.ROSTER_SCHEDULE_TTL_SECONDS,
            ):
                return
            from bisheng.worker.telemetry.mid_table import (
                sync_mid_user_daily_participation_fact,
            )

            sync_mid_user_daily_participation_fact.apply_async(
                countdown=countdown
            )
        except Exception:
            logger.exception("Failed to schedule participation roster sync.")

    @classmethod
    def clear_roster_reconcile_scheduled(cls) -> None:
        try:
            get_redis_client_sync().delete(cls.ROSTER_SCHEDULED_KEY)
        except Exception:
            logger.exception(
                "Failed to clear participation roster scheduled marker."
            )

    @classmethod
    async def record_login(
        cls,
        *,
        tenant_id: int | None,
        user_id: int,
        user_name: str,
        occurred_at: datetime | None = None,
    ) -> DailyParticipationRecord:
        """Atomically mark the employee as logged in and increment raw attempts."""
        event_time = occurred_at or datetime.now(CHINA_STANDARD_TIME)
        event_time = (
            event_time.replace(tzinfo=CHINA_STANDARD_TIME)
            if event_time.tzinfo is None
            else event_time.astimezone(CHINA_STANDARD_TIME)
        )
        local_date, day_timestamp = participation_day(event_time)
        now = int(event_time.timestamp())
        normalized_tenant_id = int(tenant_id or DEFAULT_TENANT_ID)

        primary_membership = await UserDepartmentDao.aget_user_primary_department(
            int(user_id)
        )
        primary_department = (
            await DepartmentDao.aget_by_id(primary_membership.department_id)
            if primary_membership
            else None
        )
        base_document = {
            "metric_source": METRIC_SOURCE_PARTICIPATION,
            "tenant_id": normalized_tenant_id,
            "timestamp": day_timestamp,
            "user_id": int(user_id),
            "user_name": user_name or str(user_id),
            "user_group_infos": [],
            "user_role_infos": [],
            "user_department_infos": [],
            "local_date": local_date,
            "active_employee": 1,
            "logged_in": True,
            "login_count": 1,
            "first_login_at": now,
            "last_login_at": now,
            "primary_department_id": (
                int(primary_department.id) if primary_department else None
            ),
            "primary_department_name": (
                primary_department.name if primary_department else None
            ),
            "department_source": "event_time",
            "projection_updated_at": now,
        }

        fact = cls(ensure_sync_index=False)
        await fact.ensure_index_exists()
        await fact._es_client.update(
            index=fact._index_name,
            id=cls.build_es_id(normalized_tenant_id, local_date, int(user_id)),
            script={
                "lang": "painless",
                "source": """
                    ctx._source.tenant_id = params.doc.tenant_id;
                    ctx._source.timestamp = params.doc.timestamp;
                    ctx._source.user_id = params.doc.user_id;
                    ctx._source.user_name = params.doc.user_name;
                    ctx._source.local_date = params.doc.local_date;
                    ctx._source.active_employee = 1;
                    ctx._source.logged_in = true;
                    ctx._source.login_count =
                        (ctx._source.login_count == null ? 0 : ctx._source.login_count) + 1;
                    if (ctx._source.first_login_at == null) {
                        ctx._source.first_login_at = params.doc.first_login_at;
                    }
                    ctx._source.last_login_at = params.doc.last_login_at;
                    ctx._source.primary_department_id = params.doc.primary_department_id;
                    ctx._source.primary_department_name = params.doc.primary_department_name;
                    ctx._source.department_source = params.doc.department_source;
                    ctx._source.projection_updated_at = params.doc.projection_updated_at;
                """,
                "params": {"doc": base_document},
            },
            upsert=base_document,
            retry_on_conflict=3,
        )
        return DailyParticipationRecord(
            es_id=cls.build_es_id(
                normalized_tenant_id, local_date, int(user_id)
            ),
            **base_document,
        )

    def upsert_roster_records_sync(
        self,
        records: list[DailyParticipationRecord],
    ) -> None:
        """Refresh roster data while preserving the login-event department."""
        if not records:
            return
        self.ensure_index_exists_sync()
        actions = []
        for record in records:
            document = record.model_dump(
                exclude={
                    "es_id",
                    "logged_in",
                    "login_count",
                    "last_login_at",
                }
            )
            actions.append(
                {
                    "_op_type": "update",
                    "_index": self._index_name,
                    "_id": record.es_id,
                    "script": {
                        "lang": "painless",
                        "source": """
                            boolean alreadyLoggedIn =
                                ctx._source.logged_in != null && ctx._source.logged_in;
                            for (entry in params.doc.entrySet()) {
                                if (
                                    alreadyLoggedIn &&
                                    (
                                        entry.getKey() == 'primary_department_id' ||
                                        entry.getKey() == 'primary_department_name' ||
                                        entry.getKey() == 'department_source' ||
                                        entry.getKey() == 'first_login_at'
                                    )
                                ) {
                                    continue;
                                }
                                ctx._source[entry.getKey()] = entry.getValue();
                            }
                        """,
                        "params": {"doc": document},
                    },
                    "upsert": record.model_dump(exclude={"es_id"}),
                }
            )
        helpers.bulk(self._es_client_sync, actions)

    def upsert_login_backfill_records_sync(
        self,
        records: list[DailyParticipationRecord],
    ) -> None:
        """Idempotently restore aggregated historical login facts."""
        if not records:
            return
        self.ensure_index_exists_sync()
        actions = []
        for record in records:
            document = record.model_dump(exclude={"es_id"})
            actions.append(
                {
                    "_op_type": "update",
                    "_index": self._index_name,
                    "_id": record.es_id,
                    "script": {
                        "lang": "painless",
                        "source": """
                            boolean hasEventTimeDepartment =
                                ctx._source.department_source == 'event_time';
                            for (entry in params.doc.entrySet()) {
                                if (
                                    hasEventTimeDepartment &&
                                    (
                                        entry.getKey() == 'primary_department_id' ||
                                        entry.getKey() == 'primary_department_name' ||
                                        entry.getKey() == 'department_source'
                                    )
                                ) {
                                    continue;
                                }
                                ctx._source[entry.getKey()] = entry.getValue();
                            }
                        """,
                        "params": {"doc": document},
                    },
                    "upsert": document,
                }
            )
        helpers.bulk(self._es_client_sync, actions)

    def delete_stale_roster_records_sync(
        self,
        *,
        local_date: str,
        sync_run_id: str,
        sync_started_at: int,
    ) -> int:
        """Remove employees no longer in today's active roster."""
        result = self.delete_by_query_sync(
            {
                "bool": {
                    "filter": [
                        {"term": {"local_date": local_date}},
                        {"range": {"projection_updated_at": {"lt": sync_started_at}}},
                    ],
                    "must_not": [{"term": {"sync_run_id": sync_run_id}}],
                }
            },
            refresh=True,
            conflicts="proceed",
        )
        return int(result.get("deleted", 0))

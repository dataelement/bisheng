from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from elasticsearch import helpers
from loguru import logger
from sqlalchemy import and_
from sqlmodel import select

from bisheng.common.constants.enums.telemetry import BaseTelemetryTypeEnum
from bisheng.common.services import telemetry_service
from bisheng.core.context.tenant import bypass_tenant_filter
from bisheng.core.database import get_sync_db_session
from bisheng.core.logger import trace_id_var
from bisheng.core.search.elasticsearch.manager import (
    get_statistics_es_connection_sync,
)
from bisheng.database.models.department import Department, UserDepartmentDao
from bisheng.database.models.qa_expert import Question
from bisheng.database.models.tenant import UserTenant
from bisheng.telemetry.domain.mid_table.realtime_qa_question import (
    QA_TYPE_LABELS,
    RealtimeQaQuestionFact,
    RealtimeQaQuestionRecord,
)
from bisheng.user.domain.models.user import User
from bisheng.utils import generate_uuid
from bisheng.worker.main import bisheng_celery

DEFAULT_LOOKBACK_DAYS = 2
PAGE_SIZE = 1000


def _parse_datetime(value: str | None, fallback: datetime | None) -> datetime | None:
    if not value:
        return fallback
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone().replace(tzinfo=None)
    return parsed


def _resolve_window(
    *,
    start_date: str | None,
    end_date: str | None,
    full_history: bool,
) -> tuple[datetime | None, datetime]:
    now = datetime.now()
    default_start = None if full_history else now - timedelta(days=DEFAULT_LOOKBACK_DAYS)
    start = _parse_datetime(start_date, default_start)
    end = _parse_datetime(end_date, now)
    if end is None:
        end = now
    if start is not None and start > end:
        raise ValueError(f"start_date {start.isoformat()} is after end_date {end.isoformat()}")
    return start, end


def _optional_int(value: Any) -> int | None:
    try:
        return int(value) if value is not None and str(value).strip() else None
    except (TypeError, ValueError):
        return None


def _department_fields(
    department: Department | None,
) -> tuple[int | None, str | None]:
    if department is None:
        return None, None
    return int(department.id), department.name


def _build_record(
    *,
    tenant_id: int,
    question_id: str,
    qa_type: str,
    timestamp: int,
    user_id: int,
    user_name: str,
    department: Department | None,
    scene: str,
    source_app: str,
    space_id: Any = None,
    file_id: Any = None,
    conversation_id: str | None = None,
    business_domain_code: str | None = None,
    projection_updated_at: int,
) -> RealtimeQaQuestionRecord:
    department_id, department_name = _department_fields(department)
    return RealtimeQaQuestionRecord(
        es_id=f"qa_{tenant_id}_{qa_type}_{question_id}",
        tenant_id=tenant_id,
        timestamp=timestamp,
        user_id=user_id,
        user_name=user_name or str(user_id),
        user_group_infos=[],
        user_role_infos=[],
        user_department_infos=[],
        question_id=question_id,
        qa_type=qa_type,
        qa_type_name=QA_TYPE_LABELS[qa_type],
        scene=scene,
        source_app=source_app,
        primary_department_id=department_id,
        primary_department_name=department_name,
        department_source="current_primary_backfill",
        space_id=_optional_int(space_id),
        file_id=_optional_int(file_id),
        conversation_id=conversation_id,
        business_domain_code=business_domain_code,
        projection_updated_at=projection_updated_at,
    )


def _get_expert_question_rows(
    *,
    offset: int,
    limit: int,
    start: datetime | None,
    end: datetime,
) -> list[tuple[Question, User | None, int | None]]:
    active_tenant_join = and_(
        UserTenant.user_id == Question.user_id,
        UserTenant.status == "active",
        UserTenant.is_active == 1,
    )
    statement = (
        select(Question, User, UserTenant.tenant_id)
        .outerjoin(User, User.user_id == Question.user_id)
        .outerjoin(UserTenant, active_tenant_join)
        .where(Question.created_at <= end)
        .order_by(Question.id.asc())
        .offset(offset)
        .limit(limit)
    )
    if start is not None:
        statement = statement.where(Question.created_at >= start)
    with bypass_tenant_filter():
        with get_sync_db_session() as session:
            return list(session.exec(statement).all())


def _sync_expert_questions(
    fact: RealtimeQaQuestionFact,
    *,
    start: datetime | None,
    end: datetime,
    projection_updated_at: int,
) -> int:
    offset = 0
    synced = 0
    while True:
        rows = _get_expert_question_rows(
            offset=offset,
            limit=PAGE_SIZE,
            start=start,
            end=end,
        )
        if not rows:
            break
        offset += len(rows)
        user_ids = [int(question.user_id) for question, _, _ in rows]
        with bypass_tenant_filter():
            departments = UserDepartmentDao.get_primary_department_map_by_user_ids(user_ids)
        records = [
            _build_record(
                tenant_id=int(tenant_id or 1),
                question_id=str(question.id),
                qa_type="expert",
                timestamp=int(question.created_at.timestamp()),
                user_id=int(question.user_id),
                user_name=(user.user_name if user is not None else question.created_by or str(question.user_id)),
                department=departments.get(int(question.user_id)),
                scene="expert_question",
                source_app="expert_qa",
                business_domain_code=question.business_domain,
                projection_updated_at=projection_updated_at,
            )
            for question, user, tenant_id in rows
        ]
        fact.insert_records_sync(records)
        synced += len(records)
    return synced


def _portal_record_from_hit(
    hit: dict[str, Any],
    *,
    departments: dict[int, Department],
    projection_updated_at: int,
) -> RealtimeQaQuestionRecord | None:
    source = hit.get("_source") or {}
    event_data = source.get("event_data") or {}
    user_context = source.get("user_context") or {}
    user_id = _optional_int(user_context.get("user_id"))
    if user_id is None:
        return None

    scene = str(event_data.get("portal_qa_scene") or "document_qa")
    qa_type = "smart" if scene == "smart_qa" else "document"
    question_id = str(event_data.get("portal_qa_question_id") or source.get("event_id") or hit.get("_id") or "").strip()
    if not question_id:
        return None

    tenant_id = _optional_int(source.get("tenant_id")) or 1
    timestamp = _optional_int(source.get("timestamp")) or projection_updated_at
    return _build_record(
        tenant_id=tenant_id,
        question_id=question_id,
        qa_type=qa_type,
        timestamp=timestamp,
        user_id=user_id,
        user_name=str(user_context.get("user_name") or user_id),
        department=departments.get(user_id),
        scene=scene,
        source_app=str(event_data.get("portal_qa_source_app") or "shougang_portal"),
        space_id=event_data.get("portal_qa_space_id"),
        file_id=event_data.get("portal_qa_file_id"),
        conversation_id=event_data.get("portal_qa_conversation_id"),
        projection_updated_at=projection_updated_at,
    )


def _flush_portal_hits(
    fact: RealtimeQaQuestionFact,
    hits: list[dict[str, Any]],
    *,
    projection_updated_at: int,
) -> int:
    user_ids = [
        user_id
        for hit in hits
        if (user_id := _optional_int(((hit.get("_source") or {}).get("user_context") or {}).get("user_id"))) is not None
    ]
    with bypass_tenant_filter():
        departments = UserDepartmentDao.get_primary_department_map_by_user_ids(user_ids)
    records = [
        record
        for hit in hits
        if (
            record := _portal_record_from_hit(
                hit,
                departments=departments,
                projection_updated_at=projection_updated_at,
            )
        )
        is not None
    ]
    if records:
        fact.insert_records_sync(records)
    return len(records)


def _sync_portal_questions(
    fact: RealtimeQaQuestionFact,
    *,
    start: datetime | None,
    end: datetime,
    projection_updated_at: int,
) -> int:
    client = get_statistics_es_connection_sync()
    if not client.indices.exists(index=telemetry_service.index_name):
        return 0

    filters: list[dict[str, Any]] = [
        {"term": {"event_type": BaseTelemetryTypeEnum.PORTAL_QA.value}},
        {
            "range": {
                "timestamp": {
                    **({"gte": int(start.timestamp())} if start is not None else {}),
                    "lte": int(end.timestamp()),
                    "format": "epoch_second",
                }
            }
        },
    ]
    hits = helpers.scan(
        client=client,
        index=telemetry_service.index_name,
        query={"query": {"bool": {"filter": filters}}},
        size=PAGE_SIZE,
    )
    batch: list[dict[str, Any]] = []
    synced = 0
    for hit in hits:
        batch.append(hit)
        if len(batch) >= PAGE_SIZE:
            synced += _flush_portal_hits(
                fact,
                batch,
                projection_updated_at=projection_updated_at,
            )
            batch = []
    if batch:
        synced += _flush_portal_hits(
            fact,
            batch,
            projection_updated_at=projection_updated_at,
        )
    return synced


@bisheng_celery.task()
def sync_mid_realtime_qa_question_fact(
    start_date: str | None = None,
    end_date: str | None = None,
    full_history: bool = False,
) -> dict[str, int]:
    """Repair missed real-time QA projections from durable source records."""
    trace_id_var.set(f"sync_mid_realtime_qa_question_fact_task_{generate_uuid()}")
    start, end = _resolve_window(
        start_date=start_date,
        end_date=end_date,
        full_history=full_history,
    )
    projection_updated_at = int(datetime.now().timestamp())
    fact = RealtimeQaQuestionFact()
    expert_count = _sync_expert_questions(
        fact,
        start=start,
        end=end,
        projection_updated_at=projection_updated_at,
    )
    portal_count = _sync_portal_questions(
        fact,
        start=start,
        end=end,
        projection_updated_at=projection_updated_at,
    )
    logger.info(
        "Reconciled real-time QA facts. start={}, end={}, expert={}, portal={}",
        start.isoformat() if start else "beginning",
        end.isoformat(),
        expert_count,
        portal_count,
    )
    return {"expert": expert_count, "portal": portal_count}

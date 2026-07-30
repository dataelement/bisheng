from datetime import date, datetime, timedelta
from typing import Any, List

from elasticsearch import helpers
from loguru import logger
from sqlalchemy import exists, or_
from sqlmodel import select

from bisheng.api.services.workflow import WorkFlowService
from bisheng.common.constants.enums.telemetry import (
    ApplicationTypeEnum,
    BaseTelemetryTypeEnum,
)
from bisheng.common.schemas.telemetry.base_telemetry_schema import UserGroupInfo, UserRoleInfo, UserDepartmentInfo
from bisheng.common.services import telemetry_service
from bisheng.common.services.config_service import settings
from bisheng.core.context.tenant import bypass_tenant_filter
from bisheng.core.database import get_sync_db_session
from bisheng.core.logger import trace_id_var
from bisheng.core.search.elasticsearch.manager import (
    get_statistics_es_connection_sync,
)
from bisheng.database.models.department import Department, UserDepartmentDao
from bisheng.database.models.tenant import Tenant, UserTenant
from bisheng.database.models.flow import FlowType
from bisheng.knowledge.domain.models.knowledge import Knowledge, KnowledgeTypeEnum
from bisheng.knowledge.domain.models.knowledge_document_version import KnowledgeDocumentVersion
from bisheng.knowledge.domain.models.department_knowledge_space import (
    DepartmentKnowledgeSpace,
)
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile, KnowledgeFileStatus, FileType
from bisheng.knowledge.domain.models.knowledge_space_scope import (
    KnowledgeSpaceLevelEnum,
    KnowledgeSpaceOwnerTypeEnum,
    KnowledgeSpaceScopeDao,
)
from bisheng.knowledge.domain.services.knowledge_service import KnowledgeService
from bisheng.knowledge.domain.services.file_classification_label_service import (
    FileClassificationLabelService,
)
from bisheng.telemetry.domain.mid_table.app_increment import AppIncrement, AppIncrementRecord
from bisheng.telemetry.domain.mid_table.base import BaseMidTable
from bisheng.telemetry.domain.mid_table.daily_participation import (
    CHINA_STANDARD_TIME,
    DailyParticipationFact,
    DailyParticipationRecord,
    aggregate_historical_login_hits,
    participation_day,
)
from bisheng.telemetry.domain.mid_table.knowledge_increment import KnowledgeIncrement, KnowledgeIncrementRecord
from bisheng.telemetry.domain.mid_table.knowledge_space_content import KnowledgeSpaceContentStat
from bisheng.telemetry.domain.mid_table.user_increment import UserIncrement, UserIncrementRecord
from bisheng.telemetry.domain.mid_table.user_interact import UserInteract, UserInteractRecord
from bisheng.user.domain.services.user import UserService
from bisheng.user.domain.models.user import User
from bisheng.utils import generate_uuid
from bisheng.worker.main import bisheng_celery


def get_yesterday_date_range(mid_table: BaseMidTable, start_date: str = None, end_date: str = None) -> (datetime,
                                                                                                        datetime):
    if start_date is None or end_date is None:
        # default to yesterday's date
        now = datetime.now()
        yesterday = now - timedelta(days=1)
        start_date = datetime(year=yesterday.year, month=yesterday.month, day=yesterday.day, hour=0, minute=0, second=0)
        end_date = datetime(year=now.year, month=now.month, day=now.day, hour=0, minute=0, second=0)
    else:
        start_date = datetime.fromisoformat(start_date)
        end_date = datetime.fromisoformat(end_date)

    lastest_time = mid_table.get_latest_record_time_sync()
    if lastest_time:
        start_date = datetime.fromtimestamp(lastest_time) + timedelta(seconds=1)
    if end_date < start_date:
        logger.error(f"end_date {end_date} is before start_date {start_date}")
        return None, None
    return start_date, end_date


def convert_flow_type(flow_type: int) -> ApplicationTypeEnum:
    flow_type_mapping = {
        FlowType.ASSISTANT.value: ApplicationTypeEnum.ASSISTANT,
        FlowType.WORKFLOW.value: ApplicationTypeEnum.WORKFLOW,
    }
    return flow_type_mapping.get(flow_type, ApplicationTypeEnum.UNKNOWN)


@bisheng_celery.task()
def sync_mid_user_increment(start_date: str = None, end_date: str = None):
    trace_id_var.set(f"sync_mid_user_increment_task_{generate_uuid()}")
    mid_table = UserIncrement()
    start_date, end_date = get_yesterday_date_range(mid_table, start_date, end_date)
    if start_date is None or end_date is None:
        return

    logger.info(f"Syncing mid_user_increment from {start_date} to {end_date}")
    # Here would be the logic to fetch data from the source and insert into mid_user_increment
    page, page_size = 1, 1000

    while True:
        user_list = UserService.get_user_all_info(start_time=start_date, end_time=end_date,
                                                  page=page, page_size=page_size)
        page += 1
        if not user_list:
            break
        records = []
        for user in user_list:
            records.append(UserIncrementRecord(
                es_id=f"user_{user.user_id}",
                user_id=user.user_id,
                user_name=user.user_name,
                user_group_infos=[UserGroupInfo(user_group_id=group.id, user_group_name=group.group_name)
                                  for group in user.groups],
                user_role_infos=[UserRoleInfo(role_id=role.id, role_name=role.role_name, group_id=role.group_id)
                                 for role in user.roles],
                user_department_infos=[UserDepartmentInfo(department_id=dept.id, department_name=dept.name)
                                       for dept in getattr(user, 'departments', []) or []],
                timestamp=int(user.create_time.timestamp())
            ))
        mid_table.insert_records_sync(records)

    # This is a placeholder for the actual data synchronization logic
    logger.info(f"Successfully synced mid_user_increment from {start_date} to {end_date}")


def _get_active_participation_users(
    offset: int,
    limit: int,
) -> list[tuple[User, int]]:
    """Page the current employee roster across active leaf tenants."""
    with bypass_tenant_filter():
        with get_sync_db_session() as session:
            if settings.multi_tenant.enabled:
                statement = (
                    select(User, UserTenant.tenant_id)
                    .join(UserTenant, UserTenant.user_id == User.user_id)
                    .join(Tenant, Tenant.id == UserTenant.tenant_id)
                    .where(
                        User.delete == 0,
                        UserTenant.status == "active",
                        UserTenant.is_active == 1,
                        Tenant.status == "active",
                    )
                    .order_by(
                        User.user_id.asc(),
                        UserTenant.tenant_id.asc(),
                    )
                    .offset(offset)
                    .limit(limit)
                )
                return [
                    (user, int(tenant_id))
                    for user, tenant_id in session.exec(statement).all()
                ]

            statement = (
                select(User)
                .where(User.delete == 0)
                .order_by(User.user_id.asc())
                .offset(offset)
                .limit(limit)
            )
            return [(user, 1) for user in session.exec(statement).all()]


def _reconcile_participation_roster_for_day(
    target_date: date,
    *,
    department_source: str,
) -> dict[str, int | str]:
    local_date, day_timestamp = participation_day(target_date)
    sync_run_id = generate_uuid()
    sync_started_at = int(datetime.now().timestamp())
    mid_table = DailyParticipationFact()
    offset, page_size = 0, 1000
    synced_count = 0

    while True:
        roster_rows = _get_active_participation_users(offset, page_size)
        if not roster_rows:
            break
        offset += len(roster_rows)
        primary_department_map = (
            UserDepartmentDao.get_primary_department_map_by_user_ids(
                [int(user.user_id) for user, _ in roster_rows]
            )
        )
        records = []
        for user, tenant_id in roster_rows:
            department = primary_department_map.get(int(user.user_id))
            records.append(
                DailyParticipationRecord(
                    es_id=DailyParticipationFact.build_es_id(
                        tenant_id, local_date, int(user.user_id)
                    ),
                    tenant_id=tenant_id,
                    timestamp=day_timestamp,
                    user_id=int(user.user_id),
                    user_name=user.user_name,
                    user_group_infos=[],
                    user_role_infos=[],
                    user_department_infos=[],
                    local_date=local_date,
                    active_employee=1,
                    primary_department_id=(
                        int(department.id) if department else None
                    ),
                    primary_department_name=(
                        department.name if department else None
                    ),
                    department_source=department_source,
                    sync_run_id=sync_run_id,
                    projection_updated_at=sync_started_at,
                )
            )
        mid_table.upsert_roster_records_sync(records)
        synced_count += len(records)

    deleted_count = mid_table.delete_stale_roster_records_sync(
        local_date=local_date,
        sync_run_id=sync_run_id,
        sync_started_at=sync_started_at,
    )
    return {
        "local_date": local_date,
        "synced": synced_count,
        "deleted": deleted_count,
    }


@bisheng_celery.task()
def sync_mid_user_daily_participation_fact():
    """Reconcile today's denominator while preserving real-time login counters."""
    DailyParticipationFact.clear_roster_reconcile_scheduled()
    trace_id_var.set(
        f"sync_mid_user_daily_participation_fact_task_{generate_uuid()}"
    )
    today = datetime.now(CHINA_STANDARD_TIME).date()
    result = _reconcile_participation_roster_for_day(
        today,
        department_source="current_roster",
    )
    logger.info(
        "Reconciled daily participation roster. date={}, synced={}, deleted={}",
        result["local_date"],
        result["synced"],
        result["deleted"],
    )
    return result


def _scan_historical_login_events(
    *,
    start_timestamp: int,
    end_timestamp: int,
) -> dict[tuple[int, str, int], dict[str, Any]] | None:
    client = get_statistics_es_connection_sync()
    if not client.indices.exists(index=telemetry_service.index_name):
        return None
    hits = helpers.scan(
        client=client,
        index=telemetry_service.index_name,
        query={
            "_source": [
                "tenant_id",
                "timestamp",
                "user_context.user_id",
                "user_context.user_name",
            ],
            "query": {
                "bool": {
                    "filter": [
                        {
                            "term": {
                                "event_type": (
                                    BaseTelemetryTypeEnum.USER_LOGIN.value
                                )
                            }
                        },
                        {
                            "range": {
                                "timestamp": {
                                    "gte": start_timestamp,
                                    "lt": end_timestamp,
                                    "format": "epoch_second",
                                }
                            }
                        },
                    ]
                }
            },
        },
        size=1000,
    )
    return aggregate_historical_login_hits(hits)


@bisheng_celery.task()
def backfill_mid_user_daily_participation_fact(
    lookback_days: int = 30,
) -> dict[str, int]:
    """Best-effort history using current roster and durable login telemetry."""
    trace_id_var.set(
        f"backfill_mid_user_daily_participation_fact_task_{generate_uuid()}"
    )
    normalized_days = max(1, min(int(lookback_days), 365))
    today = datetime.now(CHINA_STANDARD_TIME).date()
    start_date = today - timedelta(days=normalized_days)
    start_timestamp = participation_day(start_date)[1]
    end_timestamp = participation_day(today)[1]
    aggregates = _scan_historical_login_events(
        start_timestamp=start_timestamp,
        end_timestamp=end_timestamp,
    )
    if aggregates is None:
        logger.info(
            "Skipped participation history backfill because telemetry index is absent."
        )
        return {"days": 0, "roster": 0, "login_facts": 0}

    roster_count = 0
    for day_offset in range(normalized_days):
        result = _reconcile_participation_roster_for_day(
            start_date + timedelta(days=day_offset),
            department_source="current_roster_backfill",
        )
        roster_count += int(result["synced"])

    user_ids = sorted({key[2] for key in aggregates})
    departments = {}
    with bypass_tenant_filter():
        for offset in range(0, len(user_ids), 1000):
            departments.update(
                UserDepartmentDao.get_primary_department_map_by_user_ids(
                    user_ids[offset:offset + 1000]
                )
            )
    projection_updated_at = int(datetime.now().timestamp())
    records = []
    for aggregate in aggregates.values():
        department = departments.get(aggregate["user_id"])
        records.append(
            DailyParticipationRecord(
                es_id=DailyParticipationFact.build_es_id(
                    aggregate["tenant_id"],
                    aggregate["local_date"],
                    aggregate["user_id"],
                ),
                tenant_id=aggregate["tenant_id"],
                timestamp=participation_day(
                    date.fromisoformat(aggregate["local_date"])
                )[1],
                user_id=aggregate["user_id"],
                user_name=aggregate["user_name"],
                user_group_infos=[],
                user_role_infos=[],
                user_department_infos=[],
                local_date=aggregate["local_date"],
                active_employee=1,
                logged_in=True,
                login_count=aggregate["login_count"],
                first_login_at=aggregate["first_login_at"],
                last_login_at=aggregate["last_login_at"],
                primary_department_id=(
                    int(department.id) if department else None
                ),
                primary_department_name=(
                    department.name if department else None
                ),
                department_source="current_primary_backfill",
                projection_updated_at=projection_updated_at,
            )
        )
    fact = DailyParticipationFact()
    for offset in range(0, len(records), 1000):
        fact.upsert_login_backfill_records_sync(records[offset:offset + 1000])

    logger.info(
        "Backfilled participation history. days={}, roster={}, login_facts={}",
        normalized_days,
        roster_count,
        len(records),
    )
    return {
        "days": normalized_days,
        "roster": roster_count,
        "login_facts": len(records),
    }


def get_user_from_ids_with_cache(user_ids: List[int], user_map: dict):
    if user_ids:
        with bypass_tenant_filter():
            user_list = UserService.get_user_all_info(user_ids=user_ids, page=0, page_size=0)
        user_map.update({user.user_id: user for user in user_list})
    return user_map


def _current_primary_file_predicate():
    """Include legacy files and current primary versions, never historical versions."""
    any_version = select(KnowledgeDocumentVersion.id).where(
        KnowledgeDocumentVersion.knowledge_file_id == KnowledgeFile.id
    )
    primary_version = any_version.where(
        KnowledgeDocumentVersion.is_primary == True  # noqa: E712
    )
    return or_(~exists(any_version), exists(primary_version))


def _get_success_space_file_rows(page: int, page_size: int):
    statement = (
        select(KnowledgeFile, Knowledge)
        .join(Knowledge, KnowledgeFile.knowledge_id == Knowledge.id)
        .where(
            Knowledge.type == KnowledgeTypeEnum.SPACE.value,
            KnowledgeFile.file_type == FileType.FILE.value,
            KnowledgeFile.status == KnowledgeFileStatus.SUCCESS.value,
            _current_primary_file_predicate(),
        )
        .order_by(KnowledgeFile.id.asc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    with bypass_tenant_filter():
        with get_sync_db_session() as session:
            return session.exec(statement).all()


def _get_success_space_file_rows_by_space_id(space_id: int, page: int, page_size: int):
    statement = (
        select(KnowledgeFile, Knowledge)
        .join(Knowledge, KnowledgeFile.knowledge_id == Knowledge.id)
        .where(
            Knowledge.id == space_id,
            Knowledge.type == KnowledgeTypeEnum.SPACE.value,
            KnowledgeFile.file_type == FileType.FILE.value,
            KnowledgeFile.status == KnowledgeFileStatus.SUCCESS.value,
            _current_primary_file_predicate(),
        )
        .order_by(KnowledgeFile.id.asc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    with bypass_tenant_filter():
        with get_sync_db_session() as session:
            return session.exec(statement).all()


def _get_knowledge_space_content_rows_by_file_ids(file_ids: List[int]):
    if not file_ids:
        return []
    statement = (
        select(KnowledgeFile, Knowledge)
        .join(Knowledge, KnowledgeFile.knowledge_id == Knowledge.id)
        .where(
            KnowledgeFile.id.in_(file_ids),
            _current_primary_file_predicate(),
        )
    )
    with bypass_tenant_filter():
        with get_sync_db_session() as session:
            return session.exec(statement).all()


def _is_department_bound_space_scope(scope) -> bool:
    if scope is None:
        return False
    level = str(getattr(scope.level, "value", scope.level))
    return level in {
        KnowledgeSpaceLevelEnum.DEPARTMENT.value,
        KnowledgeSpaceLevelEnum.TEAM_KS.value,
    }


def _get_knowledge_space_department_map(
    space_ids: list[int],
    space_scope_map: dict,
) -> dict[int, Department | None]:
    """Resolve departments only for department and clinic knowledge spaces."""
    normalized_space_ids = sorted({int(space_id) for space_id in space_ids if space_id})
    result: dict[int, Department | None] = dict.fromkeys(normalized_space_ids)
    if not normalized_space_ids:
        return result
    eligible_space_ids = [
        space_id
        for space_id in normalized_space_ids
        if _is_department_bound_space_scope(space_scope_map.get(space_id))
    ]
    if not eligible_space_ids:
        return result

    with bypass_tenant_filter():
        with get_sync_db_session() as session:
            binding_rows = session.exec(
                select(DepartmentKnowledgeSpace.space_id, Department)
                .join(
                    Department,
                    Department.id == DepartmentKnowledgeSpace.department_id,
                )
                .where(
                    DepartmentKnowledgeSpace.space_id.in_(eligible_space_ids),
                )
            ).all()
            for space_id, department in binding_rows:
                result[int(space_id)] = department

            scope_department_ids = set()
            for space_id in eligible_space_ids:
                if result[space_id] is not None:
                    continue
                scope = space_scope_map.get(space_id)
                if (
                    scope is not None
                    and str(getattr(scope.level, "value", scope.level))
                    == KnowledgeSpaceLevelEnum.DEPARTMENT.value
                    and str(getattr(scope.owner_type, "value", scope.owner_type))
                    == KnowledgeSpaceOwnerTypeEnum.DEPARTMENT.value
                ):
                    scope_department_ids.add(int(scope.owner_id))

            if scope_department_ids:
                departments = session.exec(
                    select(Department).where(
                        Department.id.in_(scope_department_ids),
                    )
                ).all()
                department_map = {
                    int(department.id): department for department in departments
                }
                for space_id in eligible_space_ids:
                    if result[space_id] is not None:
                        continue
                    scope = space_scope_map.get(space_id)
                    if scope is not None:
                        result[space_id] = department_map.get(int(scope.owner_id))
    return result


def _build_knowledge_space_content_records(
    rows,
    user_map: dict,
    *,
    sync_run_id: str = None,
    space_scope_map: dict | None = None,
    space_department_map: dict | None = None,
    primary_department_map: dict | None = None,
    category_label_cache: dict | None = None,
):
    if not rows:
        return [], user_map
    space_scope_map = space_scope_map if space_scope_map is not None else {}
    space_department_map = (
        space_department_map if space_department_map is not None else {}
    )
    primary_department_map = (
        primary_department_map if primary_department_map is not None else {}
    )
    category_label_cache = (
        category_label_cache if category_label_cache is not None else {}
    )
    user_ids = {
        int(file_record.user_id)
        for file_record, _ in rows
        if file_record.user_id and int(file_record.user_id) not in user_map
    }
    user_map = get_user_from_ids_with_cache(list(user_ids), user_map)

    space_ids = sorted({int(space.id) for _, space in rows if getattr(space, "id", None)})
    missing_space_ids = [space_id for space_id in space_ids if space_id not in space_scope_map]
    if missing_space_ids:
        space_scope_map.update(KnowledgeSpaceScopeDao.get_map_by_space_ids(missing_space_ids))
    missing_space_department_ids = [
        space_id for space_id in space_ids if space_id not in space_department_map
    ]
    if missing_space_department_ids:
        space_department_map.update(
            _get_knowledge_space_department_map(
                missing_space_department_ids,
                space_scope_map,
            )
        )

    all_user_ids = sorted(
        {int(file_record.user_id) for file_record, _ in rows if file_record.user_id}
    )
    missing_primary_user_ids = [
        user_id for user_id in all_user_ids if user_id not in primary_department_map
    ]
    if missing_primary_user_ids:
        primary_department_map.update(
            UserDepartmentDao.get_primary_department_map_by_user_ids(
                missing_primary_user_ids
            )
        )

    records = []
    for file_record, space in rows:
        uploader = user_map.get(int(file_record.user_id or 0))
        tenant_id = int(
            getattr(file_record, "tenant_id", None)
            or getattr(space, "tenant_id", None)
            or 1
        )
        if tenant_id not in category_label_cache:
            category_label_cache[tenant_id] = (
                FileClassificationLabelService.get_label_lookup_for_tenant(
                    tenant_id
                )
            )
        category_labels, subcategory_labels = category_label_cache[tenant_id]
        scope = space_scope_map.get(int(space.id))
        records.append(
            KnowledgeSpaceContentStat.build_file_record(
                file_record=file_record,
                space=space,
                uploader=uploader,
                space_level=getattr(scope, "level", None),
                space_department=space_department_map.get(int(space.id)),
                primary_department=primary_department_map.get(
                    int(file_record.user_id or 0)
                ),
                file_category_labels=category_labels,
                file_subcategory_labels=subcategory_labels,
                sync_run_id=sync_run_id,
            )
        )
    return records, user_map


def _is_file_content_stat_visible(file_record: KnowledgeFile, space: Knowledge) -> bool:
    return (
        space.type == KnowledgeTypeEnum.SPACE.value
        and file_record.file_type == FileType.FILE.value
        and file_record.status == KnowledgeFileStatus.SUCCESS.value
    )


@bisheng_celery.task()
def sync_mid_knowledge_space_content_stat(start_date: str = None, end_date: str = None):
    trace_id_var.set(f"sync_mid_knowledge_space_content_stat_task_{generate_uuid()}")
    logger.info("Syncing mid_knowledge_space_content_stat file records...")

    mid_table = KnowledgeSpaceContentStat()
    sync_run_id = generate_uuid()
    page, page_size = 1, 1000
    user_map = {}
    space_scope_map = {}
    space_department_map = {}
    primary_department_map = {}
    category_label_cache = {}
    synced_count = 0

    while True:
        rows = _get_success_space_file_rows(page, page_size)
        page += 1
        if not rows:
            break

        records, user_map = _build_knowledge_space_content_records(
            rows,
            user_map,
            sync_run_id=sync_run_id,
            space_scope_map=space_scope_map,
            space_department_map=space_department_map,
            primary_department_map=primary_department_map,
            category_label_cache=category_label_cache,
        )

        mid_table.insert_records_sync(records)
        synced_count += len(records)

    deleted_count = mid_table.delete_stale_file_records_sync(sync_run_id)
    logger.info(
        "Successfully synced mid_knowledge_space_content_stat file records. "
        "synced={}, deleted_stale={}",
        synced_count,
        deleted_count,
    )


@bisheng_celery.task()
def sync_pending_knowledge_space_content_stat():
    trace_id_var.set(f"sync_pending_knowledge_space_content_stat_task_{generate_uuid()}")
    KnowledgeSpaceContentStat.clear_scheduled_sync()
    if not KnowledgeSpaceContentStat.acquire_lock_sync():
        KnowledgeSpaceContentStat._schedule_pending_sync(
            countdown=KnowledgeSpaceContentStat.SCHEDULE_DELAY_SECONDS
        )
        return

    try:
        mid_table = KnowledgeSpaceContentStat()
        user_map = {}
        space_scope_map = {}
        space_department_map = {}
        primary_department_map = {}
        category_label_cache = {}

        file_ids = KnowledgeSpaceContentStat.peek_pending_file_ids_sync(
            KnowledgeSpaceContentStat.FILE_BATCH_SIZE
        )
        if file_ids:
            rows = _get_knowledge_space_content_rows_by_file_ids(file_ids)
            row_by_file_id = {int(file_record.id): (file_record, space) for file_record, space in rows}
            visible_rows = []
            stale_file_ids = []
            for file_id in file_ids:
                row = row_by_file_id.get(int(file_id))
                if not row:
                    stale_file_ids.append(file_id)
                    continue
                file_record, space = row
                if _is_file_content_stat_visible(file_record, space):
                    visible_rows.append(row)
                else:
                    stale_file_ids.append(file_id)

            records, user_map = _build_knowledge_space_content_records(
                visible_rows,
                user_map,
                space_scope_map=space_scope_map,
                space_department_map=space_department_map,
                primary_department_map=primary_department_map,
                category_label_cache=category_label_cache,
            )
            if records:
                mid_table.insert_records_sync(records)
            if stale_file_ids:
                mid_table.delete_file_records_sync(stale_file_ids)
            KnowledgeSpaceContentStat.ack_pending_file_ids_sync(file_ids)

            logger.info(
                "Synced pending knowledge space content file stats. upserted={}, deleted={}",
                len(records),
                len(stale_file_ids),
            )

        preview_payloads = KnowledgeSpaceContentStat.peek_pending_preview_payloads_sync(
            KnowledgeSpaceContentStat.PREVIEW_BATCH_SIZE
        )
        if preview_payloads:
            preview_records = []
            valid_payloads = []
            invalid_payloads = []
            for payload in preview_payloads:
                record = KnowledgeSpaceContentStat.deserialize_preview_payload(payload)
                if record is None:
                    invalid_payloads.append(payload)
                    continue
                preview_records.append(record)
                valid_payloads.append(payload)
            if invalid_payloads:
                KnowledgeSpaceContentStat.ack_pending_preview_payloads_sync(invalid_payloads)
            if preview_records:
                mid_table.insert_records_sync(preview_records)
                KnowledgeSpaceContentStat.ack_pending_preview_payloads_sync(valid_payloads)
            logger.info(
                "Synced pending knowledge space preview stats. upserted={}, invalid={}",
                len(preview_records),
                len(invalid_payloads),
            )

        space_rename_ids = KnowledgeSpaceContentStat.peek_pending_space_rename_ids_sync()
        for space_id in space_rename_ids:
            page, page_size = 1, 500
            space_synced_count = 0
            while True:
                rows = _get_success_space_file_rows_by_space_id(space_id, page, page_size)
                page += 1
                if not rows:
                    break
                records, user_map = _build_knowledge_space_content_records(
                    rows,
                    user_map,
                    space_scope_map=space_scope_map,
                    space_department_map=space_department_map,
                    primary_department_map=primary_department_map,
                    category_label_cache=category_label_cache,
                )
                if records:
                    mid_table.insert_records_sync(records)
                    space_synced_count += len(records)
            KnowledgeSpaceContentStat.ack_pending_space_rename_ids_sync([space_id])
            logger.info(
                "Synced pending knowledge space rename content stats. space_id={}, upserted={}",
                space_id,
                space_synced_count,
            )

        space_delete_ids = KnowledgeSpaceContentStat.peek_pending_space_delete_ids_sync()
        if space_delete_ids:
            deleted_count = mid_table.delete_space_file_records_sync(space_delete_ids)
            KnowledgeSpaceContentStat.ack_pending_space_delete_ids_sync(space_delete_ids)
            logger.info(
                "Deleted pending knowledge space content stats. space_ids={}, deleted={}",
                space_delete_ids,
                deleted_count,
            )
    except Exception:
        logger.exception("Failed to sync pending knowledge space content stats.")
    finally:
        KnowledgeSpaceContentStat.release_lock_sync()
        if KnowledgeSpaceContentStat.has_pending_sync():
            KnowledgeSpaceContentStat.schedule_pending_sync_now()


@bisheng_celery.task()
def sync_mid_app_increment(start_date: str = None, end_date: str = None):
    # Placeholder for syncing mid_app_increment table
    trace_id_var.set(f"sync_mid_app_increment_task_{generate_uuid()}")
    logger.info("Syncing mid_app_increment table...")

    mid_table = AppIncrement()
    start_date, end_date = get_yesterday_date_range(mid_table, start_date, end_date)
    if start_date is None or end_date is None:
        return

    logger.info(f"Syncing mid_app_increment from {start_date} to {end_date}")

    page, page_size = 1, 1000
    user_map = {}
    while True:
        app_list = WorkFlowService.get_all_apps_by_time_range_sync(start_time=start_date, end_time=end_date, page=page,
                                                                   page_size=page_size)
        page += 1
        if not app_list:
            break
        records = []
        user_ids = set()
        for app in app_list:
            if app['user_id'] not in user_map:
                user_ids.add(app['user_id'])
        user_map = get_user_from_ids_with_cache(list(user_ids), user_map)

        for app in app_list:
            user = user_map.get(app['user_id'], None)
            records.append(AppIncrementRecord(
                es_id=f"app_{app['id']}",
                user_id=app['user_id'],
                user_name=user.user_name if user else "",
                user_group_infos=[UserGroupInfo(user_group_id=group.id, user_group_name=group.group_name)
                                  for group in user.groups] if user else [],
                user_role_infos=[UserRoleInfo(role_id=role.id, role_name=role.role_name, group_id=role.group_id)
                                 for role in user.roles] if user else [],
                user_department_infos=[UserDepartmentInfo(department_id=dept.id, department_name=dept.name)
                                       for dept in getattr(user, 'departments', []) or []] if user else [],
                app_id=app['id'],
                app_name=app['name'],
                app_type=convert_flow_type(app['flow_type']),
                timestamp=int(app['create_time'].timestamp())
            ))
        mid_table.insert_records_sync(records)

    # Implement the actual logic here
    logger.info("Successfully synced mid_app_increment table.")


@bisheng_celery.task()
def sync_mid_knowledge_increment(start_date: str = None, end_date: str = None):
    # Placeholder for syncing mid_knowledge_increment table
    trace_id_var.set(f"sync_mid_knowledge_increment_task_{generate_uuid()}")
    logger.info("Syncing mid_knowledge_increment table...")
    mid_table = KnowledgeIncrement()
    start_date, end_date = get_yesterday_date_range(mid_table, start_date, end_date)
    if start_date is None or end_date is None:
        return
    logger.info(f"Syncing mid_knowledge_increment from {start_date} to {end_date}")

    page, page_size = 1, 1000
    user_map = {}
    while True:
        knowledge_list = KnowledgeService.get_all_knowledge_by_time_range(start_date, end_date, page=page,
                                                                          page_size=page_size)
        page += 1
        if not knowledge_list:
            break
        user_ids = set()
        for knowledge in knowledge_list:
            if knowledge.user_id not in user_map:
                user_ids.add(knowledge.user_id)
        user_map = get_user_from_ids_with_cache(list(user_ids), user_map)

        records = []
        for knowledge in knowledge_list:
            user = user_map.get(knowledge.user_id, None)
            records.append(KnowledgeIncrementRecord(
                es_id=f"knowledge_{knowledge.id}",
                user_id=knowledge.user_id,
                user_name=user.user_name if user else "",
                user_group_infos=[UserGroupInfo(user_group_id=group.id, user_group_name=group.group_name)
                                  for group in user.groups] if user else [],
                user_role_infos=[UserRoleInfo(role_id=role.id, role_name=role.role_name, group_id=role.group_id)
                                 for role in user.roles] if user else [],
                user_department_infos=[UserDepartmentInfo(department_id=dept.id, department_name=dept.name)
                                       for dept in getattr(user, 'departments', []) or []] if user else [],
                knowledge_id=knowledge.id,
                knowledge_name=knowledge.name,
                knowledge_type=knowledge.type,
                timestamp=int(knowledge.create_time.timestamp())
            ))
        mid_table.insert_records_sync(records)
    # Implement the actual logic here
    logger.info("Successfully synced mid_knowledge_increment table.")


@bisheng_celery.task()
def sync_mid_user_interact_dtl(start_date: str = None, end_date: str = None):
    # Placeholder for syncing mid_user_interact_dtl table
    trace_id_var.set(f"sync_mid_user_interact_dtl_task_{generate_uuid()}")
    logger.info("Syncing mid_user_interact_dtl table...")
    mid_table = UserInteract()
    start_date, end_date = get_yesterday_date_range(mid_table, start_date, end_date)
    if start_date is None or end_date is None:
        return

    page, page_size = 1, 1000
    while True:
        result = mid_table.get_records_by_time_range_sync(start_time=int(start_date.timestamp()),
                                                          end_time=int(end_date.timestamp()),
                                                          page=page,
                                                          page_size=page_size)
        page += 1
        if not result:
            break
        records = []
        for record in result:
            es_id = record['_id']
            record = record['_source']
            records.append(UserInteractRecord(
                es_id=es_id,
                user_id=record['user_context']['user_id'],
                user_name=record['user_context']['user_name'],
                user_group_infos=[UserGroupInfo(user_group_id=group['user_group_id'],
                                                user_group_name=group['user_group_name'])
                                  for group in record['user_context'].get('user_group_infos', [])],
                user_role_infos=[UserRoleInfo(role_id=role['role_id'],
                                              role_name=role['role_name'],
                                              group_id=role.get('group_id', 0))
                                 for role in record['user_context'].get('user_role_infos', [])],
                user_department_infos=[UserDepartmentInfo(department_id=d['department_id'],
                                                          department_name=d['department_name'])
                                       for d in record['user_context'].get('user_department_infos', [])],
                event_id=record['event_id'],
                timestamp=record['timestamp'],

                message_id=record['event_data']['message_feedback_message_id'],
                interact_type=record['event_data']['message_feedback_operation_type'],
                app_id=record['event_data']['message_feedback_app_id'],
                app_name=record['event_data']['message_feedback_app_name'],
            ))
        mid_table.insert_records_sync(records)
    # Implement the actual logic here
    logger.info("Successfully synced mid_user_interact_dtl table.")

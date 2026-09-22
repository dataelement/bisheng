from datetime import date, datetime, timedelta
from time import monotonic
from typing import Any, List

from elasticsearch import exceptions as es_exceptions
from elasticsearch import helpers
from loguru import logger
from sqlalchemy import exists, func, or_
from sqlmodel import col, select

from bisheng.api.services.workflow import WorkFlowService
from bisheng.common.constants.enums.telemetry import (
    ApplicationTypeEnum,
    BaseTelemetryTypeEnum,
)
from bisheng.common.constants.telemetry import KNOWLEDGE_SPACE_DASHBOARD_FILE_LEVELS
from bisheng.common.schemas.telemetry.base_telemetry_schema import UserGroupInfo, UserRoleInfo, UserDepartmentInfo
from bisheng.common.schemas.telemetry.event_data_schema import (
    PortalDocumentDownloadEventData,
    PortalDocumentReadEventData,
    PortalFavoriteEventData,
)
from bisheng.common.services import telemetry_service
from bisheng.common.services.config_service import settings
from bisheng.core.cache.redis_manager import get_redis_client_sync
from bisheng.core.context.tenant import bypass_tenant_filter
from bisheng.core.database import get_sync_db_session
from bisheng.core.logger import trace_id_var
from bisheng.core.search.elasticsearch.manager import (
    get_statistics_es_connection_sync,
)
from bisheng.database.models.department import Department, UserDepartment, UserDepartmentDao
from bisheng.database.models.tenant import Tenant, UserTenant
from bisheng.database.models.flow import FlowType
from bisheng.knowledge.domain.models.knowledge import Knowledge, KnowledgeTypeEnum
from bisheng.knowledge.domain.models.knowledge_document_version import KnowledgeDocumentVersion
from bisheng.knowledge.domain.models.department_knowledge_space import (
    DepartmentKnowledgeSpace,
)
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile, KnowledgeFileDao, KnowledgeFileStatus, FileType
from bisheng.knowledge.domain.models.knowledge_space_scope import (
    KnowledgeSpaceLevelEnum,
    KnowledgeSpaceOwnerTypeEnum,
    KnowledgeSpaceScope,
    KnowledgeSpaceScopeDao,
)
from bisheng.knowledge.domain.services.knowledge_service import KnowledgeService
from bisheng.knowledge.domain.services.file_classification_label_service import (
    FileClassificationLabelService,
)
from bisheng.telemetry.domain.mid_table.app_increment import AppIncrement, AppIncrementRecord
from bisheng.telemetry.domain.mid_table.base import BaseMidTable
from bisheng.telemetry.domain.mid_table.content_stat_reconcile import BatchWriteError, ContentStatReconciler
from bisheng.telemetry.domain.mid_table.retry_budget import bounded_telemetry_task, checkpoint, frozen_value, recover_due_jobs
from bisheng.telemetry.domain.mid_table.queue_retry import QueuedProjectionFailure
from bisheng.telemetry.domain.mid_table.daily_participation import (
    CHINA_STANDARD_TIME,
    DailyParticipationFact,
    DailyParticipationRecord,
    aggregate_historical_login_hits,
    participation_day,
)
from bisheng.telemetry.domain.mid_table.knowledge_increment import KnowledgeIncrement, KnowledgeIncrementRecord
from bisheng.telemetry.domain.mid_table.knowledge_space_content import KnowledgeSpaceContentStat
from bisheng.telemetry.domain.repositories.implementations.knowledge_statistics_repository_impl import (
    KnowledgeStatisticsRepositoryImpl as KnowledgeStatisticsRepository,
)
from bisheng.telemetry.domain.mid_table.knowledge_space_content_dimensions import (
    resolve_organization_names,
)
from bisheng.telemetry.domain.mid_table.user_increment import UserIncrement, UserIncrementRecord
from bisheng.telemetry.domain.mid_table.user_interact import UserInteract, UserInteractRecord
from bisheng.user.domain.services.user import UserService
from bisheng.user.domain.models.user import User
from bisheng.utils import generate_uuid
from bisheng.worker.main import bisheng_celery


def get_yesterday_date_range(
    mid_table: BaseMidTable, start_date: str = None, end_date: str = None
) -> (datetime, datetime):
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
        user_list = UserService.get_user_all_info(
            start_time=start_date, end_time=end_date, page=page, page_size=page_size
        )
        page += 1
        if not user_list:
            break
        records = []
        for user in user_list:
            records.append(
                UserIncrementRecord(
                    es_id=f"increment_user_{user.user_id}",
                    user_id=user.user_id,
                    user_name=user.user_name,
                    user_group_infos=[
                        UserGroupInfo(user_group_id=group.id, user_group_name=group.group_name) for group in user.groups
                    ],
                    user_role_infos=[
                        UserRoleInfo(role_id=role.id, role_name=role.role_name, group_id=role.group_id)
                        for role in user.roles
                    ],
                    user_department_infos=[
                        UserDepartmentInfo(department_id=dept.id, department_name=dept.name)
                        for dept in getattr(user, "departments", []) or []
                    ],
                    timestamp=int(user.create_time.timestamp()),
                )
            )
        mid_table.insert_records_sync(records)

    # This is a placeholder for the actual data synchronization logic
    logger.info(f"Successfully synced mid_user_increment from {start_date} to {end_date}")


def _get_active_participation_users(
    offset: int,
    limit: int,
    user_ids: list[int] | None = None,
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
                if user_ids is not None:
                    statement = statement.where(col(User.user_id).in_(user_ids))
                return [(user, int(tenant_id)) for user, tenant_id in session.exec(statement).all()]

            statement = select(User).where(User.delete == 0).order_by(User.user_id.asc()).offset(offset).limit(limit)
            if user_ids is not None:
                statement = statement.where(col(User.user_id).in_(user_ids))
            return [(user, 1) for user in session.exec(statement).all()]


def _cleanup_participation_records(fact, dates, started_at, historical_login_keys, roster_keys):
    """仅核对参与记录, 不触碰共用索引中的其他指标。"""
    reconciler = ContentStatReconciler(fact._es_client_sync, fact._index_name, str)
    hits = helpers.scan(
        fact._es_client_sync,
        index=fact._index_name,
        size=1000,
        seq_no_primary_term=True,
        query={
            "_source": ["tenant_id", "local_date", "user_id"],
            "query": {
                "bool": {
                    "filter": [
                        {"term": {"metric_source": "participation"}},
                        {"terms": {"local_date": dates}},
                        {"range": {"projection_updated_at": {"lt": started_at}}},
                    ]
                }
            },
        },
    )
    deleted, batch = 0, []

    def flush(rows):
        checkpoint()
        rows = [
            hit
            for hit in rows
            if (int(hit["_source"]["tenant_id"]), int(hit["_source"]["user_id"])) not in roster_keys
            and (int(hit["_source"]["tenant_id"]), hit["_source"]["local_date"], int(hit["_source"]["user_id"]))
            not in historical_login_keys
        ]
        if not rows:
            return 0
        ids = sorted({int(hit["_source"]["user_id"]) for hit in rows})
        active = set()
        offset = 0
        while True:
            users = _get_active_participation_users(offset, 1000, ids)
            if not users:
                break
            active.update((int(tenant), int(user.user_id)) for user, tenant in users)
            offset += len(users)
        operations = []
        for hit in rows:
            source = hit["_source"]
            key = (int(source["tenant_id"]), source["local_date"], int(source["user_id"]))
            if (key[0], key[2]) not in active and key not in historical_login_keys:
                operations.append(
                    {"delete": {"_index": fact._index_name, "_id": hit["_id"], **reconciler.version(hit)}}
                )
        result = reconciler.write(operations)
        if result["conflict_ids"]:
            raise RuntimeError(f"Participation cleanup conflicts: {result['conflict_ids']}")
        return result["deleted"]

    try:
        for hit in hits:
            batch.append(hit)
            if len(batch) == 1000:
                deleted += flush(batch)
                batch = []
        if batch:
            deleted += flush(batch)
    finally:
        hits.close()
    return deleted


def _reconcile_participation_days(dates, *, aggregates=None, department_source="current_roster"):
    started_at = int(datetime.now().timestamp())
    fact = DailyParticipationFact()
    logins = dict(aggregates or {})
    historical_login_keys = set(logins)
    checked = written = unchanged = roster = 0
    date_values = [participation_day(day) for day in dates]

    def flush(records):
        nonlocal checked, written, unchanged
        checkpoint()
        result = fact.reconcile_records_sync(records)
        checked += result["checked"]
        written += result["created"] + result["updated"]
        unchanged += result["unchanged"]
        logger.info(
            "participation.reconcile.progress days={} checked={} written={} unchanged={}",
            len(dates),
            checked,
            written,
            unchanged,
        )

    def build(user_id, tenant, name, department, local_date, timestamp, login):
        return DailyParticipationRecord(
            es_id=DailyParticipationFact.build_es_id(tenant, local_date, user_id),
            tenant_id=tenant,
            timestamp=timestamp,
            user_id=user_id,
            user_name=name,
            user_group_infos=[],
            user_role_infos=[],
            user_department_infos=[],
            local_date=local_date,
            active_employee=1,
            primary_department_id=int(department.id) if department else None,
            primary_department_name=department.name if department else None,
            department_source="current_primary_backfill" if login else department_source,
            projection_updated_at=started_at,
            **(
                {key: login[key] for key in ("login_count", "first_login_at", "last_login_at")} | {"logged_in": True}
                if login
                else {}
            ),
        )

    offset, records = 0, []
    roster_keys = set()
    while True:
        checkpoint()
        users = _get_active_participation_users(offset, 1000)
        if not users:
            break
        offset += len(users)
        with bypass_tenant_filter():
            departments = UserDepartmentDao.get_primary_department_map_by_user_ids(
                sorted({int(user.user_id) for user, _ in users})
            )
        for user, tenant in users:
            user_id = int(user.user_id)
            roster_keys.add((tenant, user_id))
            for local_date, timestamp in date_values:
                login = logins.pop((tenant, local_date, user_id), None)
                records.append(
                    build(user_id, tenant, user.user_name, departments.get(user_id), local_date, timestamp, login)
                )
                roster += 1
                if len(records) == 1000:
                    flush(records)
                    records = []
    # 保留不在当前名单中但确有历史登录的人员, 避免优化改变历史补算结果。
    remaining = list(logins.values())
    for offset in range(0, len(remaining), 1000):
        checkpoint()
        batch = remaining[offset : offset + 1000]
        with bypass_tenant_filter():
            departments = UserDepartmentDao.get_primary_department_map_by_user_ids(
                sorted({row["user_id"] for row in batch})
            )
        for login in batch:
            records.append(
                build(
                    login["user_id"],
                    login["tenant_id"],
                    login["user_name"],
                    departments.get(login["user_id"]),
                    login["local_date"],
                    participation_day(date.fromisoformat(login["local_date"]))[1],
                    login,
                )
            )
            if len(records) == 1000:
                flush(records)
                records = []
    if records:
        flush(records)
    deleted = _cleanup_participation_records(
        fact, [value[0] for value in date_values], started_at, historical_login_keys, roster_keys
    )
    return {
        "days": len(dates),
        "roster": roster,
        "login_facts": len(historical_login_keys),
        "checked": checked,
        "written": written,
        "unchanged": unchanged,
        "deleted": deleted,
    }


def _reconcile_participation_roster_for_day(target_date: date, *, department_source: str):
    result = _reconcile_participation_days([target_date], department_source=department_source)
    return {**result, "local_date": target_date.isoformat(), "synced": result["roster"]}


@bisheng_celery.task()
@bounded_telemetry_task
def sync_mid_user_daily_participation_fact():
    """Reconcile today's denominator while preserving real-time login counters."""
    DailyParticipationFact.clear_roster_reconcile_scheduled()
    trace_id_var.set(f"sync_mid_user_daily_participation_fact_task_{generate_uuid()}")
    today = date.fromisoformat(frozen_value("today", lambda: datetime.now(CHINA_STANDARD_TIME).date().isoformat()))
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
                        {"term": {"event_type": (BaseTelemetryTypeEnum.USER_LOGIN.value)}},
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

    def guarded_hits():
        try:
            for offset, hit in enumerate(hits):
                if offset % 1000 == 0:
                    checkpoint()
                yield hit
        finally:
            hits.close()

    return aggregate_historical_login_hits(guarded_hits())


@bisheng_celery.task()
@bounded_telemetry_task
def backfill_mid_user_daily_participation_fact(
    lookback_days: int = 30,
) -> dict[str, int]:
    """Best-effort history using current roster and durable login telemetry."""
    trace_id_var.set(f"backfill_mid_user_daily_participation_fact_task_{generate_uuid()}")
    normalized_days = max(1, min(int(lookback_days), 365))
    today = date.fromisoformat(frozen_value("today", lambda: datetime.now(CHINA_STANDARD_TIME).date().isoformat()))
    start_date = today - timedelta(days=normalized_days)
    start_timestamp = participation_day(start_date)[1]
    end_timestamp = participation_day(today)[1]
    aggregates = _scan_historical_login_events(
        start_timestamp=start_timestamp,
        end_timestamp=end_timestamp,
    )
    if aggregates is None:
        logger.info("Skipped participation history backfill because telemetry index is absent.")
        return {"days": 0, "roster": 0, "login_facts": 0}

    result = _reconcile_participation_days(
        [start_date + timedelta(days=offset) for offset in range(normalized_days)],
        aggregates=aggregates,
        department_source="current_roster_backfill",
    )
    logger.info("Backfilled participation history. {}", result)
    return result


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


def _content_stat_file_predicates() -> tuple[Any, ...]:
    return (
        Knowledge.type == KnowledgeTypeEnum.SPACE.value,
        Knowledge.is_favorite == False,  # noqa: E712
        KnowledgeFile.file_type == FileType.FILE.value,
        KnowledgeFile.status == KnowledgeFileStatus.SUCCESS.value,
        KnowledgeFileDao.active_inventory_predicate(),
        or_(Knowledge.state.is_(None), Knowledge.state != 5),
    )


def _get_content_stat_reconcile_scope() -> tuple[int, int]:
    """冻结本轮 ID 上界; 总数用于进度估算, 不持有长事务快照。"""
    statement = (
        select(func.count(KnowledgeFile.id), func.max(KnowledgeFile.id))
        .join(Knowledge, KnowledgeFile.knowledge_id == Knowledge.id)
        .where(*_content_stat_file_predicates())
    )
    with bypass_tenant_filter():
        with get_sync_db_session() as session:
            total, max_id = session.exec(statement).one()
    return int(total), int(max_id or 0)


def _get_content_stat_reconcile_rows(after_id: int, max_id: int, limit: int) -> list[tuple[KnowledgeFile, Knowledge]]:
    """用 ID 游标防止并发删除导致 offset 跳过仍有效的文件。"""
    statement = (
        select(KnowledgeFile, Knowledge)
        .join(Knowledge, KnowledgeFile.knowledge_id == Knowledge.id)
        .where(*_content_stat_file_predicates(), KnowledgeFile.id > after_id, KnowledgeFile.id <= max_id)
        .order_by(KnowledgeFile.id.asc())
        .limit(limit)
    )
    with bypass_tenant_filter():
        with get_sync_db_session() as session:
            return session.exec(statement).all()


def _get_content_stat_valid_file_ids(file_ids: list[int]) -> set[int]:
    if not file_ids:
        return set()
    statement = (
        select(KnowledgeFile.id)
        .join(Knowledge, KnowledgeFile.knowledge_id == Knowledge.id)
        .where(*_content_stat_file_predicates(), KnowledgeFile.id.in_(file_ids))
    )
    with bypass_tenant_filter():
        with get_sync_db_session() as session:
            return {int(file_id) for file_id in session.exec(statement).all()}


def _get_success_space_file_rows(page: int, page_size: int):
    statement = (
        select(KnowledgeFile, Knowledge)
        .join(Knowledge, KnowledgeFile.knowledge_id == Knowledge.id)
        .where(
            *_content_stat_file_predicates(),
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
            Knowledge.is_favorite == False,  # noqa: E712
            KnowledgeFile.file_type == FileType.FILE.value,
            KnowledgeFile.status == KnowledgeFileStatus.SUCCESS.value,
            KnowledgeFileDao.active_inventory_predicate(),
            or_(Knowledge.state.is_(None), Knowledge.state != 5),
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
            KnowledgeFileDao.active_inventory_predicate(),
            or_(Knowledge.state.is_(None), Knowledge.state != 5),
        )
    )
    with bypass_tenant_filter():
        with get_sync_db_session() as session:
            return session.exec(statement).all()


def _get_favorite_space_ids() -> list[int]:
    statement = select(Knowledge.id).where(
        Knowledge.type == KnowledgeTypeEnum.SPACE.value,
        Knowledge.is_favorite == True,  # noqa: E712
    )
    with bypass_tenant_filter():
        with get_sync_db_session() as session:
            return [int(space_id) for space_id in session.exec(statement).all()]


def _is_department_bound_space_scope(scope) -> bool:
    if scope is None:
        return False
    level = str(getattr(scope.level, "value", scope.level))
    return level in {
        KnowledgeSpaceLevelEnum.DEPARTMENT.value,
        KnowledgeSpaceLevelEnum.TEAM_KS.value,
    }


def _resolve_content_stat_space_level(scope) -> str | None:
    if scope is None:
        return None
    level = str(getattr(scope.level, "value", scope.level)).strip().lower()
    if level not in KNOWLEDGE_SPACE_DASHBOARD_FILE_LEVELS:
        return None
    return level


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
        space_id for space_id in normalized_space_ids if _is_department_bound_space_scope(space_scope_map.get(space_id))
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
                    and str(getattr(scope.level, "value", scope.level)) == KnowledgeSpaceLevelEnum.DEPARTMENT.value
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
                department_map = {int(department.id): department for department in departments}
                for space_id in eligible_space_ids:
                    if result[space_id] is not None:
                        continue
                    scope = space_scope_map.get(space_id)
                    if scope is not None:
                        result[space_id] = department_map.get(int(scope.owner_id))
    return result


def _get_dimension_department_map(start_departments: list[Department | None]) -> dict[int, Department]:
    department_ids: set[int] = set()
    for department in start_departments:
        if department is None:
            continue
        for value in str(getattr(department, "path", "") or "").strip("/").split("/"):
            if value.isdigit():
                department_ids.add(int(value))
        if getattr(department, "id", None) is not None:
            department_ids.add(int(department.id))

    filters = [Department.org_level == "company"]
    if department_ids:
        filters.append(Department.id.in_(sorted(department_ids)))
    with bypass_tenant_filter():
        with get_sync_db_session() as session:
            rows = session.exec(
                select(Department).where(
                    Department.status == "active",
                    or_(*filters),
                )
            ).all()
    return {int(row.id): row for row in rows if row.id is not None}


def _resolve_belonging_start_department(
    *,
    scope,
    space_department: Department | None,
    primary_department_map: dict[int, Department],
    company_departments: list[Department],
) -> Department | None:
    level = _resolve_content_stat_space_level(scope)
    if level == KnowledgeSpaceLevelEnum.PUBLIC.value:
        return company_departments[0] if len(company_departments) == 1 else None
    if level in {
        KnowledgeSpaceLevelEnum.DEPARTMENT.value,
        KnowledgeSpaceLevelEnum.TEAM_KS.value,
    }:
        return space_department
    if level == KnowledgeSpaceLevelEnum.TEAM.value:
        created_by = int(getattr(scope, "created_by", 0) or 0)
        return primary_department_map.get(created_by)
    if level == KnowledgeSpaceLevelEnum.PERSONAL.value:
        owner_id = int(getattr(scope, "owner_id", 0) or 0)
        return primary_department_map.get(owner_id)
    return None


def _original_space_id_for(file_record, space) -> int:
    """F081 tracks each file's immutable original upload space in
    ``KnowledgeFile.original_knowledge_id``. Files created before that column existed
    (2026-08-10) — or not yet covered by ``backfill_knowledge_file_original_origin.py`` —
    have it NULL; fall back to the file's current space so 原始上传库 degrades to the
    (still library→org, not person→department) current-space mapping instead of crashing
    or silently mis-scoping to zero."""
    return int(getattr(file_record, "original_knowledge_id", None) or space.id)


def _build_knowledge_space_content_records(
    rows,
    user_map: dict,
    *,
    sync_run_id: str = None,
    space_scope_map: dict | None = None,
    space_department_map: dict | None = None,
    original_space_scope_map: dict | None = None,
    original_space_department_map: dict | None = None,
    primary_department_map: dict | None = None,
    category_label_cache: dict | None = None,
):
    if not rows:
        return [], user_map
    with bypass_tenant_filter():
        identity_map = KnowledgeStatisticsRepository.identities([int(file_record.id) for file_record, _ in rows])
    space_scope_map = space_scope_map if space_scope_map is not None else {}
    space_department_map = space_department_map if space_department_map is not None else {}
    original_space_scope_map = original_space_scope_map if original_space_scope_map is not None else {}
    original_space_department_map = (
        original_space_department_map if original_space_department_map is not None else {}
    )
    primary_department_map = primary_department_map if primary_department_map is not None else {}
    category_label_cache = category_label_cache if category_label_cache is not None else {}
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
    missing_space_department_ids = [space_id for space_id in space_ids if space_id not in space_department_map]
    if missing_space_department_ids:
        space_department_map.update(
            _get_knowledge_space_department_map(
                missing_space_department_ids,
                space_scope_map,
            )
        )

    # 原始上传库: same library->org mapping rule as 所属 (_resolve_belonging_start_department),
    # but evaluated against each file's ORIGINAL space instead of its current one, so moving a
    # file (or the uploader changing department) never changes this figure — only ever set once,
    # at first upload. A file's original space may no longer be one of the CURRENT spaces above
    # (the file could have since moved away from it), so it needs its own scope/department fetch.
    original_space_ids = sorted({_original_space_id_for(file_record, space) for file_record, space in rows})
    missing_original_space_ids = [
        space_id for space_id in original_space_ids if space_id not in original_space_scope_map
    ]
    if missing_original_space_ids:
        original_space_scope_map.update(KnowledgeSpaceScopeDao.get_map_by_space_ids(missing_original_space_ids))
    missing_original_space_department_ids = [
        space_id for space_id in original_space_ids if space_id not in original_space_department_map
    ]
    if missing_original_space_department_ids:
        original_space_department_map.update(
            _get_knowledge_space_department_map(
                missing_original_space_department_ids,
                original_space_scope_map,
            )
        )

    all_user_ids = {int(file_record.user_id) for file_record, _ in rows if file_record.user_id}
    for scope_map in (space_scope_map, original_space_scope_map):
        for scope in scope_map.values():
            level = _resolve_content_stat_space_level(scope)
            if level == KnowledgeSpaceLevelEnum.TEAM.value and getattr(scope, "created_by", None):
                all_user_ids.add(int(scope.created_by))
            elif level == KnowledgeSpaceLevelEnum.PERSONAL.value and getattr(scope, "owner_id", None):
                all_user_ids.add(int(scope.owner_id))
    all_user_ids = sorted(all_user_ids)
    missing_primary_user_ids = [user_id for user_id in all_user_ids if user_id not in primary_department_map]
    if missing_primary_user_ids:
        primary_department_map.update(
            UserDepartmentDao.get_primary_department_map_by_user_ids(missing_primary_user_ids)
        )

    departments_by_id = _get_dimension_department_map(
        list(primary_department_map.values())
        + list(space_department_map.values())
        + list(original_space_department_map.values())
    )
    company_departments = [
        department
        for department in departments_by_id.values()
        if str(getattr(department, "org_level", "") or "") == "company"
    ]

    records = []
    for file_record, space in rows:
        uploader = user_map.get(int(file_record.user_id or 0))
        tenant_id = int(getattr(file_record, "tenant_id", None) or getattr(space, "tenant_id", None) or 1)
        if tenant_id not in category_label_cache:
            category_label_cache[tenant_id] = FileClassificationLabelService.get_label_lookup_for_tenant(tenant_id)
        category_labels, subcategory_labels = category_label_cache[tenant_id]
        scope = space_scope_map.get(int(space.id))
        # 上传人XX keeps its original, unchanged meaning: whoever is currently on record as
        # this file's uploader (file_record.user_id), in THEIR current department — product
        # wants this field's semantics untouched. 原始上传库XX is the new, separate,
        # library->org mapping frozen at the file's ORIGINAL upload space.
        uploader_department = primary_department_map.get(int(file_record.user_id or 0))
        original_space_id = _original_space_id_for(file_record, space)
        original_upload_department = _resolve_belonging_start_department(
            scope=original_space_scope_map.get(original_space_id),
            space_department=original_space_department_map.get(original_space_id),
            primary_department_map=primary_department_map,
            company_departments=company_departments,
        )
        belonging_department = _resolve_belonging_start_department(
            scope=scope,
            space_department=space_department_map.get(int(space.id)),
            primary_department_map=primary_department_map,
            company_departments=company_departments,
        )
        records.append(
            KnowledgeSpaceContentStat.build_file_record(
                file_record=file_record,
                space=space,
                uploader=uploader,
                space_level=_resolve_content_stat_space_level(scope),
                uploader_organization=resolve_organization_names(
                    uploader_department,
                    departments_by_id,
                ),
                belonging_organization=resolve_organization_names(
                    belonging_department,
                    departments_by_id,
                ),
                original_upload_organization=resolve_organization_names(
                    original_upload_department,
                    departments_by_id,
                ),
                file_category_labels=category_labels,
                file_subcategory_labels=subcategory_labels,
                sync_run_id=sync_run_id,
                knowledge_identity=identity_map[int(file_record.id)],
            )
        )
    return records, user_map


def build_knowledge_space_content_event_record(file_id: int):
    """Build one fresh dimension snapshot for a successful user action."""
    rows = _get_knowledge_space_content_rows_by_file_ids([int(file_id)])
    visible_rows = [
        (file_record, space)
        for file_record, space in rows
        if _is_file_content_stat_visible(file_record, space)
    ]
    records, _ = _build_knowledge_space_content_records(visible_rows, {})
    return records[0] if records else None


def _expand_content_stat_user_work(user_id: int) -> tuple[list[int], list[int]]:
    with bypass_tenant_filter():
        with get_sync_db_session() as session:
            file_ids = session.exec(
                select(KnowledgeFile.id).where(KnowledgeFile.user_id == int(user_id))
            ).all()
            space_ids = session.exec(
                select(KnowledgeSpaceScope.space_id).where(
                    or_(
                        (
                            (KnowledgeSpaceScope.level == KnowledgeSpaceLevelEnum.TEAM.value)
                            & (KnowledgeSpaceScope.created_by == int(user_id))
                        ),
                        (
                            (KnowledgeSpaceScope.level == KnowledgeSpaceLevelEnum.PERSONAL.value)
                            & (KnowledgeSpaceScope.owner_id == int(user_id))
                        ),
                    )
                )
            ).all()
    return [int(value) for value in file_ids], [int(value) for value in space_ids]


def _expand_content_stat_department_work(department_id: int) -> tuple[list[int], list[int]]:
    with bypass_tenant_filter():
        with get_sync_db_session() as session:
            department = session.exec(
                select(Department).where(Department.id == int(department_id))
            ).first()
            if department is None or not department.path:
                return [], []
            user_ids = session.exec(
                select(UserDepartment.user_id)
                .join(Department, Department.id == UserDepartment.department_id)
                .where(
                    UserDepartment.is_primary == 1,
                    Department.path.like(f"{department.path}%"),
                )
            ).all()
            space_ids = session.exec(
                select(DepartmentKnowledgeSpace.space_id)
                .join(Department, Department.id == DepartmentKnowledgeSpace.department_id)
                .where(Department.path.like(f"{department.path}%"))
            ).all()
            # A company label may already have been cleared when this work item
            # is consumed, so every organization change also refreshes public
            # spaces whose ownership depends on the unique company label.
            space_ids.extend(
                session.exec(
                    select(KnowledgeSpaceScope.space_id).where(
                        KnowledgeSpaceScope.level == KnowledgeSpaceLevelEnum.PUBLIC.value
                    )
                ).all()
            )
    return [int(value) for value in user_ids], [int(value) for value in space_ids]


def _is_file_content_stat_visible(file_record: KnowledgeFile, space: Knowledge) -> bool:
    return (
        space.type == KnowledgeTypeEnum.SPACE.value
        and not bool(getattr(space, "is_favorite", False))
        and file_record.file_type == FileType.FILE.value
        and file_record.status == KnowledgeFileStatus.SUCCESS.value
        and getattr(file_record, "deleted_at", None) is None
    )


def _get_portal_download_aggregation_page(
    *,
    after_key: dict[str, Any] | None = None,
    page_size: int = 1000,
) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    composite: dict[str, Any] = {
        "size": page_size,
        "sources": [
            {
                "local_date": {
                    "date_histogram": {
                        "field": "timestamp",
                        "calendar_interval": "1d",
                        "time_zone": "+08:00",
                        "format": "yyyy-MM-dd",
                    }
                }
            },
            {
                "file_id": {
                    "terms": {
                        "field": "event_data.portal_document_download_file_id",
                    }
                }
            },
        ],
    }
    if after_key:
        composite["after"] = after_key

    try:
        response = get_statistics_es_connection_sync().search(
            index=telemetry_service.index_name,
            body={
                "size": 0,
                "query": {
                    "bool": {
                        "filter": [
                            {"term": {"event_type": BaseTelemetryTypeEnum.PORTAL_DOCUMENT_DOWNLOAD.value}},
                            {
                                "term": {
                                    "event_data.portal_document_download_source_app.keyword": "shougang_portal"
                                }
                            },
                            {
                                "term": {
                                    "event_data.portal_document_download_status.keyword": "success"
                                }
                            },
                        ]
                    }
                },
                "aggs": {
                    "download_daily": {
                        "composite": composite,
                    }
                },
            },
        )
    except es_exceptions.NotFoundError:
        logger.info("Portal download telemetry index does not exist; projecting zero download records")
        return [], None
    aggregation = response.get("aggregations", {}).get("download_daily", {})
    buckets: list[dict[str, Any]] = []
    for bucket in aggregation.get("buckets", []):
        key = bucket.get("key") or {}
        try:
            file_id = int(key["file_id"])
            local_date = str(key["local_date"])
            datetime.strptime(local_date, "%Y-%m-%d")
            download_count = int(bucket["doc_count"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"Invalid portal download aggregation bucket: {bucket}") from exc
        if file_id <= 0 or download_count < 0:
            raise ValueError(f"Invalid portal download aggregation bucket: {bucket}")
        buckets.append(
            {
                "file_id": file_id,
                "local_date": local_date,
                "download_count": download_count,
            }
        )
    return buckets, aggregation.get("after_key")


def rebuild_knowledge_space_content_download_projection(
    *,
    owner_token: str,
    mid_table: KnowledgeSpaceContentStat,
    sync_run_id: str,
) -> dict[str, int]:
    after_key: dict[str, Any] | None = None
    user_map: dict[int, Any] = {}
    space_scope_map: dict[int, Any] = {}
    space_department_map: dict[int, Any] = {}
    original_space_scope_map: dict[int, Any] = {}
    original_space_department_map: dict[int, Any] = {}
    primary_department_map: dict[int, Any] = {}
    category_label_cache: dict[int, tuple[dict[str, str], dict[str, str]]] = {}
    synced_count = 0

    while True:
        if not KnowledgeSpaceContentStat.renew_lock_sync(owner_token):
            raise RuntimeError("Knowledge space content full projection owner lock lost during download query")
        buckets, next_after_key = _get_portal_download_aggregation_page(after_key=after_key)
        if not buckets:
            break

        file_ids = sorted({bucket["file_id"] for bucket in buckets})
        rows = [
            (file_record, space)
            for file_record, space in _get_knowledge_space_content_rows_by_file_ids(file_ids)
            if _is_file_content_stat_visible(file_record, space)
        ]
        file_records, user_map = _build_knowledge_space_content_records(
            rows,
            user_map,
            sync_run_id=sync_run_id,
            space_scope_map=space_scope_map,
            space_department_map=space_department_map,
            original_space_scope_map=original_space_scope_map,
            original_space_department_map=original_space_department_map,
            primary_department_map=primary_department_map,
            category_label_cache=category_label_cache,
        )
        file_record_map = {record.file_id: record for record in file_records}
        download_records = [
            KnowledgeSpaceContentStat.build_download_daily_record(
                file_record=file_record_map[bucket["file_id"]],
                local_date=bucket["local_date"],
                download_count=bucket["download_count"],
                sync_run_id=sync_run_id,
            )
            for bucket in buckets
            if bucket["file_id"] in file_record_map
        ]
        if download_records:
            if not KnowledgeSpaceContentStat.renew_lock_sync(owner_token):
                raise RuntimeError("Knowledge space content full projection owner lock lost before download write")
            mid_table.insert_records_sync(download_records)
            synced_count += len(download_records)

        if not next_after_key:
            break
        if next_after_key == after_key:
            raise RuntimeError("Portal download aggregation returned a repeated after_key")
        after_key = next_after_key

    if not KnowledgeSpaceContentStat.renew_lock_sync(owner_token):
        raise RuntimeError("Knowledge space content full projection owner lock lost before download cleanup")
    deleted_count = mid_table.delete_stale_download_daily_records_sync(sync_run_id)
    return {
        "synced_download_daily": synced_count,
        "deleted_stale_download_daily": deleted_count,
    }


def rebuild_knowledge_space_content_file_projection(owner_token: str) -> dict[str, Any]:
    """分批对账当前文件快照, 仅写差异; 历史日聚合仍由事件链路维护。"""
    sync_started_ms = KnowledgeSpaceContentStat._now_ms()
    started = monotonic()
    mid_table = KnowledgeSpaceContentStat()
    sync_run_id = generate_uuid()
    reconciler = ContentStatReconciler(mid_table._es_client_sync, mid_table.INDEX_NAME)
    page_size = 1000
    after_id = batch = 0
    user_map = {}
    space_scope_map = {}
    space_department_map = {}
    original_space_scope_map = {}
    original_space_department_map = {}
    primary_department_map = {}
    category_label_cache = {}
    counters = {"checked": 0, "unchanged": 0, "created": 0, "updated": 0, "conflicts": 0, "blocked": 0}

    def guard() -> None:
        if not KnowledgeSpaceContentStat.renew_lock_sync(owner_token):
            raise RuntimeError("Knowledge space content full projection owner lock lost")

    def write(operations: list[dict]) -> dict[str, Any]:
        guard()
        entries, offset = [], 0
        while offset < len(operations):
            kind, metadata = next(iter(operations[offset].items()))
            size = 1 if kind == "delete" else 2
            entries.append((str(metadata["_id"]), operations[offset : offset + size]))
            offset += size
        blocked = KnowledgeSpaceContentStat.dead_file_ids_sync([key for key, _ in entries])
        if blocked:
            counters["blocked"] += len(blocked)
            logger.error("content_stat.reconcile.dead_items_skipped ids={}", sorted(blocked))
        operations = [operation for key, entry in entries if key not in blocked for operation in entry]
        outcome = reconciler.write(operations)
        conflict_ids = outcome["conflict_ids"]
        counters["conflicts"] += len(conflict_ids)
        if conflict_ids and not KnowledgeSpaceContentStat.enqueue_file_stat_sync(conflict_ids):
            raise RuntimeError("Content stat reconciliation conflict enqueue failed")
        return outcome

    guard()
    total, max_id = _get_content_stat_reconcile_scope()
    logger.info(
        "content_stat.reconcile.start run_id={} total={} batch_size={} max_id={}", sync_run_id, total, page_size, max_id
    )

    while True:
        guard()
        rows = _get_content_stat_reconcile_rows(after_id, max_id, page_size)
        if not rows:
            break
        next_id = int(rows[-1][0].id)
        if next_id <= after_id:
            raise RuntimeError("Content stat reconciliation cursor did not advance")
        after_id = next_id
        batch += 1

        records, user_map = _build_knowledge_space_content_records(
            rows,
            user_map,
            sync_run_id=sync_run_id,
            space_scope_map=space_scope_map,
            space_department_map=space_department_map,
            original_space_scope_map=original_space_scope_map,
            original_space_department_map=original_space_department_map,
            primary_department_map=primary_department_map,
            category_label_cache=category_label_cache,
        )
        guard()
        operations, differences, unchanged = reconciler.compare(records)
        if differences:
            logger.info(
                "content_stat.reconcile.differences run_id={} batch={} records={}", sync_run_id, batch, differences
            )
        outcome = write(operations)
        counters["checked"] += len(records)
        counters["unchanged"] += unchanged
        counters["created"] += outcome["created"]
        counters["updated"] += outcome["updated"]
        progress = min(100.0, counters["checked"] * 100.0 / total) if total else 100.0
        logger.info(
            "content_stat.reconcile.progress run_id={} batch={} checked={} total={} progress={:.2f}% "
            "batch_size={} differences={} created={} updated={} unchanged={} conflicts={} elapsed_s={:.2f}",
            sync_run_id,
            batch,
            counters["checked"],
            total,
            progress,
            len(records),
            len(differences),
            counters["created"],
            counters["updated"],
            counters["unchanged"],
            counters["conflicts"],
            monotonic() - started,
        )

    # 未变化的记录不会更新轮次标记, 失效项必须反查数据库判定, 不能按旧 sync_run_id 删除。
    deleted_count = reverse_checked = 0
    scan = reconciler.file_batches(guard, batch_size=page_size)
    try:
        for reverse_batch, hits in enumerate(scan, start=1):
            ids = [int(hit["_id"]) for hit in hits]
            valid_ids = _get_content_stat_valid_file_ids(ids)
            operations = reconciler.deletion_operations(hits, valid_ids)
            if operations:
                logger.info(
                    "content_stat.reconcile.stale run_id={} batch={} file_ids={}",
                    sync_run_id,
                    reverse_batch,
                    [op["delete"]["_id"] for op in operations],
                )
            outcome = write(operations)
            deleted_count += outcome["deleted"]
            reverse_checked += len(hits)
            logger.info(
                "content_stat.reconcile.cleanup_progress run_id={} batch={} checked={} deleted={} elapsed_s={:.2f}",
                sync_run_id,
                reverse_batch,
                reverse_checked,
                deleted_count,
                monotonic() - started,
            )
    finally:
        scan.close()
    guard()
    deleted_favorite_count = mid_table.delete_space_records_sync(_get_favorite_space_ids())
    queue_status = KnowledgeSpaceContentStat.queue_status_sync()
    logger.info(
        "content_stat.reconcile.completed run_id={} total={} counters={} deleted_stale={} elapsed_s={:.2f}",
        sync_run_id,
        total,
        counters,
        deleted_count,
        monotonic() - started,
    )
    return {
        **queue_status,
        **counters,
        "total": total,
        "synced": counters["created"] + counters["updated"],
        "deleted_stale": deleted_count,
        "deleted_favorite": deleted_favorite_count,
        "reclaimed_count": 0,
        "batch_duration_ms": KnowledgeSpaceContentStat._now_ms() - sync_started_ms,
        "projection_lag_ms": queue_status["oldest_pending_age_ms"],
        "last_success_at": int(datetime.now().timestamp()),
        "failure_stage": None,
        "degraded": counters["conflicts"] > 0 or counters["blocked"] > 0,
    }


@bisheng_celery.task()
@bounded_telemetry_task
def sync_mid_knowledge_space_content_stat(start_date: str = None, end_date: str = None):
    del start_date, end_date
    trace_id_var.set(f"sync_mid_knowledge_space_content_stat_task_{generate_uuid()}")
    logger.info("Syncing mid_knowledge_space_content_stat file records...")

    owner_token = KnowledgeSpaceContentStat.acquire_lock_sync()
    if owner_token is None:
        logger.warning("Knowledge space content full projection skipped. degraded=true failure_stage=owner_lock")
        status = KnowledgeSpaceContentStat.queue_status_sync()
        return {
            **status,
            "reclaimed_count": 0,
            "batch_duration_ms": 0,
            "projection_lag_ms": status["oldest_pending_age_ms"],
            "last_success_at": None,
            "degraded": True,
            "failure_stage": "owner_lock",
        }

    try:
        result = rebuild_knowledge_space_content_file_projection(owner_token)
        logger.info("Knowledge space content full projection completed. {}", result)
        return result
    except Exception:
        logger.exception("Knowledge space content full projection failed. degraded=true failure_stage=full_projection")
        raise
    finally:
        KnowledgeSpaceContentStat.release_lock_sync(owner_token)
        if KnowledgeSpaceContentStat.has_pending_sync():
            KnowledgeSpaceContentStat.schedule_pending_sync_now()


@bisheng_celery.task()
@bounded_telemetry_task
def sync_pending_knowledge_space_content_stat():
    trace_id_var.set(f"sync_pending_knowledge_space_content_stat_task_{generate_uuid()}")
    KnowledgeSpaceContentStat.clear_scheduled_sync()
    owner_token = KnowledgeSpaceContentStat.acquire_lock_sync()
    if owner_token is None:
        logger.warning(
            "Knowledge space content incremental projection deferred. degraded=true failure_stage=owner_lock"
        )
        return {"degraded": True, "failure_stage": "owner_lock"}

    batch_started_ms = KnowledgeSpaceContentStat._now_ms()
    failure_stage = None
    claimed = []
    try:
        mid_table = KnowledgeSpaceContentStat()
        user_map = {}
        space_scope_map = {}
        space_department_map = {}
        original_space_scope_map = {}
        original_space_department_map = {}
        primary_department_map = {}
        category_label_cache = {}

        claimed = KnowledgeSpaceContentStat.claim_pending_sync(
            owner_token,
            KnowledgeSpaceContentStat.FILE_BATCH_SIZE,
        )
        members = [item.member for item in claimed]
        file_items = [item for item in claimed if item.kind == "file"]
        space_items = [item for item in claimed if item.kind == "space"]
        user_items = [item for item in claimed if item.kind == "user"]
        department_items = [item for item in claimed if item.kind == "department"]
        invalid_items = [item for item in claimed if item.kind not in {"file", "space", "user", "department"}]

        if invalid_items:
            failure_stage = "invalid_work_item"
            logger.error(
                "Knowledge space content projection has invalid work items. items={}",
                [item.member for item in invalid_items],
            )
            KnowledgeSpaceContentStat.fail_claimed_sync(
                owner_token, [item.member for item in invalid_items], "Unsupported work item kind"
            )

        for item in user_items:
            failure_stage = "user_projection_expand"
            file_ids, space_ids = _expand_content_stat_user_work(item.resource_id)
            redis_client = get_redis_client_sync()
            KnowledgeSpaceContentStat._zadd_pending_sync(
                redis_client,
                KnowledgeSpaceContentStat._work_members("file", file_ids)
                + KnowledgeSpaceContentStat._work_members("space", space_ids),
            )
            if not KnowledgeSpaceContentStat.ack_claimed_sync(owner_token, [item.member]):
                raise RuntimeError("Failed to acknowledge knowledge space content user work item")

        for item in department_items:
            failure_stage = "department_projection_expand"
            user_ids, space_ids = _expand_content_stat_department_work(item.resource_id)
            redis_client = get_redis_client_sync()
            KnowledgeSpaceContentStat._zadd_pending_sync(
                redis_client,
                KnowledgeSpaceContentStat._work_members("user", user_ids)
                + KnowledgeSpaceContentStat._work_members("space", space_ids),
            )
            if not KnowledgeSpaceContentStat.ack_claimed_sync(owner_token, [item.member]):
                raise RuntimeError("Failed to acknowledge knowledge space content department work item")

        file_ids = [item.resource_id for item in file_items]
        if file_ids:
            failure_stage = "file_projection"
            if not KnowledgeSpaceContentStat.renew_lock_sync(
                owner_token
            ) or not KnowledgeSpaceContentStat.renew_claims_sync(
                owner_token,
                [item.member for item in file_items],
            ):
                raise RuntimeError("Knowledge space content projection lease lost before file projection")
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
                original_space_scope_map=original_space_scope_map,
                original_space_department_map=original_space_department_map,
                primary_department_map=primary_department_map,
                category_label_cache=category_label_cache,
            )
            if records:
                mid_table.reconcile_file_records_sync(records)
            if stale_file_ids:
                if not KnowledgeSpaceContentStat.renew_lock_sync(owner_token):
                    raise RuntimeError("Knowledge space content owner lock lost before file deletion")
                mid_table.reconcile_delete_file_records_sync(stale_file_ids)
            if not KnowledgeSpaceContentStat.renew_lock_sync(owner_token):
                raise RuntimeError("Knowledge space content projection owner lock lost before file ack")
            if not KnowledgeSpaceContentStat.ack_claimed_sync(
                owner_token,
                [item.member for item in file_items],
            ):
                raise RuntimeError("Failed to acknowledge knowledge space content file projection")

            logger.info(
                "Synced pending knowledge space content file stats. upserted={}, deleted={}",
                len(records),
                len(stale_file_ids),
            )

        for item in space_items:
            failure_stage = "space_projection"
            if not KnowledgeSpaceContentStat.renew_lock_sync(
                owner_token
            ) or not KnowledgeSpaceContentStat.renew_claims_sync(
                owner_token,
                [item.member],
            ):
                raise RuntimeError("Knowledge space content projection lease lost before space projection")
            space_id = item.resource_id
            page, page_size = 1, 500
            space_synced_count = 0
            while True:
                if not KnowledgeSpaceContentStat.renew_lock_sync(
                    owner_token
                ) or not KnowledgeSpaceContentStat.renew_claims_sync(
                    owner_token,
                    [item.member],
                ):
                    raise RuntimeError("Knowledge space content projection lease lost during space projection")
                rows = _get_success_space_file_rows_by_space_id(space_id, page, page_size)
                page += 1
                if not rows:
                    break
                records, user_map = _build_knowledge_space_content_records(
                    rows,
                    user_map,
                    space_scope_map=space_scope_map,
                    space_department_map=space_department_map,
                    original_space_scope_map=original_space_scope_map,
                    original_space_department_map=original_space_department_map,
                    primary_department_map=primary_department_map,
                    category_label_cache=category_label_cache,
                )
                if records:
                    mid_table.reconcile_file_records_sync(records)
                    space_synced_count += len(records)
            if space_synced_count == 0:
                mid_table.delete_space_records_sync([space_id])
            if not KnowledgeSpaceContentStat.renew_lock_sync(owner_token):
                raise RuntimeError("Knowledge space content projection owner lock lost before space ack")
            if not KnowledgeSpaceContentStat.ack_claimed_sync(owner_token, [item.member]):
                raise RuntimeError("Failed to acknowledge knowledge space content space projection")
            logger.info(
                "Synced pending knowledge space content stats. space_id={}, upserted={}",
                space_id,
                space_synced_count,
            )

        status = KnowledgeSpaceContentStat.queue_status_sync()
        projection_lag_ms = (
            max(0, KnowledgeSpaceContentStat._now_ms() - min(item.enqueued_at_ms for item in claimed)) if claimed else 0
        )
        result = {
            **status,
            "reclaimed_count": 0,
            "batch_duration_ms": KnowledgeSpaceContentStat._now_ms() - batch_started_ms,
            "projection_lag_ms": projection_lag_ms,
            "last_success_at": int(datetime.now().timestamp()),
            "failure_stage": None,
            "degraded": bool(invalid_items)
            or status.get("dead_count", 0) > 0
            or status["pending_count"] > KnowledgeSpaceContentStat.FILE_BATCH_SIZE,
            "processed_count": len(members) - len(invalid_items),
            "failed_count": len(invalid_items),
        }
        logger.info("Knowledge space content incremental projection completed. {}", result)
        return result
    except Exception as exc:
        logger.exception(
            "Knowledge space content incremental projection failed. degraded=true failure_stage={}",
            failure_stage or "unknown",
        )
        if claimed:
            if isinstance(exc, BatchWriteError) and failure_stage == "file_projection":
                successful = [
                    item.member
                    for item in claimed
                    if item.kind == "file" and str(item.resource_id) in exc.successful_ids
                ]
                if successful and not KnowledgeSpaceContentStat.ack_claimed_sync(owner_token, successful):
                    raise RuntimeError("Failed to acknowledge successful projection batch items") from exc
            KnowledgeSpaceContentStat.fail_claimed_sync(owner_token, [item.member for item in claimed], exc)
            raise QueuedProjectionFailure(str(exc)) from exc
        raise
    finally:
        KnowledgeSpaceContentStat.release_lock_sync(owner_token)
        if KnowledgeSpaceContentStat.has_pending_sync():
            KnowledgeSpaceContentStat.schedule_pending_sync_now()


def _content_stat_event_data(envelope):
    event_type = BaseTelemetryTypeEnum(envelope.event_type)
    data_cls = {
        BaseTelemetryTypeEnum.PORTAL_DOCUMENT_READ: PortalDocumentReadEventData,
        BaseTelemetryTypeEnum.PORTAL_DOCUMENT_DOWNLOAD: PortalDocumentDownloadEventData,
        BaseTelemetryTypeEnum.PORTAL_FAVORITE: PortalFavoriteEventData,
    }[event_type]
    return event_type, data_cls(
        source_app=envelope.source_app,
        scene=envelope.scene,
        entry_point=envelope.entry_point,
        resource_type="document",
        space_id=envelope.dimensions.get("space_id"),
        file_id=envelope.dimensions.get("file_id"),
        status="success",
        content_stat_schema_version=2,
        content_stat_local_date=envelope.local_date,
        content_stat_daily_id=envelope.daily_id,
        content_stat_snapshot=envelope.dimensions,
    )


def _count_content_stat_raw_events(envelope) -> int:
    prefix = envelope.event_type
    response = get_statistics_es_connection_sync().count(
        index=telemetry_service.index_name,
        body={
            "query": {
                "bool": {
                    "filter": [
                        {"term": {"event_type": envelope.event_type}},
                        {
                            "term": {
                                f"event_data.{prefix}_content_stat_schema_version": 2,
                            }
                        },
                        {
                            "term": {
                                f"event_data.{prefix}_content_stat_daily_id.keyword": envelope.daily_id,
                            }
                        },
                    ]
                }
            }
        },
    )
    return int(response.get("count", 0) or 0)


@bisheng_celery.task()
@bounded_telemetry_task
def sync_pending_knowledge_space_content_events():
    """Persist raw events and reconcile daily aggregates with at-least-once delivery."""
    KnowledgeSpaceContentStat.clear_event_scheduled_sync()
    owner_token = KnowledgeSpaceContentStat.acquire_lock_sync()
    if owner_token is None:
        return {"degraded": True, "failure_stage": "owner_lock"}
    processed = failed = 0
    event_ids = []
    active_ids = set()

    def guard():
        checkpoint()
        if not KnowledgeSpaceContentStat.renew_lock_sync(
            owner_token
        ) or not KnowledgeSpaceContentStat.renew_event_claims_sync(owner_token, sorted(active_ids)):
            raise RuntimeError("Knowledge space content event projection lease lost")

    def reject(errors):
        nonlocal failed
        for event_id, reason in errors.items():
            if KnowledgeSpaceContentStat.fail_claimed_sync(owner_token, [event_id], reason, events=True) != 1:
                raise RuntimeError(f"Failed to return event claim {event_id}")
            active_ids.discard(event_id)
            failed += 1
            logger.error("content_stat.event.failed event_id={} reason={}", event_id, reason)

    try:
        event_ids = KnowledgeSpaceContentStat.claim_event_pending_sync(owner_token)
        active_ids.update(event_ids)
        if event_ids:
            guard()
            envelopes, errors = KnowledgeSpaceContentStat.get_event_payloads_sync(event_ids)
            reject(errors)
            floor = KnowledgeSpaceContentStat.get_replay_floor_sync()
            expired = [key for key, envelope in envelopes.items() if envelope.occurred_at < floor]
            if expired:
                if not KnowledgeSpaceContentStat.ack_event_claimed_sync(owner_token, expired):
                    raise RuntimeError("Failed to acknowledge events before replay floor")
                active_ids.difference_update(expired)
            events, errors = [], {}
            for key in sorted(active_ids):
                envelope = envelopes[key]
                try:
                    event_type, event_data = _content_stat_event_data(envelope)
                    events.append(
                        {
                            "event_id": key,
                            "user_id": envelope.user_id,
                            "event_type": event_type,
                            "timestamp": envelope.occurred_at,
                            "trace_id": trace_id_var.get(),
                            "event_data": event_data,
                        }
                    )
                except Exception as exc:
                    errors[key] = str(exc)
            reject(errors)
            raw_errors = telemetry_service.record_events_sync_strict(events, guard=guard)
            reject(raw_errors)
            groups = {}
            for key in sorted(active_ids):
                envelope = envelopes[key]
                groups.setdefault((envelope.event_type, envelope.daily_id), []).append(key)
            searches = []
            for event_type, daily_id in groups:
                searches.extend(
                    [
                        {"index": telemetry_service.index_name},
                        {
                            "size": 0,
                            "track_total_hits": True,
                            "query": {
                                "bool": {
                                    "filter": [
                                        {"term": {"event_type": event_type}},
                                        {"term": {f"event_data.{event_type}_content_stat_schema_version": 2}},
                                        {"term": {f"event_data.{event_type}_content_stat_daily_id.keyword": daily_id}},
                                    ]
                                }
                            },
                        },
                    ]
                )
            updates, errors = [], {}
            if searches:
                guard()
                responses = get_statistics_es_connection_sync().msearch(searches=searches).get("responses", [])
                if len(responses) != len(groups):
                    raise RuntimeError("Content event count batch incomplete response")
                for keys, response in zip(groups.values(), responses, strict=True):
                    total = response.get("hits", {}).get("total", {})
                    if (
                        response.get("error")
                        or response.get("timed_out")
                        or response.get("_shards", {}).get("failed", 0)
                        or total.get("relation") != "eq"
                        or total.get("value", -1) < len(keys)
                    ):
                        errors.update(dict.fromkeys(keys, "Raw event count unavailable or incomplete"))
                    else:
                        updates.append((envelopes[keys[0]], int(total["value"])))
                reject(errors)
                guard()
                daily_errors = KnowledgeSpaceContentStat().upsert_events_daily_sync(updates)
                reject(
                    {
                        key: daily_errors[envelopes[key].daily_id]
                        for key in list(active_ids)
                        if envelopes[key].daily_id in daily_errors
                    }
                )
            if active_ids:
                guard()
                if not KnowledgeSpaceContentStat.ack_event_claimed_sync(owner_token, sorted(active_ids)):
                    raise RuntimeError("Failed to acknowledge content event batch")
                processed = len(active_ids)
                active_ids.clear()
            logger.info(
                "content_stat.events.progress claimed={} groups={} processed={} failed={}",
                len(event_ids),
                len(groups),
                processed,
                failed,
            )
        status = KnowledgeSpaceContentStat.event_queue_status_sync()
        return {
            **status,
            "processed_count": processed,
            "failed_count": failed,
            "degraded": (
                failed > 0
                or status.get("event_dead_count", 0) > 0
                or status["event_pending_count"] > KnowledgeSpaceContentStat.FILE_BATCH_SIZE
                or status["event_oldest_pending_age_ms"] >= 300_000
            ),
        }
    except Exception as exc:
        if event_ids:
            KnowledgeSpaceContentStat.fail_claimed_sync(owner_token, event_ids, exc, events=True)
            raise QueuedProjectionFailure(str(exc)) from exc
        raise
    finally:
        KnowledgeSpaceContentStat.release_lock_sync(owner_token)
        if KnowledgeSpaceContentStat.has_event_pending_sync():
            KnowledgeSpaceContentStat.schedule_event_pending_sync_now()


@bisheng_celery.task()
@bounded_telemetry_task
def recover_knowledge_space_content_stat_leases():
    trace_id_var.set(f"recover_knowledge_space_content_stat_leases_task_{generate_uuid()}")
    try:
        reclaimed_count = KnowledgeSpaceContentStat.reclaim_expired_sync()
        reclaimed_event_count = KnowledgeSpaceContentStat.reclaim_expired_events_sync()
        status = KnowledgeSpaceContentStat.queue_status_sync()
        event_status = KnowledgeSpaceContentStat.event_queue_status_sync()
        result = {
            **status,
            **event_status,
            "reclaimed_count": reclaimed_count,
            "reclaimed_event_count": reclaimed_event_count,
            "batch_duration_ms": 0,
            "projection_lag_ms": status["oldest_pending_age_ms"],
            "last_success_at": int(datetime.now().timestamp()),
            "failure_stage": None,
            "degraded": (
                status.get("dead_count", 0) > 0
                or event_status.get("event_dead_count", 0) > 0
                or status["pending_count"] > KnowledgeSpaceContentStat.FILE_BATCH_SIZE
                or event_status["event_pending_count"] > KnowledgeSpaceContentStat.FILE_BATCH_SIZE
                or event_status["event_oldest_pending_age_ms"] >= 300_000
            ),
        }
        if KnowledgeSpaceContentStat.has_pending_sync():
            KnowledgeSpaceContentStat.schedule_pending_sync_now()
        if KnowledgeSpaceContentStat.has_event_pending_sync():
            KnowledgeSpaceContentStat.schedule_event_pending_sync_now()
        result["recovered_jobs"] = recover_due_jobs()
        logger.info("Knowledge space content lease recovery completed. {}", result)
        return result
    except Exception:
        logger.exception("Knowledge space content lease recovery failed. degraded=true failure_stage=lease_recovery")
        raise


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
        app_list = WorkFlowService.get_all_apps_by_time_range_sync(
            start_time=start_date, end_time=end_date, page=page, page_size=page_size
        )
        page += 1
        if not app_list:
            break
        records = []
        user_ids = set()
        for app in app_list:
            if app["user_id"] not in user_map:
                user_ids.add(app["user_id"])
        user_map = get_user_from_ids_with_cache(list(user_ids), user_map)

        for app in app_list:
            user = user_map.get(app["user_id"], None)
            records.append(
                AppIncrementRecord(
                    es_id=f"app_{app['id']}",
                    user_id=app["user_id"],
                    user_name=user.user_name if user else "",
                    user_group_infos=[
                        UserGroupInfo(user_group_id=group.id, user_group_name=group.group_name) for group in user.groups
                    ]
                    if user
                    else [],
                    user_role_infos=[
                        UserRoleInfo(role_id=role.id, role_name=role.role_name, group_id=role.group_id)
                        for role in user.roles
                    ]
                    if user
                    else [],
                    user_department_infos=[
                        UserDepartmentInfo(department_id=dept.id, department_name=dept.name)
                        for dept in getattr(user, "departments", []) or []
                    ]
                    if user
                    else [],
                    app_id=app["id"],
                    app_name=app["name"],
                    app_type=convert_flow_type(app["flow_type"]),
                    timestamp=int(app["create_time"].timestamp()),
                )
            )
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
        knowledge_list = KnowledgeService.get_all_knowledge_by_time_range(
            start_date, end_date, page=page, page_size=page_size
        )
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
            records.append(
                KnowledgeIncrementRecord(
                    es_id=f"knowledge_{knowledge.id}",
                    user_id=knowledge.user_id,
                    user_name=user.user_name if user else "",
                    user_group_infos=[
                        UserGroupInfo(user_group_id=group.id, user_group_name=group.group_name) for group in user.groups
                    ]
                    if user
                    else [],
                    user_role_infos=[
                        UserRoleInfo(role_id=role.id, role_name=role.role_name, group_id=role.group_id)
                        for role in user.roles
                    ]
                    if user
                    else [],
                    user_department_infos=[
                        UserDepartmentInfo(department_id=dept.id, department_name=dept.name)
                        for dept in getattr(user, "departments", []) or []
                    ]
                    if user
                    else [],
                    knowledge_id=knowledge.id,
                    knowledge_name=knowledge.name,
                    knowledge_type=knowledge.type,
                    timestamp=int(knowledge.create_time.timestamp()),
                )
            )
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
        result = mid_table.get_records_by_time_range_sync(
            start_time=int(start_date.timestamp()), end_time=int(end_date.timestamp()), page=page, page_size=page_size
        )
        page += 1
        if not result:
            break
        records = []
        for record in result:
            es_id = record["_id"]
            record = record["_source"]
            records.append(
                UserInteractRecord(
                    es_id=es_id,
                    user_id=record["user_context"]["user_id"],
                    user_name=record["user_context"]["user_name"],
                    user_group_infos=[
                        UserGroupInfo(user_group_id=group["user_group_id"], user_group_name=group["user_group_name"])
                        for group in record["user_context"].get("user_group_infos", [])
                    ],
                    user_role_infos=[
                        UserRoleInfo(
                            role_id=role["role_id"], role_name=role["role_name"], group_id=role.get("group_id", 0)
                        )
                        for role in record["user_context"].get("user_role_infos", [])
                    ],
                    user_department_infos=[
                        UserDepartmentInfo(department_id=d["department_id"], department_name=d["department_name"])
                        for d in record["user_context"].get("user_department_infos", [])
                    ],
                    event_id=record["event_id"],
                    timestamp=record["timestamp"],
                    message_id=record["event_data"]["message_feedback_message_id"],
                    interact_type=record["event_data"]["message_feedback_operation_type"],
                    app_id=record["event_data"]["message_feedback_app_id"],
                    app_name=record["event_data"]["message_feedback_app_name"],
                )
            )
        mid_table.insert_records_sync(records)
    # Implement the actual logic here
    logger.info("Successfully synced mid_user_interact_dtl table.")

from datetime import datetime, timedelta
from typing import List

from loguru import logger
from sqlmodel import select

from bisheng.api.services.workflow import WorkFlowService
from bisheng.common.constants.enums.telemetry import ApplicationTypeEnum
from bisheng.common.schemas.telemetry.base_telemetry_schema import UserGroupInfo, UserRoleInfo, UserDepartmentInfo
from bisheng.core.context.tenant import bypass_tenant_filter
from bisheng.core.database import get_sync_db_session
from bisheng.core.logger import trace_id_var
from bisheng.database.models.flow import FlowType
from bisheng.knowledge.domain.models.knowledge import Knowledge, KnowledgeTypeEnum
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile, KnowledgeFileStatus, FileType
from bisheng.knowledge.domain.services.knowledge_service import KnowledgeService
from bisheng.telemetry.domain.mid_table.app_increment import AppIncrement, AppIncrementRecord
from bisheng.telemetry.domain.mid_table.base import BaseMidTable
from bisheng.telemetry.domain.mid_table.knowledge_increment import KnowledgeIncrement, KnowledgeIncrementRecord
from bisheng.telemetry.domain.mid_table.knowledge_space_content import KnowledgeSpaceContentStat
from bisheng.telemetry.domain.mid_table.user_increment import UserIncrement, UserIncrementRecord
from bisheng.telemetry.domain.mid_table.user_interact import UserInteract, UserInteractRecord
from bisheng.user.domain.services.user import UserService
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


def get_user_from_ids_with_cache(user_ids: List[int], user_map: dict):
    if user_ids:
        with bypass_tenant_filter():
            user_list = UserService.get_user_all_info(user_ids=user_ids, page=0, page_size=0)
        user_map.update({user.user_id: user for user in user_list})
    return user_map


def _get_success_space_file_rows(page: int, page_size: int):
    statement = (
        select(KnowledgeFile, Knowledge)
        .join(Knowledge, KnowledgeFile.knowledge_id == Knowledge.id)
        .where(
            Knowledge.type == KnowledgeTypeEnum.SPACE.value,
            KnowledgeFile.file_type == FileType.FILE.value,
            KnowledgeFile.status == KnowledgeFileStatus.SUCCESS.value,
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
        .where(KnowledgeFile.id.in_(file_ids))
    )
    with bypass_tenant_filter():
        with get_sync_db_session() as session:
            return session.exec(statement).all()


def _build_knowledge_space_content_records(rows, user_map: dict, *, sync_run_id: str = None):
    if not rows:
        return [], user_map
    user_ids = {
        int(file_record.user_id)
        for file_record, _ in rows
        if file_record.user_id and int(file_record.user_id) not in user_map
    }
    user_map = get_user_from_ids_with_cache(list(user_ids), user_map)
    records = []
    for file_record, space in rows:
        uploader = user_map.get(int(file_record.user_id or 0))
        records.append(
            KnowledgeSpaceContentStat.build_file_record(
                file_record=file_record,
                space=space,
                uploader=uploader,
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
    synced_count = 0

    while True:
        rows = _get_success_space_file_rows(page, page_size)
        page += 1
        if not rows:
            break

        records, user_map = _build_knowledge_space_content_records(rows, user_map, sync_run_id=sync_run_id)

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

            records, user_map = _build_knowledge_space_content_records(visible_rows, user_map)
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
                records, user_map = _build_knowledge_space_content_records(rows, user_map)
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

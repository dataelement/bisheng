from datetime import datetime, timedelta
from typing import List

from loguru import logger

from bisheng.api.services.workflow import WorkFlowService
from bisheng.common.constants.enums.telemetry import ApplicationTypeEnum
from bisheng.common.schemas.telemetry.base_telemetry_schema import UserGroupInfo, UserRoleInfo
from bisheng.core.logger import trace_id_var
from bisheng.database.models.flow import FlowType
from bisheng.knowledge.domain.services.knowledge_service import KnowledgeService
from bisheng.telemetry.domain.mid_table.app_increment import AppIncrement, AppIncrementRecord
from bisheng.telemetry.domain.mid_table.base import BaseMidTable
from bisheng.telemetry.domain.mid_table.knowledge_increment import KnowledgeIncrement, KnowledgeIncrementRecord
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
        FlowType.FLOW.value: ApplicationTypeEnum.SKILL,
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
                timestamp=int(user.create_time.timestamp())
            ))
        mid_table.insert_records_sync(records)

    # This is a placeholder for the actual data synchronization logic
    logger.info(f"Successfully synced mid_user_increment from {start_date} to {end_date}")


def get_user_from_ids_with_cache(user_ids: List[int], user_map: dict):
    if user_ids:
        user_list = UserService.get_user_all_info(user_ids=user_ids, page=0, page_size=0)
        user_map.update({user.user_id: user for user in user_list})
    return user_map


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

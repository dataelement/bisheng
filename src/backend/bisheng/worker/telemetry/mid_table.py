from datetime import datetime, timedelta

from loguru import logger

from bisheng.common.schemas.telemetry.base_telemetry_schema import UserGroupInfo, UserRoleInfo
from bisheng.telemetry.domain.mid_table.user_increment import UserIncrement, UserIncrementRecord
from bisheng.user.domain.services.user import UserService
from bisheng.worker.main import bisheng_celery


@bisheng_celery.task()
def sync_mid_user_increment(start_date: str = None, end_date: str = None):
    if start_date is None or end_date is None:
        # default to yesterday's date
        now = datetime.now()
        start_date = (now - timedelta(days=1)).strftime("%Y-%m-%d 00:00:00")
        end_date = datetime(year=now.year, month=now.month, day=now.day, hour=0, minute=0, second=0)
    else:
        start_date = datetime.fromisoformat(start_date)
        end_date = datetime.fromisoformat(end_date)

    mid_table = UserIncrement()
    lastest_time = mid_table.get_latest_record_time()
    if lastest_time:
        start_date = datetime.fromtimestamp(lastest_time)

    if end_date < start_date:
        logger.error(f"end_date {end_date} is before start_date {start_date}")
        return
    logger.info(f"Syncing mid_user_increment from {start_date} to {end_date}")
    # Here would be the logic to fetch data from the source and insert into mid_user_increment
    page, page_size = 1, 1000

    while True:
        user_list = UserService.get_user_by_time_range(start_time=start_date, end_time=end_date,
                                                       page=page, page_size=page_size)
        page += 1
        if not user_list:
            break
        records = []
        for user in user_list:
            records.append(UserIncrementRecord(
                user_id=user.user_id,
                user_name=user.user_name,
                user_group_infos=[UserGroupInfo(user_group_id=group.id, user_group_name=group.group_name)
                                  for group in user.groups],
                user_role_infos=[UserRoleInfo(role_id=role.id, role_name=role.name, group_id=role.group_id)
                                 for role in user.roles],
                create_time=int(user.create_time.timestamp())
            ))
        mid_table.insert_record(records)

    # This is a placeholder for the actual data synchronization logic
    logger.info(f"Successfully synced mid_user_increment from {start_date} to {end_date}")

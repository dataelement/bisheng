import datetime
import time
import uuid

from loguru import logger
import schedule

from bisheng.api.services.audit_log import AuditLogService
from bisheng.api.v1.schema.audit import DayCron
from bisheng.database.models.message import MessageDao
from bisheng.database.models.scheduled_task_logs import ScheduledTaskLogs, ScheduledTaskLogsDao, LogType
from bisheng.worker import check_model_status_task

# day: bool
EXEC_TASKS = {}

# todo 修复好celery beat的bug后，使用celery beat来代替schedule
def check_review_message_task():
    session_config = AuditLogService.get_session_config()
    if not session_config.flag:
        # 未开启审查，则跳过
        return
    hour, minute = session_config.get_hour_minute()
    schedule_dict = {
        'hour': hour,
        'minute': minute
    }
    now = datetime.datetime.now()
    exec_time = datetime.datetime(now.year, now.month, now.day, hour, minute)
    is_current_day = False
    day_of_weeks = session_config.get_celery_crontab_week()
    if day_of_weeks is not None:
        day_of_weeks = day_of_weeks -1
        if day_of_weeks < 0:
            day_of_weeks = 6
        if now.weekday() == day_of_weeks:
            is_current_day = True
    else:
        is_current_day = True

    # 不是今天执行或者没到时间
    if not is_current_day or now < exec_time:
        return

    key = exec_time.strftime('%Y-%m-%d %H:%M')
    # 今天已经执行过
    if key in EXEC_TASKS:
        return
    EXEC_TASKS[key] = schedule_dict


    end_date = now.replace(hour=hour, minute=minute)
    if session_config.day_cron == DayCron.Day.value:
        old_time = datetime.timedelta(days=1)
    else:
        old_time = datetime.timedelta(weeks=1)
    start_date = end_date - old_time

    logger.info(f'start review_session_message start_date={start_date} end_date={end_date}')

    # 获取期间有更新的会话
    page = 1
    page_size = 100
    while True:
        res, total = MessageDao.app_list_group_by_chat_id(page_size, page, start_date=start_date, end_date=end_date)
        if len(res) == 0:
            break
        for one in res:
            AuditLogService.review_one_session(one['chat_id'])
        page += 1

    logger.debug(f'review_session_message over start_date={start_date} end_date={end_date}')


def catch_task():
    task_id = str(uuid.uuid4())
    task_name = "check_review_message_task"
    data = ScheduledTaskLogs(task_id=task_id, task_name=task_name, log_type=LogType.STARTED.value)
    ScheduledTaskLogsDao.insert_one(data)
    try:
        check_review_message_task()
        data = ScheduledTaskLogs(task_id=task_id, task_name=task_name, log_type=LogType.FINISHED.value,log_content={"status":"success"})
        ScheduledTaskLogsDao.insert_one(data)
    except Exception as e:
        logger.exception(f'catch_task error')
        data = ScheduledTaskLogs(task_id=task_id, task_name=task_name, log_type=LogType.FINISHED.value,log_content={"status":"failed","message":str(e)})
        ScheduledTaskLogsDao.insert_one(data)

schedule.every(1).minute.do(catch_task)
schedule.every(20).minutes.do(check_model_status_task)

def main():
    logger.info('start schedule')
    while True:
        schedule.run_pending()
        time.sleep(30)


if __name__ == '__main__':
    main()

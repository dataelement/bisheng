import uuid
from datetime import datetime, timedelta

from loguru import logger

from bisheng.api.services.audit_log import AuditLogService
from bisheng.api.v1.schema.audit import DayCron
from bisheng.database.models.message import MessageDao
from bisheng.database.models.scheduled_task_logs import ScheduledTaskLogs, ScheduledTaskLogsDao, LogType
from bisheng.worker import bisheng_celery
task_name = "review_session_message"
def insert_start(task_id):
    data = ScheduledTaskLogs(task_id=task_id,task_name=task_name,log_type=LogType.STARTED.value)
    ScheduledTaskLogsDao.insert_one(data)

def insert_finish(task_id,review_num,start_date,end_date):
    log_content = {"review_num":review_num,"start_date":start_date,"end_date":end_date}
    data = ScheduledTaskLogs(task_id=task_id,task_name=task_name,log_type=LogType.FINISHED.value,log_content=log_content)
    ScheduledTaskLogsDao.insert_one(data)

@bisheng_celery.task
def review_session_message():
    """
    审查会话产生的消息
    """
    task_id = str(uuid.uuid4())
    insert_start(task_id)
    session_config = AuditLogService.get_session_config()
    if not session_config.flag:
        # 未开启审查，则跳过
        return
    hour, minute = session_config.hour_cron.split(':')
    end_date = datetime.now().replace(hour=int(hour), minute=int(minute))
    if session_config.day_cron == DayCron.Day.value:
        old_time = timedelta(days=1)
    else:
        old_time = timedelta(weeks=1)
    start_date = end_date - old_time

    # 获取期间有更新的会话
    page = 1
    page_size = 100
    review_num = 0
    while True:
        res, total = MessageDao.app_list_group_by_chat_id(page_size, page, start_date=start_date, end_date=end_date)
        if len(res) == 0:
            break
        for one in res:
            AuditLogService.review_one_session(one['chat_id'])
        review_num += len(res)
        page += 1
    insert_finish(task_id,review_num,start_date,end_date)
    logger.debug(f'review_session_message over start_date={start_date} end_date={end_date}')


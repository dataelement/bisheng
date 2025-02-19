from datetime import datetime, timedelta

from loguru import logger

from bisheng.api.services.audit_log import AuditLogService
from bisheng.api.v1.schema.audit import DayCron
from bisheng.database.models.message import MessageDao
from bisheng.worker import bisheng_celery


@bisheng_celery.task
def review_session_message():
    """
    审查会话产生的消息
    """
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
    while True:
        res, total = MessageDao.app_list_group_by_chat_id(page_size, page, start_date=start_date, end_date=end_date)
        if len(res) == 0:
            break
        for one in res:
            AuditLogService.review_one_session(one['chat_id'])
        page += 1

    logger.debug(f'review_session_message over start_date={start_date} end_date={end_date}')


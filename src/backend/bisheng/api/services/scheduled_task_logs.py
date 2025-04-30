from typing import List

from bisheng.api.services.base import BaseService
from bisheng.database.models.scheduled_task_logs import ScheduledTaskLogsDao, ScheduledTaskLogs


class ScheduledTaskLogsService(BaseService):
    @classmethod
    def get_logs_by_task_name(cls, task_name) ->List[ScheduledTaskLogs]:
        result = ScheduledTaskLogsDao.get_by_task_name(task_name=task_name)
        return result

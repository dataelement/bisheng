from fastapi import APIRouter, Depends

from bisheng.api.services.scheduled_task_logs import ScheduledTaskLogsService
from bisheng.api.services.user_service import get_login_user
from bisheng.api.v1.schemas import (resp_200)

router = APIRouter(prefix='/scheduled_task', dependencies=[Depends(get_login_user)])


@router.get('/task_log', status_code=200)
def get_versions(*, task_name: str):
    """
    获取技能对应的版本列表
    """
    data = ScheduledTaskLogsService.get_logs_by_task_name(task_name)
    return resp_200(data={"task_log": data})

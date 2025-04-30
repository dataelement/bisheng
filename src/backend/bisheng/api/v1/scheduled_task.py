import json
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi_jwt_auth import AuthJWT
from sqlmodel import select
from starlette.responses import StreamingResponse

from bisheng.api.errcode.base import UnAuthorizedError
from bisheng.api.errcode.flow import FlowOnlineEditError, FlowNameExistsError
from bisheng.api.services.flow import FlowService
from bisheng.api.services.scheduled_task_logs import ScheduledTaskLogsService
from bisheng.api.services.user_service import UserPayload, get_login_user
from bisheng.api.utils import build_flow_no_yield, get_L2_param_from_flow, remove_api_keys
from bisheng.api.v1.schemas import (FlowCompareReq, FlowListRead, FlowVersionCreate, StreamData,
                                    UnifiedResponseModel, resp_200)
from bisheng.database.base import session_getter
from bisheng.database.models.flow import (Flow, FlowCreate, FlowDao, FlowRead, FlowReadWithStyle, FlowType,
                                          FlowUpdate)
from bisheng.database.models.flow_version import FlowVersionDao
from bisheng.database.models.role_access import AccessType
from bisheng.settings import settings
from bisheng.utils.logger import logger

router = APIRouter(prefix='/scheduled_task', dependencies=[Depends(get_login_user)])

@router.get('/task_log', status_code=200)
def get_versions(*, task_name: str):
    """
    获取技能对应的版本列表
    """
    data = ScheduledTaskLogsService.get_logs_by_task_name(task_name)
    return resp_200(data={"task_log": data})

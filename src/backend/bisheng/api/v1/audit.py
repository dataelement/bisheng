from datetime import datetime
from typing import Optional, List

from fastapi import APIRouter, Query, Depends

from bisheng.api.services.user_service import UserPayload, get_login_user
from bisheng.api.v1.schemas import UnifiedResponseModel
from bisheng.api.services.audit_log import AuditLogService

router = APIRouter(prefix='/audit', tags=['AuditLog'])


@router.get('', response_model=UnifiedResponseModel)
def get_audit_logs(*,
                   group_ids: Optional[List[str]] = Query(default=[], description='分组id列表'),
                   operator_ids: Optional[List[int]] = Query(default=[], description='操作人id列表'),
                   start_time: Optional[datetime] = Query(default=None, description='开始时间'),
                   end_time: Optional[datetime] = Query(default=None, description='结束时间'),
                   system_id: Optional[str] = Query(default=None, description='系统模块'),
                   event_type: Optional[str] = Query(default=None, description='操作行为'),
                   page: Optional[int] = Query(default=0, description='页码'),
                   limit: Optional[int] = Query(default=0, description='每页条数'),
                   login_user: UserPayload = Depends(get_login_user)):
    group_ids = [one for one in group_ids if one]
    operator_ids = [one for one in operator_ids if one]
    return AuditLogService.get_audit_log(login_user, group_ids, operator_ids,
                                         start_time, end_time, system_id, event_type, page, limit)


@router.get('/operators', response_model=UnifiedResponseModel)
def get_all_operators(*, login_user: UserPayload = Depends(get_login_user)):
    """
    获取操作过组下资源的所有用户
    """
    return AuditLogService.get_all_operators(login_user)

from datetime import datetime
from typing import Optional, List

from fastapi import APIRouter, Query, Depends, Request, Body

from bisheng.api.services.audit_log import AuditLogService
from bisheng.api.services.user_service import UserPayload, get_login_user
from bisheng.api.v1.schema.audit import AuditSessionConfig
from bisheng.api.v1.schemas import UnifiedResponseModel, resp_200

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

@router.post('/session/config', response_model=UnifiedResponseModel)
def update_session_config(*, request: Request, login_user: UserPayload = Depends(get_login_user),
                          data: AuditSessionConfig = Body(description='会话配置项')):
    """ 更新会话分析策略的配置 """
    AuditLogService.update_session_config(login_user, data)
    return resp_200(data=data)

@router.get('/session/config', response_model=UnifiedResponseModel)
def get_session_config(*, request: Request, login_user: UserPayload = Depends(get_login_user)):
    """ 更新会话分析策略的配置 """
    data = AuditLogService.get_session_config(login_user)
    return resp_200(data=data)

@router.get('/session', response_model=UnifiedResponseModel)
def get_session_list(*, request: Request, login_user: UserPayload = Depends(get_login_user),
                     flow_ids: Optional[List[str]] = Query(default=[], description='应用id列表'),
                     user_ids: Optional[List[str]] = Query(default=[], description='用户id列表'),
                     page: Optional[int] = Query(default=0, description='页码'),
                     page_size: Optional[int] = Query(default=10, description='每页条数')):
    """ 获取所有会话列表 """
    pass

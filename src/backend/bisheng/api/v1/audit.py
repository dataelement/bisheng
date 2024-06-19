from datetime import datetime
from typing import Optional, List

from fastapi import APIRouter, Query, Depends

from bisheng.api.JWT import get_login_user
from bisheng.api.services.user_service import UserPayload
from bisheng.api.v1.schemas import UnifiedResponseModel, resp_200

router = APIRouter(prefix='/audit', tags=['AuditLog'])


@router.get('', response_model=UnifiedResponseModel)
def get_audit_logs(*,
                   group_ids: Optional[List[str]] = Query(default=None, description='分组id列表'),
                   operator_ids: Optional[List[int]] = Query(default=None, description='操作人id列表'),
                   start_time: Optional[datetime] = Query(default=None, description='开始时间'),
                   end_time: Optional[datetime] = Query(default=None, description='结束时间'),
                   system_id: Optional[str] = Query(default=None, description='系统模块'),
                   event_type: Optional[str] = Query(default=None, description='操作行为'),
                   page: Optional[int] = Query(default=0, description='页码'),
                   limit: Optional[int] = Query(default=0, description='每页条数'),
                   login_user: UserPayload = Depends(get_login_user)):
    return resp_200(data={
        'data': [
            {
                "id": "xxxx",
                "operator_id": 1,  # 操作用户的ID
                "operator_name": "xxx",  # 操作用户的用户名
                "group_ids": [1, 2, 3],  # 所属的分组列表
                "system_ids": "chat",  # 系统模块
                "event_type": "create_chat",  # 操作行为
                "object_type": "flow",  # 操作对象类型
                "object_id": 1,  # 操作对象唯一标识
                "object_name": "xxx",  # 操作对象名称
                "note": "备注",  # 备注
                "ip_address": "1.1.1.1",  # 操作时客户端的IP地址
                "create_time": "2023-01-01 00:00:00",  # 操作时间
            }
        ],
        "total": 10,
    })

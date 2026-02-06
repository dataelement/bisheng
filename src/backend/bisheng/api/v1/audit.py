from datetime import datetime
from typing import Optional, List

from fastapi import APIRouter, Query, Depends

from bisheng.api.services.audit_log import AuditLogService
from bisheng.api.v1.schemas import resp_200
from bisheng.common.dependencies.user_deps import UserPayload

router = APIRouter(prefix='/audit', tags=['AuditLog'])


@router.get('')
async def get_audit_logs(*,
                         group_ids: Optional[List[str]] = Query(default=[], description='GroupingidVertical'),
                         operator_ids: Optional[List[int]] = Query(default=[], description='WhoidVertical'),
                         start_time: Optional[datetime] = Query(default=None, description='Start when'),
                         end_time: Optional[datetime] = Query(default=None, description='End time'),
                         system_id: Optional[str] = Query(default=None, description='Module Item'),
                         event_type: Optional[str] = Query(default=None, description='Operation behaviors'),
                         page: Optional[int] = Query(default=0, description='Page'),
                         limit: Optional[int] = Query(default=0, description='Listings Per Page'),
                         login_user: UserPayload = Depends(UserPayload.get_login_user)):
    group_ids = [one for one in group_ids if one]
    operator_ids = [one for one in operator_ids if one]
    return await AuditLogService.get_audit_log(login_user, group_ids, operator_ids,
                                               start_time, end_time, system_id, event_type, page, limit)


@router.get('/operators')
def get_all_operators(*, login_user: UserPayload = Depends(UserPayload.get_login_user)):
    """
    Get all users who have acted on a resource under a group
    """
    return resp_200(data=AuditLogService.get_all_operators(login_user))


@router.get('/session')
async def get_session_list(login_user: UserPayload = Depends(UserPayload.get_login_user),
                           flow_ids: Optional[List[str]] = Query(default=[], description='ApplicationsidVertical'),
                           user_ids: Optional[List[int]] = Query(default=[], description='UsersidVertical'),
                           group_ids: Optional[List[int]] = Query(default=[], description='User GroupsidVertical'),
                           start_date: Optional[datetime] = Query(default=None, description='Start when'),
                           end_date: Optional[datetime] = Query(default=None, description='End time'),
                           feedback: Optional[str] = Query(default=None,
                                                           description='like LikedislikeUnlikecopiedCopy:'),
                           sensitive_status: Optional[int] = Query(default=None,
                                                                   description='Sensitive word review status'),
                           page: Optional[int] = Query(default=1, description='Page'),
                           page_size: Optional[int] = Query(default=10, description='Listings Per Page')):
    """ Filter all session lists """
    data, total = await AuditLogService.get_session_list(login_user, flow_ids, user_ids, group_ids, start_date,
                                                         end_date,
                                                         feedback, sensitive_status, page, page_size)
    return resp_200(data={
        'data': data,
        'total': total
    })


@router.get('/session/export')
async def export_session_messages(login_user: UserPayload = Depends(UserPayload.get_login_user),
                                  flow_ids: Optional[List[str]] = Query(default=[],
                                                                        description='ApplicationsidVertical'),
                                  user_ids: Optional[List[int]] = Query(default=[], description='UsersidVertical'),
                                  group_ids: Optional[List[int]] = Query(default=[],
                                                                         description='User GroupsidVertical'),
                                  start_date: Optional[datetime] = Query(default=None, description='Start when'),
                                  end_date: Optional[datetime] = Query(default=None, description='End time'),
                                  feedback: Optional[str] = Query(default=None,
                                                                  description='like LikedislikeUnlikecopiedCopy:'),
                                  sensitive_status: Optional[int] = Query(default=None,
                                                                          description='Sensitive word review status')):
    """ Exporting a list of session detailscsvDoc. """
    url = await AuditLogService.export_session_messages(login_user, flow_ids, user_ids, group_ids, start_date, end_date,
                                                        feedback, sensitive_status)
    return resp_200(data={
        'url': url
    })


@router.get('/session/export/data')
async def get_session_messages(login_user: UserPayload = Depends(UserPayload.get_login_user),
                               flow_ids: Optional[List[str]] = Query(default=[], description='ApplicationsidVertical'),
                               user_ids: Optional[List[int]] = Query(default=[], description='UsersidVertical'),
                               group_ids: Optional[List[int]] = Query(default=[], description='User GroupsidVertical'),
                               start_date: Optional[datetime] = Query(default=None, description='Start when'),
                               end_date: Optional[datetime] = Query(default=None, description='End time'),
                               feedback: Optional[str] = Query(default=None,
                                                               description='like LikedislikeUnlikecopiedCopy:'),
                               sensitive_status: Optional[int] = Query(default=None,
                                                                       description='Sensitive word review status')):
    """ Export data for a list of session details """
    result = await AuditLogService.get_session_messages(login_user, flow_ids, user_ids, group_ids, start_date, end_date,
                                                        feedback, sensitive_status)
    return resp_200(data={
        'data': result
    })

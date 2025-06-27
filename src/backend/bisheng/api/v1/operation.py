from datetime import datetime
from typing import Optional, List

from fastapi import APIRouter, Query, Depends, Request, Body

from bisheng.api.errcode.base import UnAuthorizedError
from bisheng.api.services.audit_log import AuditLogService
from bisheng.api.services.user_service import UserPayload, get_login_user
from bisheng.api.v1.schema.audit import ReviewSessionConfig
from bisheng.api.v1.schemas import UnifiedResponseModel, resp_200
from bisheng.database.models.group import GroupDao
from bisheng.database.models.session import ReviewStatus
from bisheng.database.models.user_group import UserGroupDao
from bisheng.utils.util import validate_date_range

router = APIRouter(prefix='/operation', tags=['Operation'])

@router.get('/session', response_model=UnifiedResponseModel)
def get_session_list(*, request: Request, login_user: UserPayload = Depends(get_login_user),
                     flow_ids: Optional[List[str]] = Query(default=[], description='应用id列表'),
                     user_ids: Optional[List[int]] = Query(default=[], description='用户id列表'),
                     group_ids: Optional[List[str]] = Query(default=[], description='用户组id列表'),
                     start_date: Optional[datetime] = Query(default=None, description='开始时间'),
                     end_date: Optional[datetime] = Query(default=None, description='结束时间'),
                     feedback: Optional[str] = Query(default=None, description='like：点赞；dislike：点踩；copied：复制'),
                     review_status: Optional[int] = Query(default=None, description='审查状态'),
                     page: Optional[int] = Query(default=1, description='页码'),
                     page_size: Optional[int] = Query(default=10, description='每页条数'),
                     keyword: Optional[str] = Query(default=None,description='历史记录')):
    """ 筛选所有会话列表 """
    if not login_user.is_admin():
        all_group = UserGroupDao.get_user_operation_or_admin_group(login_user.user_id)
        all_group = [str(one.group_id) for one in all_group]
    else:
        all_group = [str(one.id) for one in GroupDao.get_all_group()]
    if len(group_ids) == 0:
        group_ids = all_group
    else:
        group_ids = list(set(group_ids) & set(all_group))
    if len(group_ids) == 0:
        return UnAuthorizedError.return_resp()
    start_date, end_date = validate_date_range(start_date, end_date)
    review_status = [ReviewStatus(review_status)] if review_status else []
    data, total = AuditLogService.get_session_list(user=login_user, flow_ids=flow_ids, user_ids=user_ids,
                                                   group_ids=group_ids, start_date=start_date,
                                                   end_date=end_date,
                                                   feedback=feedback, review_status=review_status,
                                                   page=page, page_size=page_size, keyword=keyword,
                                                   category=['question', 'answer'])
    return resp_200(data={
        'data': data,
        'total': total
    })

@router.get('/export', response_model=UnifiedResponseModel)
def get_session_list(*, request: Request, login_user: UserPayload = Depends(get_login_user),
                     flow_ids: Optional[List[str]] = Query(default=[], description='应用id列表'),
                     user_ids: Optional[List[int]] = Query(default=[], description='用户id列表'),
                     group_ids: Optional[List[str]] = Query(default=[], description='用户组id列表'),
                     start_date: Optional[datetime] = Query(default=None, description='开始时间'),
                     end_date: Optional[datetime] = Query(default=None, description='结束时间'),
                     feedback: Optional[str] = Query(default=None, description='like：点赞；dislike：点踩；copied：复制'),
                     review_status: Optional[int] = Query(default=None, description='审查状态'),
                     page: Optional[int] = Query(default=0, description='页码'),
                     page_size: Optional[int] = Query(default=0, description='每页条数'),
                     keyword: Optional[str] = Query(default=None,description='历史记录')):
    """ 筛选所有会话列表 """
    if not login_user.is_admin():
        all_group = UserGroupDao.get_user_operation_or_admin_group(login_user.user_id)
        all_group = [str(one.group_id) for one in all_group]
    else:
        all_group = [str(one.id) for one in GroupDao.get_all_group()]
    if len(group_ids) == 0:
        group_ids = all_group
    else:
        group_ids = list(set(group_ids) & set(all_group))
    if len(group_ids) == 0:
        return UnAuthorizedError.return_resp()
    start_date, end_date = validate_date_range(start_date, end_date)
    review_status = [ReviewStatus(review_status)] if review_status else []
    all_session, total = AuditLogService.get_session_list(user=login_user, flow_ids=flow_ids, user_ids=user_ids,
                                                          group_ids=group_ids, start_date=start_date,
                                                          end_date=end_date, category=['question', 'answer'],
                                                   feedback=feedback, review_status=review_status, page=page, page_size=page_size, keyword=keyword)
    url = AuditLogService.session_export(all_session, 'operation', start_date, end_date)
    return resp_200(data={"file": url})


@router.get('/session/chart', response_model=UnifiedResponseModel)
async def get_session_chart(request: Request, login_user: UserPayload = Depends(get_login_user),
                            flow_ids: Optional[List[str]] = Query(default=[], description='应用id列表'),
                            group_ids: Optional[List[str]] = Query(default=[], description='用户组id列表'),
                            start_date: Optional[datetime] = Query(default=None, description='开始时间'),
                            end_date: Optional[datetime] = Query(default=None, description='结束时间'),
                            order_field: Optional[str] = Query(default=None, description='排序字段'),
                            order_type: Optional[str] = Query(default=None, description='排序类型'),
                            page: Optional[int] = Query(default=1, description='页码'),
                            page_size: Optional[int] = Query(default=10, description='每页条数')):
    """ 按照用户组聚合统计会话数据 """
    if not login_user.is_admin():
        all_group = UserGroupDao.get_user_operation_or_admin_group(login_user.user_id)
        all_group = [str(one.group_id) for one in all_group]
    else:
        all_group = [str(one.id) for one in GroupDao.get_all_group()]
    if len(group_ids) == 0:
        group_ids = all_group
    else:
        group_ids = list(set(group_ids) & set(all_group))
    if len(group_ids) == 0:
        return UnAuthorizedError.return_resp()
    data, total, total_session_num = AuditLogService.get_session_chart(login_user, flow_ids, group_ids, start_date, end_date,
                                                    order_field, order_type, page, page_size)
    return resp_200(data={
        'data': data,
        'total_session_num': total_session_num,
        'total': total
    })

@router.get('/session/chart/export')
async def export_session_chart(request: Request, login_user: UserPayload = Depends(get_login_user),
                               flow_ids: Optional[List[str]] = Query(default=[], description='应用id列表'),
                               group_ids: Optional[List[str]] = Query(default=[], description='用户组id列表'),
                               start_date: Optional[datetime] = Query(default=None, description='开始时间'),
                               end_date: Optional[datetime] = Query(default=None, description='结束时间'),
                               like_type: Optional[int] = Query(default=1, description='好评类型')):
    """ 根据筛选条件导出最终的结果 """
    if not login_user.is_admin():
        all_group = UserGroupDao.get_user_operation_or_admin_group(login_user.user_id)
        all_group = [str(one.group_id) for one in all_group]
    else:
        all_group = [str(one.id) for one in GroupDao.get_all_group()]
    if len(group_ids) == 0:
        group_ids = all_group
    else:
        group_ids = list(set(group_ids) & set(all_group))
    if len(group_ids) == 0:
        return UnAuthorizedError.return_resp()
    url = AuditLogService.export_operational_session_chart(login_user, flow_ids, group_ids, start_date, end_date,like_type )
    return resp_200(data={
        'url': url
    })

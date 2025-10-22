from fastapi import APIRouter, Depends, Body, Request
from loguru import logger

from bisheng.api.services.invite_code.invite_code import InviteCodeService
from bisheng.api.services.user_service import UserPayload, get_admin_user, get_login_user
from bisheng.api.v1.schemas import resp_200, resp_500
from bisheng.utils import get_request_ip

router = APIRouter(prefix='/invite', tags=['InviteCode'])


@router.post('/code')
async def create_invite_code(request: Request, login_user: UserPayload = Depends(get_admin_user),
                             name: str = Body(..., description='批次名称'),
                             num: int = Body(..., description='当前批次的邀请码数量'),
                             limit: int = Body(..., description='当前批次邀请码的使用次数限制')):
    """
    创建邀请码
    """
    logger.debug(
        f"create invite code user_id: {login_user.user_id}, ip: {get_request_ip(request)}, name: {name}, num: {num}, limit: {limit}")
    codes = await InviteCodeService.create_batch_invite_codes(login_user, name, num, limit)
    return resp_200(data={
        "name": name,
        "limit": limit,
        "codes": codes
    })


@router.post('/bind')
async def bind_invite_code(request: Request, login_user: UserPayload = Depends(get_login_user),
                           code: str = Body(..., embed=True, description='邀请码')):
    """
    绑定邀请码
    """
    result, error = await InviteCodeService.bind_invite_code(login_user, code)
    logger.debug(f"bind_invite_code user_id:{login_user.user_id}, code:{code}, flag:{result}, error:{error}")
    if result:
        return resp_200(message=error)
    else:
        return resp_500(message=error)


@router.get('/code')
async def get_bind_code_num(request: Request, login_user: UserPayload = Depends(get_login_user)):
    """
    获取用户绑定的有效的邀请码的可使用次数
    """
    num = await InviteCodeService.get_invite_code_num(login_user)
    return resp_200(data=num)

from fastapi import APIRouter, Depends
from fastapi.params import Body

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.schemas.api import resp_200, UnifiedResponseModel
from bisheng.share_link.api.dependencies import get_share_link_service
from bisheng.share_link.api.schemas.share_link_schema import GenerateShareLinkRequest

router = APIRouter()


@router.post('/generate_share_link', summary='generate share link',
             response_model=UnifiedResponseModel)
async def generate_share_link(
        req_param: GenerateShareLinkRequest = Body(..., description="generate share link request"),
        login_user: UserPayload = Depends(UserPayload.get_login_user),
        share_link_service=Depends(get_share_link_service)
):
    """
    Generate share link
    :param login_user:
    :param share_link_service:
    :param req_param:
    :return:
    """

    share_link = await share_link_service.generate_share_link(req_param, login_user)

    return resp_200(data=share_link)


@router.get('/{share_token}', summary='get share link info',
            response_model=UnifiedResponseModel)
async def get_share_link_info(
        share_token: str,
        share_link_service=Depends(get_share_link_service)
):
    """
    Get share link info by share token
    :param share_token:
    :param share_link_service:
    :return:
    """

    share_link = await share_link_service.get_share_link_by_token(share_token)

    return resp_200(data=share_link)

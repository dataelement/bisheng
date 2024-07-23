from typing import List

from fastapi import APIRouter, Request, Depends, Query, Body

from bisheng.api.services.tag import TagService
from bisheng.api.services.user_service import UserPayload, get_login_user, get_admin_user
from bisheng.api.v1.schemas import UnifiedResponseModel, resp_200
from bisheng.database.models.group_resource import ResourceTypeEnum
from bisheng.database.models.tag import Tag, TagLink

router = APIRouter(prefix='/tag', tags=['Tag'])


@router.get('', response_model=UnifiedResponseModel[List[Tag]])
def get_all_tag(request: Request,
                login_user: UserPayload = Depends(get_login_user),
                keyword: str = Query(default=None, description='搜索关键字'),
                page: int = Query(default=0, description='页码'),
                limit: int = Query(default=10, description='每页条数')):
    result, total = TagService.get_all_tag(request, login_user, keyword, page, limit)
    return resp_200(data={
        'data': result,
        'total': total
    })


@router.post('', response_model=UnifiedResponseModel[Tag])
def create_tag(request: Request,
               login_user: UserPayload = Depends(get_admin_user),
               name: str = Body(..., embed=True, description='标签名称')):
    result = TagService.create_tag(request, login_user, name)
    return resp_200(result)


@router.put('', response_model=UnifiedResponseModel[Tag])
def update_tag(request: Request,
               login_user: UserPayload = Depends(get_admin_user),
               tag_id: int = Body(..., embed=True, description='标签ID'),
               name: str = Body(..., embed=True, description='标签名称')):
    result = TagService.update_tag(request, login_user, tag_id, name)
    return resp_200(result)


@router.delete('', response_model=UnifiedResponseModel)
def delete_tag(request: Request,
               login_user: UserPayload = Depends(get_admin_user),
               tag_id: int = Body(..., embed=True, description='标签ID')):
    TagService.delete_tag(request, login_user, tag_id)
    return resp_200()


@router.post('/link', response_model=UnifiedResponseModel[TagLink])
def create_tag_link(request: Request,
                    login_user: UserPayload = Depends(get_login_user),
                    tag_id: int = Body(..., embed=True, description='标签ID'),
                    resource_id: str = Body(..., embed=True, description='资源ID'),
                    resource_type: ResourceTypeEnum = Body(..., embed=True, description='资源类型')):
    result = TagService.create_tag_link(request, login_user, tag_id, resource_id, resource_type)
    return resp_200(result)


@router.delete('/link', response_model=UnifiedResponseModel)
def delete_tag_link(
        request: Request,
        login_user: UserPayload = Depends(get_login_user),
        tag_id: int = Body(..., embed=True, description='标签ID'),
        resource_id: str = Body(..., embed=True, description='资源ID'),
        resource_type: ResourceTypeEnum = Body(..., embed=True, description='资源类型')):
    TagService.delete_tag_link(request, login_user, tag_id, resource_id, resource_type)
    return resp_200()


@router.get('/home', response_model=UnifiedResponseModel[List[Tag]])
def get_home_tag(request: Request,
                 login_user: UserPayload = Depends(get_login_user)):
    """
    获取首页展示的标签列表
    """

    result = TagService.get_home_tag(request, login_user)
    return resp_200(result)


@router.post('/home', response_model=UnifiedResponseModel[List[Tag]])
def update_home_tag(request: Request,
                    login_user: UserPayload = Depends(get_admin_user),
                    tag_ids: List[int] = Body(..., embed=True, description='标签ID列表')):
    """
    更新首页展示的标签列表
    """

    result = TagService.update_home_tag(request, login_user, tag_ids)
    return resp_200(result)

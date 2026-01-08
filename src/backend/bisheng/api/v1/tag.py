from typing import List

from fastapi import APIRouter, Request, Depends, Query, Body

from bisheng.api.services.tag import TagService
from bisheng.api.v1.schemas import resp_200
from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.database.models.group_resource import ResourceTypeEnum

router = APIRouter(prefix='/tag', tags=['Tag'])


@router.get('')
def get_all_tag(request: Request,
                login_user: UserPayload = Depends(UserPayload.get_login_user),
                keyword: str = Query(default=None, description='Search keyword ...'),
                page: int = Query(default=0, description='Page'),
                limit: int = Query(default=10, description='Listings Per Page')):
    result, total = TagService.get_all_tag(request, login_user, keyword, page, limit)
    return resp_200(data={
        'data': result,
        'total': total
    })


@router.post('')
def create_tag(request: Request,
               login_user: UserPayload = Depends(UserPayload.get_admin_user),
               name: str = Body(..., embed=True, description='Label Name')):
    result = TagService.create_tag(request, login_user, name)
    return resp_200(result)


@router.put('')
def update_tag(request: Request,
               login_user: UserPayload = Depends(UserPayload.get_admin_user),
               tag_id: int = Body(..., embed=True, description='labelID'),
               name: str = Body(..., embed=True, description='Label Name')):
    result = TagService.update_tag(request, login_user, tag_id, name)
    return resp_200(result)


@router.delete('')
def delete_tag(request: Request,
               login_user: UserPayload = Depends(UserPayload.get_admin_user),
               tag_id: int = Body(..., embed=True, description='labelID')):
    TagService.delete_tag(request, login_user, tag_id)
    return resp_200()


@router.post('/link')
def create_tag_link(request: Request,
                    login_user: UserPayload = Depends(UserPayload.get_login_user),
                    tag_id: int = Body(..., embed=True, description='labelID'),
                    resource_id: str = Body(..., embed=True, description='reasourseID'),
                    resource_type: ResourceTypeEnum = Body(..., embed=True, description='Resource Type')):
    result = TagService.create_tag_link(request, login_user, tag_id, resource_id, resource_type)
    return resp_200(result)


@router.delete('/link')
def delete_tag_link(
        request: Request,
        login_user: UserPayload = Depends(UserPayload.get_login_user),
        tag_id: int = Body(..., embed=True, description='labelID'),
        resource_id: str = Body(..., embed=True, description='reasourseID'),
        resource_type: ResourceTypeEnum = Body(..., embed=True, description='Resource Type')):
    TagService.delete_tag_link(request, login_user, tag_id, resource_id, resource_type)
    return resp_200()


@router.get('/home')
def get_home_tag(request: Request,
                 login_user: UserPayload = Depends(UserPayload.get_login_user)):
    """
    Get a list of tags to show on the homepage
    """

    result = TagService.get_home_tag(request, login_user)
    return resp_200(result)


@router.post('/home')
def update_home_tag(request: Request,
                    login_user: UserPayload = Depends(UserPayload.get_admin_user),
                    tag_ids: List[int] = Body(..., embed=True, description='labelIDVertical')):
    """
    Update the list of tags displayed on the homepage
    """

    result = TagService.update_home_tag(request, login_user, tag_ids)
    return resp_200(result)

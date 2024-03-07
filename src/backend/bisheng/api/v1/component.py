import json
from typing import List

from bisheng.api.services.component import ComponentService
from bisheng.api.v1.schemas import CreateComponentReq, UnifiedResponseModel
from bisheng.database.models.component import Component
from fastapi import APIRouter, Body, Depends
from fastapi_jwt_auth import AuthJWT

router = APIRouter(prefix='/component', tags=['Component'])


@router.get('', response_model=UnifiedResponseModel[List[Component]])
def get_all_components(*,
                       Authorize: AuthJWT = Depends()):
    # get login user
    Authorize.jwt_required()
    current_user = json.loads(Authorize.get_jwt_subject())
    return ComponentService.get_all_component(current_user)


@router.post('', response_model=UnifiedResponseModel[Component])
def save_components(*,
                    data: CreateComponentReq,
                    Authorize: AuthJWT = Depends()):
    # get login user
    Authorize.jwt_required()
    current_user = json.loads(Authorize.get_jwt_subject())
    component = Component(**data.dict(), user_id=current_user.get('user_id'), user_name=current_user.get('user_name'))
    return ComponentService.save_component(component)


@router.patch('', response_model=UnifiedResponseModel[Component])
def update_component(*,
                     data: CreateComponentReq,
                     Authorize: AuthJWT = Depends()):
    # get login user
    Authorize.jwt_required()
    current_user = json.loads(Authorize.get_jwt_subject())
    component = Component(**data.dict(), user_id=current_user.get('user_id'), user_name=current_user.get('user_name'))
    return ComponentService.update_component(component)


@router.delete('', response_model=UnifiedResponseModel[Component])
def delete_component(*,
                     name: str = Body(..., embed=True, description='组件名'),
                     Authorize: AuthJWT = Depends()):
    Authorize.jwt_required()
    current_user = json.loads(Authorize.get_jwt_subject())

    return ComponentService.delete_component(current_user.get('user_id'), name)

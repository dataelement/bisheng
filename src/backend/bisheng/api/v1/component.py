import json
from typing import List

from fastapi import APIRouter, Body, Depends
from fastapi_jwt_auth import AuthJWT

from bisheng import __version__
from bisheng.api.services.component import ComponentService
from bisheng.api.services.user_service import get_login_user
from bisheng.api.utils import update_frontend_node_with_template_values
from bisheng.api.v1.schemas import (CreateComponentReq, CustomComponentCode, UnifiedResponseModel,
                                    resp_200, resp_500)
from bisheng.database.models.component import Component
from bisheng.interface.custom import CustomComponent
from bisheng.interface.custom.directory_reader import DirectoryReader
from bisheng.interface.custom.utils import build_custom_component_template

router = APIRouter(prefix='/component', tags=['Component'], dependencies=[Depends(get_login_user)])


@router.get('', response_model=UnifiedResponseModel[List[Component]])
def get_all_components(*, Authorize: AuthJWT = Depends()):
    # get login user
    Authorize.jwt_required()
    current_user = json.loads(Authorize.get_jwt_subject())
    return ComponentService.get_all_component(current_user)


@router.post('', response_model=UnifiedResponseModel[Component])
def save_components(*, data: CreateComponentReq, Authorize: AuthJWT = Depends()):
    # get login user
    Authorize.jwt_required()
    current_user = json.loads(Authorize.get_jwt_subject())
    component = Component(**data.dict(),
                          user_id=current_user.get('user_id'),
                          user_name=current_user.get('user_name'),
                          version=__version__)
    return ComponentService.save_component(component)


@router.patch('', response_model=UnifiedResponseModel[Component])
def update_component(*, data: CreateComponentReq, Authorize: AuthJWT = Depends()):
    # get login user
    Authorize.jwt_required()
    current_user = json.loads(Authorize.get_jwt_subject())
    component = Component(**data.dict(),
                          user_id=current_user.get('user_id'),
                          user_name=current_user.get('user_name'),
                          version=__version__)
    return ComponentService.update_component(component)


@router.delete('', response_model=UnifiedResponseModel[Component])
def delete_component(*,
                     name: str = Body(..., embed=True, description='组件名'),
                     Authorize: AuthJWT = Depends()):
    Authorize.jwt_required()
    current_user = json.loads(Authorize.get_jwt_subject())

    return ComponentService.delete_component(current_user.get('user_id'), name)


@router.post('/custom_component', response_model=UnifiedResponseModel[Component])
async def custom_component(
        raw_code: CustomComponentCode,
        Authorize: AuthJWT = Depends(),
):
    Authorize.jwt_required()
    current_user = json.loads(Authorize.get_jwt_subject())

    component = CustomComponent(code=raw_code.code)

    built_frontend_node = build_custom_component_template(component,
                                                          user_id=current_user.get('user_id'))

    built_frontend_node = update_frontend_node_with_template_values(built_frontend_node,
                                                                    raw_code.frontend_node)
    return resp_200(data=built_frontend_node)


@router.post('/custom_component/reload', response_model=UnifiedResponseModel[Component])
async def reload_custom_component(path: str, Authorize: AuthJWT = Depends()):
    from bisheng.interface.custom.utils import build_custom_component_template

    try:
        reader = DirectoryReader('')
        valid, content = reader.process_file(path)
        if not valid:
            raise ValueError(content)
        Authorize.jwt_required()
        current_user = json.loads(Authorize.get_jwt_subject())

        extractor = CustomComponent(code=content)
        return resp_200(
            data=build_custom_component_template(extractor, user_id=current_user.get('user_id')))
    except Exception as exc:
        print(exc)
        return resp_500(message=str(exc))


@router.post('/custom_component/update', response_model=UnifiedResponseModel[Component])
async def custom_component_update(
        raw_code: CustomComponentCode,
        Authorize: AuthJWT = Depends(),
):
    component = CustomComponent(code=raw_code.code)
    Authorize.jwt_required()
    current_user = json.loads(Authorize.get_jwt_subject())

    component_node = build_custom_component_template(component,
                                                     user_id=current_user.get('user_id'),
                                                     update_field=raw_code.field)
    # Update the field
    return resp_200(data=component_node)

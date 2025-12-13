from fastapi import APIRouter, Body, Depends

from bisheng.api.services.component import ComponentService
from bisheng.api.utils import update_frontend_node_with_template_values
from bisheng.api.v1.schemas import (CreateComponentReq, CustomComponentCode, resp_200)
from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.database.models.component import Component
from bisheng.interface.custom import CustomComponent
from bisheng.interface.custom.directory_reader import DirectoryReader
from bisheng.interface.custom.utils import build_custom_component_template

router = APIRouter(prefix='/component', tags=['Component'], dependencies=[Depends(UserPayload.get_login_user)])


@router.get('')
def get_all_components(*, login_user: UserPayload = Depends(UserPayload.get_login_user)):
    # get login user
    return ComponentService.get_all_component(login_user)


@router.post('')
def save_components(*, data: CreateComponentReq, login_user: UserPayload = Depends(UserPayload.get_login_user)):
    from bisheng import __version__
    # get login user
    component = Component(**data.model_dump(),
                          user_id=login_user.user_id,
                          user_name=login_user.user_name,
                          version=__version__)
    return ComponentService.save_component(component)


@router.patch('')
def update_component(*, data: CreateComponentReq, login_user: UserPayload = Depends(UserPayload.get_login_user)):
    from bisheng import __version__
    # get login user
    component = Component(**data.model_dump(),
                          user_id=login_user.user_id,
                          user_name=login_user.user_name,
                          version=__version__)
    return ComponentService.update_component(component)


@router.delete('')
def delete_component(*,
                     name: str = Body(..., embed=True, description='组件名'),
                     login_user: UserPayload = Depends(UserPayload.get_login_user)):
    return ComponentService.delete_component(login_user.user_id, name)


@router.post('/custom_component')
async def custom_component(
        raw_code: CustomComponentCode,
        login_user: UserPayload = Depends(UserPayload.get_login_user),
):
    component = CustomComponent(code=raw_code.code)

    built_frontend_node = build_custom_component_template(component, user_id=str(login_user.user_id))

    built_frontend_node = update_frontend_node_with_template_values(built_frontend_node,
                                                                    raw_code.frontend_node)
    return resp_200(data=built_frontend_node)


@router.post('/custom_component/reload')
async def reload_custom_component(path: str, login_user: UserPayload = Depends(UserPayload.get_login_user)):
    from bisheng.interface.custom.utils import build_custom_component_template

    reader = DirectoryReader('')
    valid, content = reader.process_file(path)
    if not valid:
        raise ValueError(content)

    extractor = CustomComponent(code=content)
    return resp_200(
        data=build_custom_component_template(extractor, user_id=str(login_user.user_id)))


@router.post('/custom_component/update')
async def custom_component_update(
        raw_code: CustomComponentCode,
        login_user: UserPayload = Depends(UserPayload.get_login_user)):
    component = CustomComponent(code=raw_code.code)

    component_node = build_custom_component_template(component,
                                                     user_id=str(login_user.user_id),
                                                     update_field=raw_code.field)
    # Update the field
    return resp_200(data=component_node)

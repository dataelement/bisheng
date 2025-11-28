from fastapi import APIRouter, Depends

from bisheng.common.dependencies.user_deps import get_login_user
from bisheng.common.schemas.api import resp_200
from bisheng.finetune.domain.models.model_deploy import ModelDeployDao
from bisheng.finetune.domain.models.server import Server, ServerCreate, ServerDao
from ...common.errcode.http_error import NotFoundError

# build router
router = APIRouter(prefix='/server', tags=['server'], dependencies=[Depends(get_login_user)])


@router.post('/add')
async def add_server(*, server: ServerCreate):
    db_server = Server.model_validate(server)
    db_server = await ServerDao.insert(db_server)
    return resp_200(db_server)


@router.get('/list_server')
async def list_server():
    rt_server = await ServerDao.find_all_server()
    rt_server = rt_server or []
    return resp_200(rt_server)


@router.delete('/{server_id}', status_code=200)
async def delete_server(*, server_id: int):
    await ServerDao.delete(server_id)
    return resp_200(None)


@router.get('/model/{deploy_id}')
async def get_model_deploy(*, deploy_id: int):
    model_deploy = await ModelDeployDao.find_model(deploy_id)
    if not ModelDeployDao:
        raise NotFoundError()
    return resp_200(data=model_deploy)

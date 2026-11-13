from typing import Annotated

from fastapi import APIRouter, Depends, Query

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.schemas.api import resp_200
from bisheng.variable.domain.schemas import VariableInput
from bisheng.variable.domain.services.variable_service import VariableService

router = APIRouter(prefix="/variable", tags=["variable"], dependencies=[Depends(UserPayload.get_login_user)])
LoginUser = Annotated[UserPayload, Depends(UserPayload.get_login_user)]


@router.post("/", status_code=200)
async def post_variable(variable: VariableInput, login_user: LoginUser):
    return resp_200(await VariableService.save(login_user, variable))


@router.get("/list")
async def get_variables(
    login_user: LoginUser,
    *,
    flow_id: str,
    node_id: str | None = None,
    variable_name: str | None = None,
    version_id: Annotated[int | None, Query(gt=0)] = None,
):
    return resp_200(await VariableService.list(login_user, flow_id, version_id, node_id, variable_name))


@router.delete("/del", status_code=200)
async def del_variables(login_user: LoginUser, *, id: Annotated[int, Query(gt=0)]):
    await VariableService.delete(login_user, id)
    return resp_200()


@router.post("/save_all", status_code=200)
async def save_all_variables(login_user: LoginUser, *, data: list[VariableInput]):
    await VariableService.replace(login_user, data)
    return resp_200()

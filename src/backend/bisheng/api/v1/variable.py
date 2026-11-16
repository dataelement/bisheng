from fastapi import APIRouter, Depends

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.schemas.api import resp_200
from bisheng.database.models.variable_value import Variable, VariableCreate
from bisheng.workflow.application import variables

router = APIRouter(prefix="/variable", tags=["variable"])


@router.post("/", status_code=200)
async def post_variable(variable: Variable, user: UserPayload = Depends(UserPayload.get_login_user)):
    return resp_200(await variables.save_variable(user, variable))


@router.get("/list")
async def get_variables(
    *,
    flow_id: str,
    node_id: str | None = None,
    variable_name: str | None = None,
    version_id: int | None = None,
    user: UserPayload = Depends(UserPayload.get_login_user),
):
    return resp_200(await variables.list_variables(user, flow_id, node_id, variable_name, version_id))


@router.delete("/del", status_code=200)
async def del_variables(*, id: int, user: UserPayload = Depends(UserPayload.get_login_user)):
    await variables.delete_variable(user, id)
    return resp_200()


@router.post("/save_all", status_code=200)
async def save_all_variables(*, data: list[VariableCreate], user: UserPayload = Depends(UserPayload.get_login_user)):
    await variables.replace_variables(user, data)
    return resp_200()

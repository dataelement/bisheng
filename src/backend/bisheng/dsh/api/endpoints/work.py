"""Work consumes existing browser sessions minted by the Desktop host."""

from typing import Literal

from fastapi import APIRouter, Depends, Path, Query, Request
from pydantic import BaseModel, ConfigDict, StrictBool

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.schemas.api import resp_200
from bisheng.dsh.domain.services.work_capabilities import WorkCapabilitiesService
from bisheng.dsh.work_mcp import WorkMcpResponse

router = APIRouter()


class WorkPublicationInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: StrictBool


@router.api_route("/dsh/work/mcp", methods=["GET", "POST", "DELETE"])
async def work_mcp(request: Request, user: UserPayload = Depends(UserPayload.get_login_user)):
    return WorkMcpResponse(request.app.state.work_mcp_runtime, user)


@router.get("/dsh/work/publications")
async def publications(user: UserPayload = Depends(UserPayload.get_tenant_admin_user)):
    service = WorkCapabilitiesService(user)
    return resp_200(
        {kind: sorted(await service.publications.list_enabled(user.tenant_id, kind)) for kind in ("tool", "skill")}
    )


@router.put("/dsh/work/publications/{kind}/{resource_id}")
async def publish(
    kind: Literal["tool", "skill"],
    body: WorkPublicationInput,
    resource_id: int = Path(gt=0),
    user: UserPayload = Depends(UserPayload.get_tenant_admin_user),
):
    return resp_200(await WorkCapabilitiesService(user).publish(kind, resource_id, body.enabled))


@router.get("/dsh/work/skills/{skill_id}/dependencies")
async def skill_dependencies(
    skill_id: int = Path(gt=0),
    version: str = Query(pattern=r"^[a-f0-9]{64}$"),
    user: UserPayload = Depends(UserPayload.get_login_user),
):
    return resp_200(await WorkCapabilitiesService(user).skill_dependencies(skill_id, version))

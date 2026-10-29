"""The enterprise capability center uses the current browser identity."""

from fastapi import APIRouter, Depends, Path
from pydantic import BaseModel, ConfigDict, Field, StrictBool

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.schemas.api import resp_200
from bisheng.dsh.domain.services.capability_catalog import CapabilityCatalogService

router = APIRouter(prefix="/dsh/capabilities")


class TrialInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    arguments: dict = Field(default_factory=dict, max_length=16)


@router.get("")
async def capabilities(user: UserPayload = Depends(UserPayload.get_login_user)):
    return resp_200(await CapabilityCatalogService(user).list())


@router.post("/{tool_id}/trial")
async def trial(body: TrialInput, tool_id: int = Path(gt=0), user: UserPayload = Depends(UserPayload.get_login_user)):
    return resp_200(await CapabilityCatalogService(user).trial(tool_id, body.arguments))


class AvailabilityInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: StrictBool


@router.put("/{tool_id}/availability")
async def set_availability(
    body: AvailabilityInput, tool_id: int = Path(gt=0), user: UserPayload = Depends(UserPayload.get_login_user)
):
    return resp_200(await CapabilityCatalogService(user).set_availability(tool_id, body.enabled))

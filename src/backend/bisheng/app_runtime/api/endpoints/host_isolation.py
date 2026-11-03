"""Disjoint host reporting and manager read identities."""

from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field

from bisheng.app_runtime.api.endpoints.runtime_delivery import RuntimeRoute, role
from bisheng.app_runtime.domain.services.host_isolation_service import HostIsolationService

router = APIRouter(tags=["Host isolation"], route_class=RuntimeRoute)


class Report(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    engine_id: str = Field(min_length=1, max_length=128)
    network_id: str = Field(min_length=1, max_length=128)
    config_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    rule_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    revision: int = Field(gt=0)
    checked_at: str = Field(max_length=40)
    status: Literal["valid", "failed"]
    checks: dict[str, bool]


@router.post("/internal/app-runtime/host-isolation-reports")
async def report(body: Report, identity=Depends(role("host-isolation"))):
    return await HostIsolationService().accept(identity, body.model_dump())


@router.get("/internal/app-runtime/v2/host-isolation")
async def current(identity=Depends(role("manager"))):
    return await HostIsolationService().current(identity)

"""Node-bound control and separately authenticated readonly admission endpoints."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, Path, Query
from pydantic import BaseModel, ConfigDict, Field

from bisheng.app_runtime.api.endpoints.runtime_delivery import RuntimeRoute, role
from bisheng.app_runtime.domain.services.runtime_kubernetes_service import RuntimeKubernetesService
from bisheng.app_runtime.domain.services.runtime_protocol import ProtocolRejected

router = APIRouter(prefix="/internal/app-runtime/v2", tags=["Runtime Kubernetes"], route_class=RuntimeRoute)
_UUID = r"^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$"


def service():
    return RuntimeKubernetesService()


def independent_role(required):
    async def verify(identity=Depends(role(required))):
        if set(identity.roles) != {required}:
            raise ProtocolRejected("independent_service_role_required")
        return identity

    return verify


class StrictInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class ControllerClaim(StrictInput):
    holder_id: str = Field(pattern=r"^[A-Za-z0-9_.-]{1,64}$")
    expected_epoch: int = Field(ge=0)


class ControllerRenew(StrictInput):
    holder_id: str = Field(pattern=r"^[A-Za-z0-9_.-]{1,64}$")
    controller_epoch: int = Field(ge=1)


class ResourceInput(ControllerRenew):
    resource_ref: str = Field(pattern=_UUID)
    operation_id: str = Field(min_length=1, max_length=36)
    cluster_id: str = Field(min_length=1, max_length=64)
    namespace: str = Field(min_length=1, max_length=63)
    purpose: str = Field(pattern=r"^[a-z][a-z-]{0,23}$")
    template: dict


class ResourceObservation(ControllerRenew):
    action: Literal["bind", "stop", "stopped", "cleanup"]
    uid: str | None = Field(default=None, pattern=_UUID)
    node_name: str = Field(default="", max_length=253)
    operation_id: str | None = Field(default=None, min_length=1, max_length=36)
    evidence: dict | None = None


@router.post("/controllers/claim")
async def claim(body: ControllerClaim, identity=Depends(independent_role("manager")), svc=Depends(service)):
    return await svc.claim_controller(identity, **body.model_dump())


@router.post("/controllers/renew")
async def renew(body: ControllerRenew, identity=Depends(independent_role("manager")), svc=Depends(service)):
    return await svc.renew_controller(identity, **body.model_dump())


@router.get("/resources")
async def resources(
    operation_id: str = Query(min_length=1, max_length=36),
    identity=Depends(independent_role("manager")),
    svc=Depends(service),
):
    return await svc.resources(identity, operation_id)


@router.get("/resources/{resource_ref}")
async def resource(
    resource_ref: str = Path(pattern=_UUID),
    identity=Depends(independent_role("manager")),
    svc=Depends(service),
):
    return await svc.resource(identity, resource_ref)


@router.post("/resources")
async def register(body: ResourceInput, identity=Depends(independent_role("manager")), svc=Depends(service)):
    return await svc.register_resource(identity, body.model_dump())


@router.post("/resources/{resource_ref}/observations")
async def observe(
    body: ResourceObservation,
    resource_ref: str = Path(pattern=_UUID),
    identity=Depends(independent_role("manager")),
    svc=Depends(service),
):
    return await svc.observe_resource(identity, resource_ref, body.model_dump(exclude_none=True))


@router.get("/admission/plans/{resource_ref}")
async def admission_plan(
    resource_ref: str = Path(pattern=_UUID),
    identity=Depends(independent_role("admission")),
    svc=Depends(service),
):
    return await svc.admission_plan(identity, resource_ref)

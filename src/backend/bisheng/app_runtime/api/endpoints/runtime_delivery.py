"""Authenticated runtime v2 endpoints; no Engine access or ORM queries here."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.routing import APIRoute
from loguru import logger
from pydantic import BaseModel, ConfigDict, Field

from bisheng.app_runtime.domain.repositories.runtime_delivery_repository import RuntimeConflict
from bisheng.app_runtime.domain.schemas.runtime_delivery import ExecutionFactInput, StageAuthorizationInput, UploadInput
from bisheng.app_runtime.domain.services.runtime_operation_service import RuntimeOperationService, consume_runtime_nonce
from bisheng.app_runtime.domain.services.runtime_protocol import ProtocolRejected, authenticate
from bisheng.common.services.config_service import settings


class RuntimeRoute(APIRoute):
    def get_route_handler(self):
        original = super().get_route_handler()

        async def handler(request):
            try:
                return await original(request)
            except RequestValidationError:
                return JSONResponse(status_code=422, content={"error": {"reason": "invalid_request"}})
            except ProtocolRejected as exc:
                return JSONResponse(status_code=403, content={"error": {"reason": str(exc)}})
            except RuntimeConflict as exc:
                return JSONResponse(
                    status_code=404 if str(exc).endswith("not_found") else 409, content={"error": {"reason": str(exc)}}
                )
            except Exception as exc:
                # Global SPA error handlers may serialize exception details.
                logger.warning("runtime control unavailable ({})", type(exc).__name__)
                return JSONResponse(status_code=503, content={"error": {"reason": "runtime_control_unavailable"}})

        return handler


router = APIRouter(prefix="/internal/app-runtime/v2", tags=["App Runtime v2"], route_class=RuntimeRoute)


def service():
    return RuntimeOperationService()


def role(required):
    async def verify(request: Request):
        if not settings.app_runtime.enabled:
            raise ProtocolRejected("runtime_disabled")
        body = await request.body()
        if len(body) > 16 * 1024 * 1024 + 65536:
            raise ProtocolRejected("request_size_limit")
        return await authenticate(
            request.method,
            str(request.url),
            body,
            request.headers,
            settings.app_runtime.runtime_service_keys,
            consume_runtime_nonce,
            required_role=required,
        )

    return verify


class Heartbeat(BaseModel):
    model_config = ConfigDict(extra="forbid")
    engine_id: str = Field(min_length=1, max_length=128)
    platform: str = Field(pattern=r"^linux/(amd64|arm64)$")
    memory_budget_mb: int = Field(ge=1)
    cpu_budget_millicores: int = Field(ge=1)
    executor_kind: Literal["docker", "kubernetes"] = "docker"
    capabilities: dict = Field(default_factory=dict)
    probe_report: dict = Field(default_factory=dict)


@router.post("/nodes/heartbeat")
async def heartbeat(body: Heartbeat, identity=Depends(role("manager")), svc=Depends(service)):
    return await svc.heartbeat(identity, body)


@router.get("/nodes/plan")
async def node_plan(identity=Depends(role("manager")), svc=Depends(service)):
    return await svc.node_plan(identity)


@router.get("/operations/{operation_id}")
async def operation(operation_id: str, identity=Depends(role("manager")), svc=Depends(service)):
    async with svc.scope(identity, operation_id=operation_id) as op:
        return await svc.describe(op)


@router.post("/operations/{operation_id}/authorize-step")
async def authorize_step(
    operation_id: str, body: StageAuthorizationInput, identity=Depends(role("manager")), svc=Depends(service)
):
    async with svc.scope(identity, operation_id=operation_id) as op:
        return await svc.authorize_step(op, identity, body)


class Claim(BaseModel):
    command_nonce: str | None = Field(default=None, pattern=r"^[0-9a-f]{32}$")


@router.post("/operations/{operation_id}/claim")
async def claim(operation_id: str, body: Claim, identity=Depends(role("manager")), svc=Depends(service)):
    async with svc.scope(identity, operation_id=operation_id) as op:
        return await svc.claim(op, identity, command_nonce=body.command_nonce)


@router.post("/operations/{operation_id}/facts")
async def fact(operation_id: str, body: ExecutionFactInput, identity=Depends(role("manager")), svc=Depends(service)):
    async with svc.scope(identity, operation_id=operation_id) as op:
        return await svc.fact(op, identity, body)


@router.post("/transfers")
async def upload(body: UploadInput, identity=Depends(role("manager")), svc=Depends(service)):
    async with svc.scope(identity, operation_id=body.operation_id):
        return await svc.artifacts.create_upload(**body.model_dump(), node_id=identity.node_id)


class Download(BaseModel):
    operation_id: str
    artifact_id: str


@router.post("/downloads")
async def download(body: Download, identity=Depends(role("manager")), svc=Depends(service)):
    async with svc.scope(identity, operation_id=body.operation_id):
        return await svc.artifacts.create_download(body.operation_id, body.artifact_id, node_id=identity.node_id)


@router.put("/transfers/{transfer_id}/content")
async def append(
    transfer_id: str, request: Request, offset: int = 0, identity=Depends(role("manager")), svc=Depends(service)
):
    async with svc.scope(identity, transfer_id=transfer_id):
        return await svc.artifacts.append(
            transfer_id,
            request.headers.get("x-runtime-transfer", ""),
            offset,
            request.stream(),
            node_id=identity.node_id,
        )


@router.post("/transfers/{transfer_id}/finalize")
async def finalize(transfer_id: str, request: Request, identity=Depends(role("manager")), svc=Depends(service)):
    async with svc.scope(identity, transfer_id=transfer_id):
        return await svc.artifacts.finalize(
            transfer_id, request.headers.get("x-runtime-transfer", ""), node_id=identity.node_id
        )


@router.get("/transfers/{transfer_id}/content")
async def content(transfer_id: str, request: Request, identity=Depends(role("manager")), svc=Depends(service)):
    ticket = request.headers.get("x-runtime-transfer", "")
    async with svc.scope(identity, transfer_id=transfer_id):
        await svc.artifacts.authorized_transfer(transfer_id, ticket, node_id=identity.node_id, action="download")

        async def stream():
            async with svc.scope(identity, transfer_id=transfer_id):
                async for chunk in svc.artifacts.content(transfer_id, ticket, node_id=identity.node_id):
                    yield chunk

        return StreamingResponse(stream(), media_type="application/octet-stream")


@router.get("/routes/apps/{app_id}")
async def route(app_id: str, _=Depends(role("entry")), svc=Depends(service)):
    return await svc.route(f"app:{app_id}")


@router.get("/routes/previews/{session_id}")
async def preview_route(session_id: str, _=Depends(role("entry")), svc=Depends(service)):
    return await svc.route(f"preview:{session_id}")


@router.get("/egress-policies")
async def policies(identity=Depends(role("egress")), svc=Depends(service)):
    return await svc.policies(identity)


class NonceInput(BaseModel):
    key: str = Field(pattern=r"^runtime:v2:nonce:[A-Za-z0-9._-]{1,64}:[0-9a-f]{32}$")
    ttl: int = Field(ge=120, le=120)


@router.post("/nonces")
async def nonce(body: NonceInput, identity=Depends(role("manager"))):
    if not identity.node_id:
        raise ProtocolRejected("node_identity_required")
    accepted = await consume_runtime_nonce("runtime:v2:received:" + identity.node_id + ":" + body.key, body.ttl)
    return {"accepted": bool(accepted)}


@router.get("/transfers/{transfer_id}")
async def transfer_status(transfer_id: str, request: Request, identity=Depends(role("manager")), svc=Depends(service)):
    async with svc.scope(identity, transfer_id=transfer_id) as record:
        transfer, artifact = await svc.artifacts.authorized_transfer(
            transfer_id, request.headers.get("x-runtime-transfer", ""), node_id=identity.node_id, action=record.action
        )
        return {
            "transfer_id": transfer.id,
            "offset": transfer.offset,
            "state": transfer.state,
            "artifact_id": artifact.id,
            "artifact_state": artifact.state,
        }


class DependencyInput(BaseModel):
    operation_id: str
    input_key: str = Field(pattern=r"^[0-9a-f]{64}$")
    artifact_id: str | None = None
    verified: bool = False


@router.post("/dependency-plans")
async def dependencies(body: DependencyInput, identity=Depends(role("manager")), svc=Depends(service)):
    from bisheng.app_runtime.domain.services.runtime_profile_service import RuntimeDependencyService

    async with svc.scope(identity, operation_id=body.operation_id) as op:
        plans = RuntimeDependencyService(svc.repo)
        if body.artifact_id:
            return await plans.confirm(op, body.input_key, body.artifact_id, verified=body.verified)
        return await plans.resolve(op, body.input_key)


class EgressBindingInput(BaseModel):
    operation_id: str
    phase: str
    package_sources: list[str] = Field(default_factory=list, max_length=8)


@router.post("/egress-bindings")
async def egress_binding(body: EgressBindingInput, identity=Depends(role("manager")), svc=Depends(service)):
    from bisheng.app_runtime.domain.services.runtime_egress_service import RuntimeEgressService

    async with svc.scope(identity, operation_id=body.operation_id) as op:
        await svc.artifacts.operation(op.id, identity.node_id)
        if body.phase == "build" and op.kind != "prepare":
            raise RuntimeConflict("egress_phase_invalid")
        return await RuntimeEgressService(svc.repo).issue(
            op,
            phase=body.phase,
            declared=op.payload.get("egress_domains", []),
            platform_base=settings.app_runtime.runtime_platform_base_url,
            package_sources=body.package_sources,
        )


@router.get("/apps/{app_id}/execution")
async def execution(app_id: str, identity=Depends(role("manager")), svc=Depends(service)):
    return await svc.application(identity, app_id)


class ObservationInput(BaseModel):
    app_id: str
    operation_id: str
    exec_ref: str
    generation: int = Field(ge=1)
    route_epoch: int = Field(ge=1)
    running: bool
    ready: bool


@router.post("/observations")
async def observation(body: ObservationInput, identity=Depends(role("manager")), svc=Depends(service)):
    return await svc.observation(identity, body)

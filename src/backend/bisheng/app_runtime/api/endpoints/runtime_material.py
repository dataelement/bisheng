"""Independent workload material transport and manager-only public-key control.

The fixed material root is mounted directly by main; it has no browser JWT or
service-HMAC authority. Storage access remains inside backend Domain Services.
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.routing import APIRoute
from loguru import logger
from pydantic import Field

from bisheng.app_runtime.api.endpoints.runtime_delivery import RuntimeRoute
from bisheng.app_runtime.api.endpoints.runtime_kubernetes import StrictInput, independent_role
from bisheng.app_runtime.domain.services import runtime_material_protocol as wire
from bisheng.app_runtime.domain.services.runtime_material_service import RuntimeMaterialService
from bisheng.app_runtime.domain.services.runtime_material_transfer_service import RuntimeMaterialTransferService
from bisheng.common.services.config_service import settings

_UUID = r"^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$"


def _response(reason, status):
    return JSONResponse(status_code=status, content={"error": {"reason": reason}})


class MaterialRoute(APIRoute):
    def get_route_handler(self):
        original = super().get_route_handler()

        async def handle(request):
            try:
                return await original(request)
            except wire.MaterialProtocolError as exc:
                return _response(str(exc), exc.status_code)
            except RequestValidationError:
                return _response("material_request_invalid", 400)
            except Exception as exc:
                # Platform global business handlers may serialize exception text.
                logger.warning("material request unavailable ({})", type(exc).__name__)
                return _response("material_service_unavailable", 503)

        return handle


class MaterialControlRoute(RuntimeRoute):
    def get_route_handler(self):
        original = super().get_route_handler()

        async def handle(request):
            try:
                return await original(request)
            except Exception as exc:
                logger.warning("material control unavailable ({})", type(exc).__name__)
                return _response("material_control_unavailable", 503)

        return handle


router = APIRouter()
workload = APIRouter(prefix=wire.PREFIX, tags=["Runtime material"], route_class=MaterialRoute)
control = APIRouter(
    prefix="/api/v1/internal/app-runtime/v2/material-delegations",
    tags=["Runtime material control"],
    route_class=MaterialControlRoute,
)


def authority():
    return RuntimeMaterialService()


def transfers(svc=Depends(authority)):
    return RuntimeMaterialTransferService(svc)


def runtime_enabled():
    return settings.app_runtime.enabled


class DelegationInput(StrictInput):
    operation_id: str = Field(min_length=1, max_length=36)
    exec_ref: str = Field(pattern=_UUID)
    key_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")
    public_key: str = Field(pattern=r"^[a-f0-9]{64}$")


class BindingInput(StrictInput):
    pod_uid: str = Field(pattern=_UUID)


@control.post("")
async def create_delegation(
    body: DelegationInput, identity=Depends(independent_role("manager")), svc=Depends(authority)
):
    return await svc.create_delegation(identity, body.model_dump())


@control.post("/{delegation_id}/bind")
async def bind_delegation(
    delegation_id: str, body: BindingInput, identity=Depends(independent_role("manager")), svc=Depends(authority)
):
    return await svc.bind_delegation(identity, delegation_id, pod_uid=body.pod_uid)


async def authenticated(request: Request, svc=Depends(authority), transport=Depends(transfers)):
    if not runtime_enabled():
        raise wire.MaterialProtocolError("runtime_disabled", 403)
    limit = wire.CHUNK_LIMIT if request.method == "PUT" else wire.CONTROL_LIMIT
    body = bytearray()
    try:
        async with asyncio.timeout(60):
            async for chunk in request.stream():
                if len(body) + len(chunk) > limit:
                    raise wire.MaterialProtocolError("material_body_limit", 413)
                body.extend(chunk)
    except TimeoutError:
        raise wire.MaterialProtocolError("material_request_expired", 401) from None
    try:
        target = request.scope["raw_path"].decode("ascii")
        query = request.scope.get("query_string", b"").decode("ascii")
    except UnicodeError:
        raise wire.MaterialProtocolError("material_target_invalid", 400) from None
    if query:
        target += "?" + query
    raw = bytes(body)
    proof, scope = await svc.authenticate_request(
        request.method,
        target,
        raw,
        request.headers,
        authorize_transfer=lambda proof, scope: transport.authorize(proof, scope, request.method, target, raw),
    )
    return proof, scope, raw


@workload.post("/exchange")
async def exchange(context=Depends(authenticated), svc=Depends(transfers)):
    _, scope, _ = context
    return await svc.exchange(scope)


@workload.get("/transfers/{transfer_id}")
async def status(transfer_id: str, context=Depends(authenticated), svc=Depends(transfers)):
    proof, scope, _ = context
    return await svc.status(scope, proof.ticket, transfer_id)


@workload.get("/transfers/{transfer_id}/content")
async def content(transfer_id: str, request: Request, context=Depends(authenticated), svc=Depends(transfers)):
    proof, scope, _ = context
    status_code, headers, stream = await svc.content(
        scope, proof.ticket, transfer_id, int(request.query_params["offset"]), int(request.query_params["length"])
    )

    async def guarded_stream():
        try:
            async for chunk in stream:
                yield chunk
        except Exception as exc:
            # Headers may already be sent: terminate, so length/digest checks fail.
            logger.warning("material content interrupted ({})", type(exc).__name__)
            raise

    return StreamingResponse(
        guarded_stream(), status_code=status_code, headers=headers, media_type="application/octet-stream"
    )


@workload.put("/transfers/{transfer_id}/content")
async def append(transfer_id: str, request: Request, context=Depends(authenticated), svc=Depends(transfers)):
    proof, scope, raw = context
    return await svc.append(scope, proof.ticket, transfer_id, int(request.query_params["offset"]), raw)


@workload.post("/transfers/{transfer_id}/finalize")
async def finalize(transfer_id: str, context=Depends(authenticated), svc=Depends(transfers)):
    proof, scope, raw = context
    declaration = wire.parse_control(raw, allowed={"sha256", "size_bytes"}, required={"sha256", "size_bytes"})
    return await svc.finalize(scope, proof.ticket, transfer_id, declaration)


@workload.api_route("/{invalid:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"])
async def noncanonical_path(invalid: str):
    raise wire.MaterialProtocolError("material_path_or_method_invalid", 400)


router.include_router(control)
router.include_router(workload)

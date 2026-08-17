"""Intent RPC — the write side (design §4.2 ①).

Every route is HMAC protected and *declares desired state*: "this app should be
running version V of image I at tier T". The manager reconciles; the backend
never says ``docker run`` (D1).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from runtime_manager.admission import AdmissionService, Tier
from runtime_manager.api.schemas import (
    AdmissionRequest,
    AdmissionResponse,
    BuildRequest,
    DeployRequest,
    DestroyRequest,
    ProbeRequest,
    StopRequest,
)
from runtime_manager.auth import verify_hmac
from runtime_manager.builder import BuildService
from runtime_manager.config import get_config
from runtime_manager.errors import InvalidRequestError
from runtime_manager.lifecycle import LifecycleService
from runtime_manager.probe import ProbeService

router = APIRouter(prefix="/v1", tags=["intents"], dependencies=[Depends(verify_hmac)])


@router.post("/admission", response_model=AdmissionResponse)
async def admission(request: AdmissionRequest) -> AdmissionResponse:
    """AC-19 — can this host take one more instance (or one more build)?"""
    config = get_config()
    tier = Tier(cpu=request.tier.cpu, mem_mb=request.tier.mem) if request.tier else None
    result = AdmissionService(config).evaluate(tier, purpose=request.purpose)
    return AdmissionResponse(**result.to_response())


@router.post("/intents/build")
async def build(request: BuildRequest) -> dict:
    """AC-15 — build an image from a code snapshot using the platform's template.

    Returns a handle immediately: a real build takes minutes and the backend
    polls ``GET /v1/builds/{build_id}``. An unsupported ``runtime`` is rejected
    synchronously (400 + the supported set) rather than becoming a build that
    has to be polled to discover it never had a chance.
    """
    record = BuildService(get_config()).submit(request)
    return {"build_id": record.build_id, "status": record.status}


@router.get("/builds/{build_id}")
async def build_status(build_id: str) -> dict:
    """Poll a build: ``{status, stage, message, tail, image_ref}`` (AC-15)."""
    return BuildService(get_config()).get(build_id).to_response()


@router.post("/intents/deploy")
async def deploy(request: DeployRequest) -> dict:
    """Declare the desired running state of one app.

    Capacity first, readiness gate before the switch, old instance retired after
    a grace window (D4 / AC-21). A refusal (capacity) or a failed readiness gate
    leaves whatever was already serving exactly as it was.
    """
    return LifecycleService(get_config()).deploy(request)


@router.post("/intents/stop")
async def stop(request: StopRequest) -> dict:
    """AC-41 — reclaim the execution body; the app's data is untouched."""
    return LifecycleService(get_config()).stop(request.app_id)


@router.post("/intents/destroy")
async def destroy(request: DestroyRequest) -> dict:
    """AC-40 — only ``purge_volume=true`` (the owner's explicit delete) removes data."""
    return LifecycleService(get_config()).destroy(request.app_id, purge_volume=request.purge_volume)


@router.post("/intents/probe")
async def probe(request: ProbeRequest) -> dict:
    """AC-18 — readiness of a live instance, or of a bare image (F055 pre-flight)."""
    service = ProbeService(get_config())
    if request.app_id:
        outcome = service.probe_app(request.app_id, timeout=request.timeout)
    elif request.image_ref:
        outcome = service.probe_image(
            image_ref=request.image_ref,
            env=request.env,
            port=request.port,
            health_path=request.health.path,
            timeout=request.timeout,
        )
    else:
        raise InvalidRequestError("probe needs either app_id or image_ref")
    return {"ready": outcome.ready, "reason": outcome.reason}

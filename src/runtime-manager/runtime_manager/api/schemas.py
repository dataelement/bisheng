"""Wire shapes for the intent RPC (design §4.2 ①).

Every field name here is form agnostic on purpose (INV-33): no ``container``,
no ``compose``, no ``image_pull_policy``. When F059 adds the k8s backend the
backend-side client must not change, so anything compose-specific stays inside
the manager (``exec_ref`` on the platform side is the single, inward-facing
exception).
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class TierIn(BaseModel):
    """Resource tier — ``mem`` in MiB, ``cpu`` in vCPU (D11 / ``DEFAULT_TIERS``)."""

    cpu: float = Field(gt=0)
    mem: int = Field(gt=0)


class HealthIn(BaseModel):
    path: str = "/"
    interval: int = 10
    timeout: int = 3
    retries: int = 3
    start_period: int | None = None


class AdmissionRequest(BaseModel):
    tier: TierIn | None = None
    purpose: Literal["run", "build"] = "run"


class BuildRequest(BaseModel):
    app_id: str
    version_id: str
    runtime: str
    #: Object key of the code snapshot, for logging and traceability.
    code_object_key: str
    #: Pre-signed download URL for that object. The manager holds no platform
    #: credentials (D3) — the backend mints this and it expires on its own.
    code_url: str
    slug: str = ""
    version_no: int = 1
    port: int = 8080
    build_args: dict[str, str] = Field(default_factory=dict)


class DeployRequest(BaseModel):
    """Desired state for one app. Note what is *absent*: replicas, concurrency.

    AC-24 (single instance per app) is expressed by the absence of an input, not
    by a validation rule — there is no field to set, so there is no code path
    that can grow one by accident.
    """

    app_id: str
    slug: str
    version_id: str
    version_no: int = 1
    image_ref: str
    tier: TierIn
    port: int = 8080
    env: dict[str, str] = Field(default_factory=dict)
    health: HealthIn = Field(default_factory=HealthIn)
    platform_api_base: str = ""
    base_path: str = ""


class StopRequest(BaseModel):
    app_id: str


class DestroyRequest(BaseModel):
    app_id: str
    purge_volume: bool = False


class ProbeRequest(BaseModel):
    """Either ``app_id`` (probe the live instance) or a standalone image spec.

    The standalone form is what makes F055's pre-flight and the approval-time
    preview instance reuse this exact code path instead of growing a second,
    subtly different readiness definition.
    """

    app_id: str | None = None
    image_ref: str | None = None
    env: dict[str, str] = Field(default_factory=dict)
    port: int = 8080
    health: HealthIn = Field(default_factory=HealthIn)
    timeout: int | None = None


class AdmissionResponse(BaseModel):
    admitted: bool
    reason: str
    message: str = ""
    stage: str | None = None
    required_mb: int = 0
    required_cpu: float = 0.0
    snapshot: dict[str, Any] = Field(default_factory=dict)

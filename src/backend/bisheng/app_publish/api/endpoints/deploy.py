"""``/api/v2/apps/**`` — what ``bisheng deploy`` and ``bisheng logs`` talk to (design D2 / §4.2 ①).

Four endpoints on the **single** ``/api/v2`` pipeline (F053 design K14): the
aggregate ``router_rpc`` carries ``Depends(verify_open_api_access)`` once, and
every endpoint here declares what it needs through the ``@open_api_scope``
marker. An endpoint without the marker is refused before its body runs
(``OpenApiEndpointUnregisteredError``) — the fail-closed default is the
router's, not this file's, which is why there is no per-endpoint credential
dependency any more (migration plan M8).

Three conventions the rest of the file assumes:

* **Order of the guards is fixed by FastAPI, not by argument order.** Router-
  level dependencies are inserted *ahead of* an endpoint's parameter
  dependencies in its ``Dependant`` (``APIRoute.__init__`` walks
  ``self.dependencies[::-1]`` and ``insert(0, …)``), so credential → scope →
  identity mode all resolve before ``require_app_runtime_enabled`` is even
  called. Answering 16207 before authenticating would let an anonymous caller
  probe how a deployment is built; checking ownership before 16207 is
  impossible, because on a deployment without the app factory there are no
  applications to own. ``test_deploy_api`` pins the order on the mounted app.
* **The receive leg does no RPC.** It answers in milliseconds — size gate,
  unpack, manifest, the two submission gates, one row — and hands the minutes
  (build, probe, scan, approval) to a Celery task the CLI polls for. A single
  call to an unreachable runtime-manager here would turn "you forgot ``port``"
  into a request hanging on a socket timeout.
* **The upload never enters memory.** It is spooled to a temp file and handed to
  MinIO as a path; ``await file.read()`` on a 50 MB package would multiply by
  every concurrent publish.

Ownership is judged on ``principal.resource_owner_user_id`` — the natural person
the key creates resources for (伴生 PRD §4.5 定义 6) — and **not** ``actor_id``,
which is the service account itself and owns nothing a human would recognise.
A principal without a resource owner is refused (M9), never treated as owner 0;
see ``publish_pipeline_service.resource_owner_of``.

``modes=("S",)`` on every marker is INV-31: the three local-dev-toolkit scopes
are mode-S only. A delegated call (``X-On-Behalf-Of``) is refused by the
pipeline with 26006 before the endpoint body runs.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile

from bisheng.app_publish.domain.services import package_service
from bisheng.app_publish.domain.services.publish_pipeline_service import (
    PublishPipelineService,
    resource_owner_of,
)
from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.app_publish import AppPublishRuntimeLayerDisabledError
from bisheng.common.errcode.open_api import OpenApiEndpointUnregisteredError
from bisheng.common.schemas.api import UnifiedResponseModel, resp_200
from bisheng.common.services.config_service import settings
from bisheng.open_api.domain.context import OpenApiPrincipal, get_current_open_api_principal
from bisheng.open_api.domain.scopes import open_api_scope

router = APIRouter(prefix="/apps", tags=["HostedAppPublish"])

#: The one scope every endpoint here needs. ``open_api_scope`` validates the
#: name against the registry when the decorator runs, i.e. at import — a typo
#: fails at startup rather than degrading into "this endpoint requires no
#: scope at all". ``requires_open_platform=True`` in the registry keeps a key
#: issued without the open platform enabled from ever carrying it.
_SCOPE = "app:manage"

#: INV-31 — mode S only. Not the decorator's default on purpose: the default
#: admits mode D, and admitting it here would let a delegating key publish in
#: somebody else's name.
_MODES: tuple[str, ...] = ("S",)


async def require_app_runtime_enabled() -> None:
    """16207 — this deployment does not run the app factory.

    Runs **after** the router-level credential pipeline on every endpoint (see
    the module docstring for why that ordering is FastAPI's, not ours): an
    unauthenticated caller must not be able to fingerprint the deployment
    shape. Without this gate a ``deploy`` against a plain installation walks
    all the way to an orchestrator RPC and dies on a timeout, which reads as
    "the platform is broken" rather than "this feature is not installed here".
    """
    if not settings.app_runtime.enabled:
        raise AppPublishRuntimeLayerDisabledError(
            msg="本环境未启用应用工场运行时层",
            details={"reason": "runtime_layer_disabled"},
            hints=["请联系管理员在部署配置中开启 app_runtime 后重试"],
        )


def _principal() -> OpenApiPrincipal:
    """The validated open-API principal ``verify_open_api_access`` installed for this request.

    Read from the ContextVar the router dependency seeded — the same thing
    beta2's ``open_endpoints`` do — rather than resolved here: K14 forbids an
    endpoint body from parsing identity on its own. ``None`` means this router
    was mounted somewhere without the pipeline; that is refused with the same
    error the pipeline itself raises for an unmarked endpoint, because an
    endpoint reachable without the pipeline is exactly that.
    """
    principal = get_current_open_api_principal()
    if principal is None:
        raise OpenApiEndpointUnregisteredError()
    return principal


@router.get(
    "/deploy-limits",
    response_model=UnifiedResponseModel[dict],
    summary="Package limits of this deployment",
)
@open_api_scope(_SCOPE, modes=_MODES)
async def deploy_limits(
    _enabled: None = Depends(require_app_runtime_enabled),
):
    """What the CLI checks a package against **before** uploading it (F053 AC-32).

    The limits are deployment configuration rather than a constant precisely so
    this endpoint can exist: a CLI that hardcoded 50 MiB would be a second copy
    of a contract that only the server can know. A CLI that cannot reach this
    endpoint uploads anyway and gets 16201 — a soft check must never be able to
    block a publish.
    """
    return resp_200(data=package_service.deploy_limits())


@router.post("/deploy", response_model=UnifiedResponseModel[dict], summary="Submit an application package")
@open_api_scope(_SCOPE, modes=_MODES)
async def deploy(
    package: UploadFile = File(..., description="tar.gz built by `bisheng deploy`"),
    app_id: str | None = Form(default=None, description="Omit on a first publish; required for an iteration"),
    confirm_schema_change: bool = Form(default=False),
    _enabled: None = Depends(require_app_runtime_enabled),
):
    """Receive one package and start the pipeline (AC-01).

    Returns as soon as the fast checks pass; everything slow runs on a worker
    and is observed through ``GET /deployments/{id}``.

    ``confirm_schema_change`` answers the ``precheck_schema`` gate (AC-09): an
    iteration that drops or modifies a column of the online version's declared
    tables is refused with 16229 unless it is ``true``; the answer is recorded
    on the deployment and the worker never asks a second time.
    """
    spooled = await package_service.spool_upload(package)
    try:
        result = await PublishPipelineService.accept(
            package_path=spooled,
            principal=_principal(),
            app_id=app_id or None,
            confirm_schema_change=confirm_schema_change,
        )
    finally:
        spooled.unlink(missing_ok=True)
    return resp_200(
        data={
            "deployment_id": result.deployment_id,
            "app_id": result.app_id,
            "version_id": result.version_id,
        }
    )


@router.get(
    "/deployments/{deployment_id}",
    response_model=UnifiedResponseModel[dict],
    summary="Poll one publish attempt",
)
@open_api_scope(_SCOPE, modes=_MODES)
async def get_deployment(
    deployment_id: str,
    _enabled: None = Depends(require_app_runtime_enabled),
):
    """The CLI's polling payload: stage, status, the failure five-tuple, the approval.

    Declared before ``/{app_id}/logs`` because Starlette matches in declaration
    order and an application whose id happened to be "deployments" would
    otherwise shadow this route.
    """
    return resp_200(data=await PublishPipelineService.get_deployment_status(deployment_id, principal=_principal()))


@router.get("/{app_id}/logs", response_model=UnifiedResponseModel[dict], summary="Recent application output")
@open_api_scope(_SCOPE, modes=_MODES)
async def get_logs(
    app_id: str,
    tail: int | None = Query(default=None, ge=1, le=5000),
    since: str | None = Query(default=None, description="epoch seconds, or a window like 30m / 2h / 7d"),
    keyword: str | None = Query(default=None),
    _enabled: None = Depends(require_app_runtime_enabled),
):
    """``bisheng logs`` (F053).

    Forwarded to the **same** service method the detail page's log tab uses, with
    ``entry="cli"`` — which narrows it to the credential's resource owner. A
    tenant administrator's key must not read every application's logs in the
    tenant: that would widen the open API past what the key holder was granted.
    """
    from bisheng.app_publish.domain.services.publish_status_service import PublishStatusService
    from bisheng.app_runtime.domain.services.app_query_service import LOG_ENTRY_CLI, AppQueryService

    principal = _principal()
    # The owner is asked for strictly (M9): the old ``getattr(..., 0) or 0``
    # spelling would have turned an ownerless key into user 0 and let the
    # owner-only entry compare against nobody.
    actor = UserPayload(
        user_id=resource_owner_of(principal),
        user_name="",
        user_role=[],
        tenant_id=principal.tenant_id,
    )
    payload = await AppQueryService.get_logs(
        app_id, actor=actor, tail=tail, since=since, keyword=keyword, entry=LOG_ENTRY_CLI
    )
    # F053 T034 write-back 2. An empty ``lines`` has two completely different
    # causes and the log text alone cannot tell them apart: the application is
    # running and simply quiet, or it has no running instance at all (draft,
    # parked, stopped). Without these two fields the CLI can only print "no
    # logs", which reads as "the log query is broken" and sends the owner off
    # to check the wrong thing. Both are read from the same single sources the
    # publish face uses — no second derivation.
    payload.update(await PublishStatusService.runtime_hint(app_id))
    return resp_200(data=payload)

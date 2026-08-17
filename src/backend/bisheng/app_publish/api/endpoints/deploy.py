"""``/api/v2/apps/**`` — what ``bisheng deploy`` and ``bisheng logs`` talk to (design D2 / §4.2 ①).

Four endpoints, each carrying its **own** ``app:manage`` credential dependency
rather than inheriting a router-level one. That is the usage F049's
``open_api_subject`` factory was built for, and it keeps this router independent
of when the shared ``/api/v2`` router gets its dependency lifted.

Three conventions the rest of the file assumes:

* **Order of the guards is fixed**: credential and scope first, "is the runtime
  layer even installed here" second, ownership last. Answering 16207 before
  authenticating would let an anonymous caller probe how a deployment is built;
  checking ownership before 16207 is impossible, because on a deployment
  without the app factory there are no applications to own.
* **The receive leg does no RPC.** It answers in milliseconds — size gate,
  unpack, manifest, the two submission gates, one row — and hands the minutes
  (build, probe, scan, approval) to a Celery task the CLI polls for. A single
  call to an unreachable runtime-manager here would turn "you forgot ``port``"
  into a request hanging on a socket timeout.
* **The upload never enters memory.** It is spooled to a temp file and handed to
  MinIO as a path; ``await file.read()`` on a 50 MB package would multiply by
  every concurrent publish.

Ownership is judged on ``principal.resource_owner_user_id`` — the natural person
the key creates resources for — and **not** ``subject_user_id``, which is the
service account itself and owns nothing a human would recognise.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from starlette.requests import HTTPConnection

from bisheng.app_publish.domain.services import package_service
from bisheng.app_publish.domain.services.publish_pipeline_service import PublishPipelineService
from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.app_publish import AppPublishRuntimeLayerDisabledError
from bisheng.common.schemas.api import UnifiedResponseModel, resp_200
from bisheng.common.services.config_service import settings
from bisheng.open_api.domain.context import get_current_open_api_principal
from bisheng.open_api.domain.scopes import is_known_scope

router = APIRouter(prefix="/apps", tags=["HostedAppPublish"])

#: The one scope every endpoint here needs. It is already registered with
#: ``requires_open_platform=True``, so a key issued without the open platform
#: enabled cannot carry it.
_SCOPE = "app:manage"

# Validated at import, exactly as ``open_api_subject`` does it: a typo in a
# scope name must fail loudly at startup rather than degrade into "this
# endpoint requires no scope at all".
if not is_known_scope(_SCOPE):
    raise ValueError(f"unknown open API scope {_SCOPE!r}; register it in OPEN_API_SCOPES first")


async def app_manage_subject(conn: HTTPConnection) -> UserPayload:
    """Authenticate the ``Bearer bs-sak-…`` credential and require ``app:manage``.

    A thin wrapper over F049's ``open_api_subject`` factory — the usage its
    docstring reserves for routers F053 / F055 add outside the shared
    ``/api/v2`` router. **The import is deferred into the call** because
    arch-guard RULE-5 forbids one module's ``api/`` layer from importing
    another's at module scope; the scope-name check that factory performs at
    construction time is reproduced above, so nothing is lost by deferring.
    """
    from bisheng.open_api.api.dependencies import open_api_subject

    return await open_api_subject(_SCOPE)(conn)


async def require_app_runtime_enabled() -> None:
    """16207 — this deployment does not run the app factory.

    Declared **after** the credential dependency on every endpoint: an
    unauthenticated caller must not be able to fingerprint the deployment shape.
    Without this gate a ``deploy`` against a plain installation walks all the
    way to an orchestrator RPC and dies on a timeout, which reads as "the
    platform is broken" rather than "this feature is not installed here".
    """
    if not settings.app_runtime.enabled:
        raise AppPublishRuntimeLayerDisabledError(
            msg="本环境未启用应用工场运行时层",
            details={"reason": "runtime_layer_disabled"},
            hints=["请联系管理员在部署配置中开启 app_runtime 后重试"],
        )


def _principal():
    """The validated open-API principal of this request.

    Read from the ContextVar the credential dependency seeded rather than
    threaded through as a parameter: FastAPI's dependency returns a
    ``UserPayload``, and the ownership rule needs ``resource_owner_user_id``,
    which lives on the principal.
    """
    return get_current_open_api_principal()


@router.get(
    "/deploy-limits",
    response_model=UnifiedResponseModel[dict],
    summary="Package limits of this deployment",
)
async def deploy_limits(
    _subject: UserPayload = Depends(app_manage_subject),
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
async def deploy(
    package: UploadFile = File(..., description="tar.gz built by `bisheng deploy`"),
    app_id: str | None = Form(default=None, description="Omit on a first publish; required for an iteration"),
    confirm_schema_change: bool = Form(default=False),
    _subject: UserPayload = Depends(app_manage_subject),
    _enabled: None = Depends(require_app_runtime_enabled),
):
    """Receive one package and start the pipeline (AC-01).

    Returns as soon as the fast checks pass; everything slow runs on a worker
    and is observed through ``GET /deployments/{id}``.

    ``confirm_schema_change`` is accepted and recorded but not acted on this
    release — the flag exists now so the CLI does not have to change its
    command surface again when structural evolution ships.
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
async def get_deployment(
    deployment_id: str,
    _subject: UserPayload = Depends(app_manage_subject),
    _enabled: None = Depends(require_app_runtime_enabled),
):
    """The CLI's polling payload: stage, status, the failure five-tuple, the approval.

    Declared before ``/{app_id}/logs`` because Starlette matches in declaration
    order and an application whose id happened to be "deployments" would
    otherwise shadow this route.
    """
    return resp_200(data=await PublishPipelineService.get_deployment_status(deployment_id, principal=_principal()))


@router.get("/{app_id}/logs", response_model=UnifiedResponseModel[dict], summary="Recent application output")
async def get_logs(
    app_id: str,
    tail: int | None = Query(default=None, ge=1, le=5000),
    since: str | None = Query(default=None, description="epoch seconds, or a window like 30m / 2h / 7d"),
    keyword: str | None = Query(default=None),
    _subject: UserPayload = Depends(app_manage_subject),
    _enabled: None = Depends(require_app_runtime_enabled),
):
    """``bisheng logs`` (F053).

    Forwarded to the **same** service method the detail page's log tab uses, with
    ``entry="cli"`` — which narrows it to the credential's resource owner. A
    tenant administrator's key must not read every application's logs in the
    tenant: that would widen the open API past what the key holder was granted.
    """
    from bisheng.app_runtime.domain.services.app_query_service import LOG_ENTRY_CLI, AppQueryService

    principal = _principal()
    actor = UserPayload(
        user_id=int(getattr(principal, "resource_owner_user_id", 0) or 0),
        user_name="",
        user_role=[],
        tenant_id=_subject.tenant_id,
    )
    return resp_200(
        data=await AppQueryService.get_logs(
            app_id, actor=actor, tail=tail, since=since, keyword=keyword, entry=LOG_ENTRY_CLI
        )
    )

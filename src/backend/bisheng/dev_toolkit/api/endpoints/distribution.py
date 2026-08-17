"""Anonymous distribution endpoints for the ``bisheng`` CLI (design D10).

Both endpoints deliberately carry **no auth dependency**. The installer and its
version metadata are not confidential, and the whole point of the flow is that
an administrator forwards a link and the developer installs the CLI *before*
anyone hands them a key — "it is a link, not a file". The template is
``GET /api/v1/env``: a plain ``@router.get`` whose signature has no ``Depends``.

Why ``/api/v1`` and not ``/api/v2``: F049 plans to lift ``verify_open_api_access``
onto the whole ``router_rpc``, at which point every ``/api/v2`` endpoint must
carry a key — an anonymous endpoint there would become a permanent exception. A
bare path such as ``/cli/download`` is not reachable either: the commercial
gateway and the OSS nginx both forward only ``/api/v1/**`` and ``/api/v2/**``.

Why not MinIO pre-signed URLs: the installer is a static artifact shipped with
the image, and ``clear_minio_share_host`` hands back a path that depends on the
front-end nginx proxy — a CLI connecting directly would get a URL it cannot use.
"""

from fastapi import APIRouter
from fastapi.responses import FileResponse, JSONResponse

from bisheng.common.schemas.api import resp_200, resp_500
from bisheng.common.services.config_service import settings
from bisheng.dev_toolkit.domain.services import artifact_service

router = APIRouter(prefix="/dev-toolkit", tags=["Dev Toolkit"])

CLI_DOWNLOAD_PATH = "/api/v1/dev-toolkit/cli/download"

# Read by a human staring at a failed `pip install`, so it names the actual
# problem (a release did not ship its build output) and the actual next step.
# Not an error code: F053 introduces none (CON-8), and a code here would also
# hand unauthenticated callers a way to tell "off" from "broken".

# user-facing string; swapping it for an ASCII comma would be a typo.
ARTIFACT_MISSING_MESSAGE = "CLI 安装件未随本次部署发布，请联系平台管理员"  # noqa: RUF001


@router.get("/versions")
def get_dev_toolkit_versions():
    """Version and compatibility truth for the CLI's pre-flight probe.

    Answers 200 even with nothing staged: the shape stays identical and ``cli``
    goes null, so an agent parsing the payload degrades instead of crashing.
    """
    snapshot = artifact_service.read_snapshot()

    cli = None
    if snapshot.cli is not None:
        cli = {
            "version": snapshot.cli.version,
            "min_compatible": snapshot.cli.min_compatible,
            "filename": snapshot.cli.filename,
            "sha256": snapshot.cli.sha256,
            "download_path": CLI_DOWNLOAD_PATH,
        }

    return resp_200(
        {
            "cli": cli,
            # F057 consumes this same endpoint for the SDK (its AC-01 / AC-03).
            # Holding the slots open now is what keeps that from becoming either
            # a second endpoint or a breaking reshape of this one.
            "sdk": {"version": None, "min_compatible": None, "download_path": None},
            "platform": {
                # From the manifest, never from `bisheng.__version__` — that one
                # is a hardcoded literal, so comparing the CLI against it would
                # be permanently right or permanently wrong.
                "version": snapshot.platform_version,
                "open_platform_enabled": settings.open_platform.enabled,
                "app_runtime_enabled": settings.app_runtime.enabled,
            },
            # Present in every response (null when healthy) so consumers never
            # have to branch on a key's existence.
            "notice": None if cli else ARTIFACT_MISSING_MESSAGE,
        }
    )


@router.get("/cli/download")
def download_cli_installer():
    """Stream the staged wheel. ``FileResponse`` handles Content-Length and Range."""
    snapshot = artifact_service.read_snapshot()
    if snapshot.cli is None:
        # A real HTTP 404, not the usual 200-plus-envelope: `pip install <url>`
        # is a client on this route, and handing pip a 200 carrying JSON would
        # make it try to install the envelope. Letting FileResponse point at a
        # missing path instead would raise a 500 with a traceback and disguise a
        # release problem as a platform outage.
        return JSONResponse(
            status_code=404,
            content=resp_500(code=404, message=ARTIFACT_MISSING_MESSAGE).model_dump(),
        )

    return FileResponse(
        snapshot.cli.path,
        filename=snapshot.cli.filename,
        media_type="application/octet-stream",
    )

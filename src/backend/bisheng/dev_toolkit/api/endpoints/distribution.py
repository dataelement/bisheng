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
from fastapi.responses import FileResponse, JSONResponse, Response

from bisheng.common.schemas.api import resp_200, resp_500
from bisheng.common.services.config_service import settings
from bisheng.dev_toolkit.domain.services import artifact_service

router = APIRouter(prefix="/dev-toolkit", tags=["Dev Toolkit"])

CLI_DOWNLOAD_PATH = "/api/v1/dev-toolkit/cli/download"

# Header the ``skills sync`` output reads to report each pack's version (AC-14).
# A header, not an envelope field, because the body is a tarball, not JSON.
PACK_VERSION_HEADER = "X-Bisheng-Pack-Version"

# Read by a developer whose `skills sync` came back empty. Names the actual
# cause (the pack this platform version does not carry) and is not an error code
# for the same reasons the CLI wheel's message is not (CON-8).
SKILL_PACK_MISSING_MESSAGE = "技能包不存在或未随本次部署发布，请确认名称或联系平台管理员"  # noqa: RUF001

# Read by a human staring at a failed `pip install`, so it names the actual
# problem (a release did not ship its build output) and the actual next step.
# Not an error code: F053 introduces none (CON-8), and a code here would also
# hand unauthenticated callers a way to tell "off" from "broken".

# user-facing string; swapping it for an ASCII comma would be a typo.
ARTIFACT_MISSING_MESSAGE = "CLI 安装件未随本次部署发布，请联系平台管理员"  # noqa: RUF001

# Read by an AI agent (or a human) that fetched the install guide URL from the
# tutorial's copy-paste prompt on a platform that ships no guide. Names the cause
# and the next step for the same reason the wheel's message does.
INSTALL_GUIDE_MISSING_MESSAGE = "安装指引未随本次部署发布，请联系平台管理员"  # noqa: RUF001


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


@router.get("/install-guide.md")
def get_install_guide():
    """Serve the CLI install-and-login guide as markdown for an AI agent to follow.

    Anonymous like its siblings: the tutorial's copy-paste prompt points an AI
    coding tool (Claude Code / Codex / Cursor / …) at this URL, and the agent
    fetches it *before* anyone has a working CLI or key — auth here would defeat
    the whole "one prompt, any agent installs it" flow. The ``.md`` suffix and
    ``text/markdown`` type tell the agent it is prose to execute, not JSON. A
    missing guide is a real 404 (not the 200-plus-envelope ``/api/v1`` habit) so
    a fetcher can tell "no guide shipped" apart from a transport error.
    """
    content = artifact_service.read_install_guide()
    if content is None:
        return JSONResponse(
            status_code=404,
            content=resp_500(code=404, message=INSTALL_GUIDE_MISSING_MESSAGE).model_dump(),
        )

    return Response(content=content, media_type="text/markdown; charset=utf-8")


@router.get("/skills/{pack}")
def download_skill_pack(pack: str):
    """Stream one developer skill pack as a gzip tarball for ``bisheng skills sync``.

    Anonymous like its siblings: a skill pack is public guidance, and the same
    bytes are what any in-platform consumer reads, so there is exactly one
    source and one distribution path (AC-15). An unknown pack is a real 404
    (not a 200-plus-envelope) so the CLI can tell "no such pack" apart from a
    transport error the same way the wheel route does; the ``{pack}`` path
    param means every name reaches this handler, and only a real pack dir with a
    ``SKILL.md`` gets packed.
    """
    archive = artifact_service.read_skill_pack(pack)
    if archive is None:
        return JSONResponse(
            status_code=404,
            content=resp_500(code=404, message=SKILL_PACK_MISSING_MESSAGE).model_dump(),
        )

    headers = {"Content-Disposition": f'attachment; filename="{archive.filename}"'}
    if archive.version:
        headers[PACK_VERSION_HEADER] = archive.version
    return Response(content=archive.content, media_type="application/gzip", headers=headers)

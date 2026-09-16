"""Anonymous distribution endpoints for the ``bisheng`` CLI (design D10).

Both endpoints deliberately carry **no auth dependency**. The installer and its
version metadata are not confidential, and the whole point of the flow is that
an administrator forwards a link and the developer installs the CLI *before*
anyone hands them a key — "it is a link, not a file". The template is
``GET /api/v1/env``: a plain ``@router.get`` whose signature has no ``Depends``.

Why ``/api/v1`` and not ``/api/v2``: ``router_rpc`` carries ``verify_open_api_access``
as its one router-level dependency (F053 design K14), so every ``/api/v2``
endpoint needs a key and is refused outright without an ``@open_api_scope``
marker — an anonymous endpoint there is impossible, not merely an exception. A
bare path such as ``/cli/download`` is not reachable either: the commercial
gateway and the OSS nginx both forward only ``/api/v1/**`` and ``/api/v2/**``.

Why not MinIO pre-signed URLs: the installer is a static artifact shipped with
the image, and ``clear_minio_share_host`` hands back a path that depends on the
front-end nginx proxy — a CLI connecting directly would get a URL it cannot use.
"""

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, JSONResponse, Response

from bisheng.common.schemas.api import resp_200, resp_500
from bisheng.common.services.config_service import settings
from bisheng.dev_toolkit.domain.services import artifact_service
from bisheng.open_api.domain.services.public_base_url import (
    model_gateway_base_url,
    resolve_public_base_url,
)

router = APIRouter(prefix="/dev-toolkit", tags=["Dev Toolkit"])

CLI_DOWNLOAD_PATH = "/api/v1/dev-toolkit/cli/download"

# F057 AC-01 / AC-02: the SDK is distributed by the platform itself, over the
# same anonymous, intranet-only route family as the CLI. Two addresses, because
# they serve two different clients: a human (or an agent) fetches the wheel from
# the download path, while pip — inside a hosted build container that cannot
# reach the public internet — resolves `bisheng-sdk` through the simple index.
SDK_DOWNLOAD_PATH = "/api/v1/dev-toolkit/sdk/download"
SDK_INDEX_PATH = "/api/v1/dev-toolkit/simple/"

# PEP 503 normalised project name. pip normalises whatever it is asked to
# install and then requests that exact path segment, so this spelling is not
# cosmetic: `bisheng_sdk/` would never be requested and the index would look
# empty to pip while looking fine in a browser.
SDK_PROJECT_NAME = "bisheng-sdk"

# Same judgement as the CLI's message: names the real cause (a release did not
# ship its build output) and the real next step, and is not an error code (D14).
SDK_MISSING_MESSAGE = "SDK 安装件未随本次部署发布，请联系平台管理员"  # noqa: RUF001

# The SDK guide is the「平台能力接线」pack's SKILL.md (决议-7). Missing means the
# pack did not ship — again a release problem, not a platform fault.
SDK_GUIDE_MISSING_MESSAGE = "SDK 开发者指南未随本次部署发布，请联系平台管理员"  # noqa: RUF001

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


def _versions_notice(cli: dict | None, sdk: dict | None) -> str | None:
    """One sentence naming whichever installer this deployment is missing."""
    missing = []
    if cli is None:
        missing.append(ARTIFACT_MISSING_MESSAGE)
    if sdk is None:
        missing.append(SDK_MISSING_MESSAGE)
    return "；".join(missing) if missing else None  # noqa: RUF001


@router.get("/versions")
def get_dev_toolkit_versions(request: Request):
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

    sdk = None
    if snapshot.sdk is not None:
        sdk = {
            "version": snapshot.sdk.version,
            # The platform's floor, not the wheel's own version: an application
            # pinned below it is refused at its first call (F057 AC-03). The SDK
            # reads this field before its first retrieve / storage request.
            "min_compatible": snapshot.sdk.min_compatible,
            "filename": snapshot.sdk.filename,
            "sha256": snapshot.sdk.sha256,
            "download_path": SDK_DOWNLOAD_PATH,
            "index_path": SDK_INDEX_PATH,
        }

    return resp_200(
        {
            "cli": cli,
            # F057 AC-01 / AC-03: the whole section goes null when no SDK wheel
            # shipped, rather than null-valued keys — the SDK reads "is there an
            # SDK on this platform at all" off this one branch, and `notice`
            # carries the human half.
            "sdk": sdk,
            # F052: where a local coding agent points its MCP client. One
            # address, derived the same way the skill packs derive theirs, so
            # the access-information panel does not compose a second URL of its
            # own. It carries no credential — the key is issued separately and
            # travels in the Authorization header.
            #
            # This router is only mounted when the open-capability layer is on,
            # so "the address does not appear where the layer is not deployed"
            # needs no code.
            "mcp": {
                "url": f"{resolve_public_base_url(request)}/api/v2/mcp",
                "transport": "streamable-http",
                "auth": "bearer",
            },
            # F051's slot, filled (T046). ``model_gateway_base_url`` is the one
            # producer of this address (F051 AC-30 / design D2) — the same
            # function ``GET /api/v2/auth/whoami`` answers with — so the
            # access-information panel and ``bisheng dev`` read it rather than
            # each appending ``/api/v2/model/v1`` to an origin of their own.
            # ``protocol`` says which client dialect the address speaks, because
            # the face answers Anthropic paths with a refusal (26202).
            "model": {
                "base_url": model_gateway_base_url(request),
                "protocol": "openai",
                "auth": "bearer",
            },
            "platform": {
                # From the manifest, never from `bisheng.__version__` — that one
                # is a hardcoded literal, so comparing the CLI against it would
                # be permanently right or permanently wrong.
                "version": snapshot.platform_version,
                # The address this deployment answers at, from the same producer
                # as `mcp` and `model` above. The access-information panel needs
                # it for the two rows it would otherwise build from the browser's
                # own origin (`bisheng login <地址>` and the installer link):
                # behind a gateway or a path prefix the origin is missing that
                # prefix, so a panel mixing the two sources would hand a
                # developer a login command that 404s next to an MCP address
                # that works. Unconfigured this resolves from *this* request's
                # forwarded Host, i.e. the browser's own address, so nothing
                # changes for a plain deployment.
                "base_url": resolve_public_base_url(request),
                "open_platform_enabled": settings.open_platform.enabled,
                "app_runtime_enabled": settings.app_runtime.enabled,
            },
            # Present in every response (null when healthy) so consumers never
            # have to branch on a key's existence. Both wheels are release
            # output of their own script, so a deployment can be missing either
            # one and the notice has to say which.
            "notice": _versions_notice(cli, sdk),
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


def _serve_sdk_wheel(filename: str | None):
    """Stream the staged SDK wheel, for both the bare and the named download path.

    Two routes, one handler: a human copies the bare path out of the access
    panel, while pip follows the index's link, whose last segment **must** be a
    legal wheel filename — pip derives the distribution's name and version from
    it and silently skips any link that does not look like one (it never reads
    ``Content-Disposition`` there). A wrong filename is a 404 rather than "the
    file we happen to have": the name is how the client states which artifact it
    verified the hash of.
    """
    snapshot = artifact_service.read_snapshot()
    if snapshot.sdk is None or (filename is not None and filename != snapshot.sdk.filename):
        # A real 404, not the 200-plus-envelope habit of /api/v1 — pip is a
        # client on this route and would try to install the envelope.
        return JSONResponse(
            status_code=404,
            content=resp_500(code=404, message=SDK_MISSING_MESSAGE).model_dump(),
        )

    return FileResponse(
        snapshot.sdk.path,
        filename=snapshot.sdk.filename,
        media_type="application/octet-stream",
    )


@router.get("/sdk/download")
def download_sdk_wheel():
    """Anonymous SDK download — the address a developer pastes into ``pip install``."""
    return _serve_sdk_wheel(None)


@router.get("/sdk/download/{filename}")
def download_sdk_wheel_by_filename(filename: str):
    """The same wheel under its own filename, which is what pip follows from the index."""
    return _serve_sdk_wheel(filename)


def _simple_index_html(title: str, links: list[str]) -> Response:
    """Minimal PEP 503 page. pip parses anchors; everything else is decoration."""
    body = "".join(links)
    return Response(
        content=(f"<!DOCTYPE html><html><head><title>{title}</title></head><body>{body}</body></html>"),
        media_type="text/html; charset=utf-8",
    )


@router.get("/simple/")
def sdk_simple_index_root():
    """PEP 503 index root: the hosted build's ``--extra-index-url`` points here.

    Listed unconditionally — the project page is where "no wheel shipped" turns
    into a 404, which is the answer pip knows how to report ("no matching
    distribution") instead of silently treating an empty root as a healthy index
    with nothing in it.
    """
    return _simple_index_html(
        "Simple index",
        [f'<a href="{SDK_PROJECT_NAME}/">{SDK_PROJECT_NAME}</a>'],
    )


@router.get("/simple/bisheng-sdk/")
def sdk_simple_index_project():
    """PEP 503 project page — one link, hash-pinned.

    The ``#sha256=`` fragment is what makes an unauthenticated, plain-HTTP
    intranet index safe to install from: pip verifies the digest before
    unpacking, so the bytes are checked even though the channel is not. The
    relative href climbs two segments to ``/api/v1/dev-toolkit/sdk/download/…``
    so the page works unchanged behind a gateway path prefix.
    """
    snapshot = artifact_service.read_snapshot()
    if snapshot.sdk is None:
        return JSONResponse(
            status_code=404,
            content=resp_500(code=404, message=SDK_MISSING_MESSAGE).model_dump(),
        )

    href = f"../../sdk/download/{snapshot.sdk.filename}"
    if snapshot.sdk.sha256:
        href = f"{href}#sha256={snapshot.sdk.sha256}"
    return _simple_index_html(
        SDK_PROJECT_NAME,
        [f'<a href="{href}">{snapshot.sdk.filename}</a>'],
    )


@router.get("/sdk-guide.md")
def get_sdk_guide():
    """The SDK developer guide as markdown — the same file the skill pack ships.

    Anonymous and ``.md`` for the same reasons as the install guide: an AI
    coding tool fetches it before anyone holds a key, and the suffix plus
    ``text/markdown`` tell it this is prose to follow. One source with the pack
    (决议-7), so the guide cannot drift from what the agent was taught.
    """
    content = artifact_service.read_sdk_guide()
    if content is None:
        return JSONResponse(
            status_code=404,
            content=resp_500(code=404, message=SDK_GUIDE_MISSING_MESSAGE).model_dump(),
        )

    return Response(content=content, media_type="text/markdown; charset=utf-8")


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

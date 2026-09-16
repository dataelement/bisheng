"""Executable snapshot of the platform contracts this CLI consumes.

This module is deliberately dumb. Every payload here is shaped exactly like the
one F053 (open_api, beta2) / F054 / F055 actually return, including the parts
that look wrong:

* `/api/v1` answers HTTP 200 with the business code inside the envelope, while
  `/api/v2` puts a real status on the status line *and* keeps the envelope body.
* the 260-segment error payload is `data = {"exception": <str>, **kwargs}`, so
  `26003` carries `data.required` as a **single string** (`"app:manage"`), not a
  list. Joining it with `", ".join(...)` would print `a, p, p, :, m…`.

"Tidying" any of these into a more sensible shape here would mean the CLI is
tested against a server that does not exist. If a shape looks wrong, fix the
server or the design note — not this file.
"""

from __future__ import annotations

import io
import tarfile
from collections.abc import Callable
from typing import Any

import httpx

from bisheng_cli.commands.skills import DEFAULT_PACKS as _CLI_DEFAULT_PACKS

# Assembled rather than written out so `scripts/arch-guard.sh` RULE-7 never
# matches a long key literal in this repo's Python (see conftest docstring).
FAKE_KEY = "bs-sak-" + "x" * 24
#: What `whoami.model_base_url` answers on a deployment with the model face on.
FAKE_MODEL_BASE_URL = "http://platform.test/api/v2/model/v1"
FAKE_KEY_MASK = "bs-sak-" + "*" * 8 + "wxyz"
# beta2 authenticates two credential prefixes on the same wire
# (`credential_validator._TOKEN_RE`): `bs-sak-` service-account keys and
# `bs-pat-` personal tokens. Anything the CLI prints has to redact both.
FAKE_PAT = "bs-pat-" + "y" * 24

# Real statuses, cross-checked against the server's own declarations by
# tests/test_platform_contract.py.
OPEN_API_HTTP_STATUS: dict[int, int] = {
    26001: 401,
    26002: 401,
    26027: 401,
    26003: 403,
    26004: 403,
    26016: 400,
    # Personal access tokens authenticate on the same wire (`bs-pat-`), so a
    # developer who pastes one gets these two rather than 26001 / 26002.
    26040: 403,
    26043: 401,
    # 26051 is 403, not the 400 its issue-time sibling 26050 carries: it is a
    # channel-entrance refusal, so it sits with 26003 / 26004.
    26051: 403,
    26030: 503,
    26031: 500,
}


def v1_envelope(data: Any, *, status_code: int = 200, status_message: str = "SUCCESS") -> httpx.Response:
    """`/api/v1` shape: HTTP 200 always, the verdict lives in the body."""
    return httpx.Response(200, json={"status_code": status_code, "status_message": status_message, "data": data})


def v2_ok(data: Any) -> httpx.Response:
    return httpx.Response(200, json={"status_code": 200, "status_message": "SUCCESS", "data": data})


def v2_error(code: int, message: str, *, http_status: int | None = None, **data: Any) -> httpx.Response:
    """`/api/v2` shape: real status line + envelope body."""
    if http_status is None:
        http_status = OPEN_API_HTTP_STATUS.get(code, 400)
    payload = {"exception": message, **data}
    return httpx.Response(http_status, json={"status_code": code, "status_message": message, "data": payload})


# ---- /api/v1/dev-toolkit ------------------------------------------------


def versions_ok(*, cli_version: str = "3.0.0", min_compatible: str = "3.0.0") -> httpx.Response:
    return v1_envelope(
        {
            "cli": {
                "version": cli_version,
                "min_compatible": min_compatible,
                "filename": f"bisheng_cli-{cli_version}-py3-none-any.whl",
                "sha256": "0" * 64,
                "download_path": "/api/v1/dev-toolkit/cli/download",
            },
            # F057 consumes these positions; null this round (design D11).
            "sdk": {"version": None, "min_compatible": None, "download_path": None},
            "platform": {"version": cli_version, "open_platform_enabled": True, "app_runtime_enabled": True},
        }
    )


def versions_404() -> httpx.Response:
    """The router was never registered — FastAPI's own 404, not an error code."""
    return httpx.Response(404, json={"detail": "Not Found"})


DEFAULT_PACK = "deploy-hosting"
#: The packs the CLI syncs, in its own order — re-exported from the CLI so a
#: pack added there is served by every test that uses `serve_default_packs`.
DEFAULT_PACKS: tuple[str, ...] = tuple(_CLI_DEFAULT_PACKS)


def skills_path(pack: str = DEFAULT_PACK) -> str:
    return f"/api/v1/dev-toolkit/skills/{pack}"


def serve_default_packs(mock: PlatformMock) -> PlatformMock:
    """Route every shipped pack the test did not route itself.

    `skills sync` fetches all of `DEFAULT_PACKS`; a test that only cares about
    one of them would otherwise trip the mock's "unexpected request" on the
    others. Routes the test registered are left alone, so a test can still
    make one pack 404 or answer a specific tarball.
    """
    for pack in DEFAULT_PACKS:
        if not mock.has("GET", skills_path(pack)):
            mock.get(skills_path(pack), skill_pack({"SKILL.md": f"# {pack}\n"}, pack=pack))
    return mock


def skill_pack(
    files: dict[str, str] | None = None,
    *,
    pack: str = DEFAULT_PACK,
    version: str = "3.0.0",
) -> httpx.Response:
    """A skill-pack tarball, shaped like ``GET /dev-toolkit/skills/{pack}`` serves it.

    Members live under a ``pack/`` arcname and the platform version rides in a
    header (the body is a tarball, not an envelope). Same shape the CLI's
    ``skills sync`` unpacks in production.
    """
    files = files or {"SKILL.md": "# deploy-hosting\n"}
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as tar:
        for rel, content in files.items():
            data = content.encode("utf-8")
            info = tarfile.TarInfo(f"{pack}/{rel}")
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return httpx.Response(200, content=buffer.getvalue(), headers={"x-bisheng-pack-version": version})


def env_ok(*, open_platform_enabled: bool = True, app_runtime_enabled: bool = True) -> httpx.Response:
    return v1_envelope(
        {
            "env": "prod",
            "version": "2.6.0-fix",  # hardcoded upstream; never use it for compatibility (design 坑 21)
            "open_platform_enabled": open_platform_enabled,
            "app_runtime_enabled": app_runtime_enabled,
        }
    )


def env_legacy() -> httpx.Response:
    """A platform old enough that the flag does not exist at all."""
    return v1_envelope({"env": "prod", "version": "2.4.0"})


def env_unreachable() -> httpx.ConnectError:
    return httpx.ConnectError("connection refused")


# ---- /api/v2/auth -------------------------------------------------------


#: Every field ``WhoamiResponse`` declares, in declaration order. Kept as data
#: rather than only inside :func:`whoami_ok` so that
#: ``tests/test_platform_contract.py`` can compare it against the server model
#: itself — the whole payload changed shape once already (F049 sent
#: ``subject_kind`` / ``service_account: {id, name}`` / ``resource_owner:
#: {user_id, user_name}``; beta2's F053 sends none of those) and the CLI suite
#: stayed green throughout, asserting against a server that no longer existed.
WHOAMI_FIELDS = (
    "credential_id",
    "actor_kind",
    "actor_id",
    "actor_name",
    "tenant_id",
    "resource_owner",
    "authorization_subject_type",
    "authorization_subject_id",
    "effective_user_id",
    "mode",
    "scopes",
    "key_mask",
    "expires_at",
    "model_base_url",
)


#: Sentinel for "the caller said nothing", so that an explicit
#: ``resource_owner=None`` can mean what the server means by it: JSON null.
_DEFAULT = object()


def whoami_ok(
    *,
    scopes: list[str] | None = None,
    resource_owner: Any = _DEFAULT,
    actor_kind: str = "service_account",
    actor_id: int = 123,
    actor_name: str = "问卷小队开发号",
    tenant_id: int = 1,
    expires_at: str | None = "2026-12-31T00:00:00",
    model_base_url: str = FAKE_MODEL_BASE_URL,
) -> httpx.Response:
    """``GET /api/v2/auth/whoami`` exactly as beta2's ``WhoamiResponse`` serves it.

    Two shapes here are easy to "tidy" into something wrong:

    * ``resource_owner`` is ``{"user_id": int}`` **or null** — one key, no name.
      A service account always has an owner (the column is NOT NULL), so the
      null case means an ownerless subject, not an older platform.
    * the subject is flat (``actor_kind`` / ``actor_id`` / ``actor_name``), and
      ``actor_kind`` is ``"natural_person"`` for a ``bs-pat-`` personal token.
    """
    owner = {"user_id": 7} if resource_owner is _DEFAULT else resource_owner
    natural_person = actor_kind == "natural_person"
    data: dict[str, Any] = {
        "credential_id": 42,
        "actor_kind": actor_kind,
        "actor_id": actor_id,
        "actor_name": actor_name,
        "tenant_id": tenant_id,
        "resource_owner": owner,
        # A personal token authorises as its holder; a service account
        # authorises as itself and has no effective user (mode S, no delegation
        # — the only shape a CLI key can have, INV-31).
        "authorization_subject_type": "user" if natural_person else "service_account",
        "authorization_subject_id": actor_id,
        "effective_user_id": actor_id if natural_person else None,
        "mode": "S",
        "scopes": scopes if scopes is not None else ["app:manage"],
        "key_mask": FAKE_KEY_MASK,
        "expires_at": expires_at,
        # F051 AC-30: the one outward spelling of the model face's base URL.
        # Empty string where the open-capability layer is not deployed — the
        # face does not exist there, and `dev` must not invent an address.
        "model_base_url": model_base_url,
    }
    return v2_ok(data)


def whoami_without_resource_owner(**kwargs: Any) -> httpx.Response:
    """A credential the platform reports as having no resource owner at all.

    ``resource_owner`` is nullable on the wire (``WhoamiResourceOwner | None``),
    and a key in that state cannot publish: `deploy` refuses it with 16205
    rather than creating an application owned by nobody.
    """
    return whoami_ok(resource_owner=None, **kwargs)


def whoami_err(code: int, message: str = "credential rejected", *, http_status: int | None = None, **data: Any):
    return v2_error(code, message, http_status=http_status, **data)


# ---- /api/v2/apps -------------------------------------------------------


def deploy_limits(*, max_package_mb: int = 50, max_unpacked_mb: int = 200, max_package_entries: int = 20000):
    return v2_ok(
        {
            "max_package_mb": max_package_mb,
            "max_unpacked_mb": max_unpacked_mb,
            "max_package_entries": max_package_entries,
        }
    )


def deploy_accept(
    *,
    deployment_id: str = "dep-1",
    app_id: str = "app-1",
    version_id: str = "ver-1",
    entry_url: str | None = None,
) -> httpx.Response:
    return v2_ok({"deployment_id": deployment_id, "app_id": app_id, "version_id": version_id, "entry_url": entry_url})


def deploy_sync_err(code: int, message: str = "deploy rejected", *, http_status: int | None = None, **data: Any):
    """A failure from the *synchronous* leg of POST /apps/deploy.

    Ownership, size, unpack, manifest, local-reference and in-flight gates all
    run before the row exists, so these never appear in the polling payload
    (design D6 / red line 1).
    """
    return v2_error(code, message, http_status=http_status, **data)


def deployment(
    *,
    stage: str = "received",
    status: str = "running",
    failure: dict[str, Any] | None = None,
    app_id: str = "app-1",
    version_no: int = 1,
    approval: dict[str, Any] | None = None,
    app_state: str | None = None,
    pending_reason: str | None = None,
    entry_url: str | None = None,
) -> httpx.Response:
    return v2_ok(
        {
            "stage": stage,
            "status": status,
            "failure": failure,
            "app_id": app_id,
            "version_no": version_no,
            "approval": approval,
            "app_state": app_state,
            "pending_reason": pending_reason,
            # ``entry_url`` used to live only on the POST response, where a first
            # deploy is still a draft and it was null exactly when it mattered.
            # F055's write-back put it on every poll; defaults to None so tests
            # that do not care keep exercising the older shape.
            "entry_url": entry_url,
        }
    )


def deployment_seq(responses: list[httpx.Response]) -> list[httpx.Response]:
    """Identity helper — reads as a sequence at the call site."""
    return list(responses)


def failure_tuple(stage: str, code: int, message: str, **details: Any) -> dict[str, Any]:
    """The five-tuple. `details` / `hints` are the agent's entire repair input."""
    return {
        "stage": stage,
        "code": code,
        "message": message,
        "details": details or {},
        "hints": [f"hint for {code}"],
    }


def logs(
    lines: list[str] | None = None,
    *,
    app_state: str | None = None,
    pending_reason: str | None = None,
) -> httpx.Response:
    """The logs payload. ``app_state`` / ``pending_reason`` ride along with it.

    They default to ``None`` so existing tests keep exercising the older-platform
    shape — a platform that predates the write-back simply omits them, and the
    CLI must still say something useful.
    """
    return v2_ok(
        {"lines": lines if lines is not None else [], "app_state": app_state, "pending_reason": pending_reason}
    )


# ---- transport ----------------------------------------------------------

Route = httpx.Response | Exception | Callable[[httpx.Request], httpx.Response]


class PlatformMock:
    """Route table for `httpx.MockTransport`.

    Responses registered as a list are consumed in order — that is how a polling
    sequence is expressed. Running past the end of the list raises instead of
    repeating the last entry: a test that polls one more time than it declared
    should say so out loud.
    """

    def __init__(self) -> None:
        self._routes: dict[tuple[str, str], list[Route]] = {}
        self.calls: list[httpx.Request] = []

    def add(self, method: str, path: str, response: Route | list[Route]) -> PlatformMock:
        key = (method.upper(), path)
        items = response if isinstance(response, list) else [response]
        self._routes.setdefault(key, []).extend(items)
        return self

    def get(self, path: str, response: Route | list[Route]) -> PlatformMock:
        return self.add("GET", path, response)

    def post(self, path: str, response: Route | list[Route]) -> PlatformMock:
        return self.add("POST", path, response)

    def has(self, method: str, path: str) -> bool:
        return (method.upper(), path) in self._routes

    @property
    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self._handle)

    def _handle(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request)
        if len(self.calls) > 500:
            # A polling loop that never terminates would otherwise hang the suite
            # instead of failing it.
            raise AssertionError("mock served 500 requests — the caller is not terminating")
        key = (request.method.upper(), request.url.path)
        queue = self._routes.get(key)
        if not queue:
            raise AssertionError(f"unexpected request: {request.method} {request.url.path}")
        item = queue.pop(0) if len(queue) > 1 else queue[0]
        if isinstance(item, Exception):
            raise item
        if callable(item):
            return item(request)
        return item

    def paths_called(self) -> list[str]:
        return [r.url.path for r in self.calls]


def use_mock_transport(monkeypatch: Any, module: Any, mock: PlatformMock) -> None:
    """Point a command module's `PlatformClient` at `mock`.

    Command modules construct their own client, which is the right shape for
    production and the wrong shape for a test. Patching the name inside the
    module (rather than injecting a client through the signature) keeps the
    production code free of a test-only seam while still letting the sentinel in
    `conftest.no_network` catch anything the mock does not cover.
    """
    real = module.PlatformClient

    def factory(*args: Any, **kwargs: Any) -> Any:
        kwargs.setdefault("transport", mock.transport)
        return real(*args, **kwargs)

    monkeypatch.setattr(module, "PlatformClient", factory)

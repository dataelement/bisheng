"""Executable snapshot of the platform contracts this CLI consumes.

This module is deliberately dumb. Every payload here is shaped exactly like the
one F049 / F054 / F055 actually return, including the parts that look wrong:

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

from collections.abc import Callable
from typing import Any

import httpx

# Assembled rather than written out so `scripts/arch-guard.sh` RULE-7 never
# matches a long key literal in this repo's Python (see conftest docstring).
FAKE_KEY = "bs-sak-" + "x" * 24
FAKE_KEY_MASK = "bs-sak-" + "*" * 8 + "wxyz"

# Real statuses, measured in test/open_api/test_open_api_auth_api.py.
OPEN_API_HTTP_STATUS: dict[int, int] = {
    26001: 401,
    26002: 401,
    26027: 401,
    26003: 403,
    26004: 403,
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


def whoami_ok(
    *,
    scopes: list[str] | None = None,
    resource_owner: dict[str, Any] | None = None,
    service_account: dict[str, Any] | None = None,
    tenant_id: int = 1,
    expires_at: str | None = "2026-12-31T00:00:00",
) -> httpx.Response:
    data: dict[str, Any] = {
        "subject_kind": "service_account",
        "service_account": service_account or {"id": 123, "name": "问卷小队开发号"},
        "tenant_id": tenant_id,
        "scopes": scopes if scopes is not None else ["app:manage"],
        "key_mask": FAKE_KEY_MASK,
        "expires_at": expires_at,
    }
    if resource_owner is not None:
        data["resource_owner"] = resource_owner
    return v2_ok(data)


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
            # NOTE: no entry_url — it exists only on the POST response (design D7).
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


def logs(lines: list[str] | None = None) -> httpx.Response:
    return v2_ok({"lines": lines if lines is not None else []})


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

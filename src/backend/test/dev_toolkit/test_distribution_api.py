"""F053 T027 — the platform's CLI distribution endpoints.

Covers AC-01 (anonymous download + version info), AC-02 (version truth comes
from the shipped manifest, never from ``/api/v1/env``) and AC-05 (the endpoints
are *absent*, not merely refusing, when the open-capability layer is off).
"""

from __future__ import annotations

import hashlib

from test.dev_toolkit.conftest import (
    CLI_MIN_COMPATIBLE,
    CLI_VERSION,
    MANIFEST_PLATFORM_VERSION,
    WHEEL_BYTES,
    WHEEL_NAME,
)

VERSIONS_PATH = "/api/v1/dev-toolkit/versions"
DOWNLOAD_PATH = "/api/v1/dev-toolkit/cli/download"


def _route(app, path):
    for route in app.routes:
        if getattr(route, "path", None) == path:
            return route
    return None


def _dependency_names(dependant) -> set[str]:
    """Every callable in the dependency tree of a route, by name."""
    names: set[str] = set()
    for dependency in dependant.dependencies:
        call = getattr(dependency, "call", None)
        if call is not None:
            names.add(getattr(call, "__name__", repr(call)))
        names |= _dependency_names(dependency)
    return names


def test_versions_reachable_without_any_credential(staged_artifacts, client_factory):
    """No Bearer, no session cookie — a developer meets this endpoint before they hold a key."""
    client = client_factory()

    response = client.get(VERSIONS_PATH)

    assert response.status_code == 200
    body = response.json()
    assert body["status_code"] == 200

    # Structural half: nothing in the dependency tree can ever demand a login or
    # a key. A green request alone would not catch a dependency that merely
    # happens to admit anonymous callers today.
    route = _route(client.app, VERSIONS_PATH)
    assert route is not None
    assert _dependency_names(route.dependant) == set()
    assert route.dependant.security_requirements == []


def test_versions_payload_shape(staged_artifacts, client_factory):
    """``cli`` / ``sdk`` / ``platform`` field slots, all three present in one round.

    The ``sdk`` slots are null this round but must exist: F057 (AC-01 / AC-03)
    consumes this same endpoint, and leaving them out would force either a
    second endpoint or a breaking reshape later.
    """
    client = client_factory(app_runtime_enabled=True)

    data = client.get(VERSIONS_PATH).json()["data"]

    assert data["cli"] == {
        "version": CLI_VERSION,
        "min_compatible": CLI_MIN_COMPATIBLE,
        "filename": WHEEL_NAME,
        "sha256": hashlib.sha256(WHEEL_BYTES).hexdigest(),
        "download_path": DOWNLOAD_PATH,
    }

    assert set(data["sdk"]) == {"version", "min_compatible", "download_path"}
    assert all(value is None for value in data["sdk"].values())

    assert data["platform"]["open_platform_enabled"] is True
    assert data["platform"]["app_runtime_enabled"] is True
    assert data["platform"]["version"] == MANIFEST_PLATFORM_VERSION


def test_platform_version_not_taken_from_env_endpoint(monkeypatch, staged_artifacts, client_factory):
    """``platform.version`` reads the shipped manifest, not ``bisheng.__version__``.

    ``GET /api/v1/env`` serves a hardcoded ``'2.6.0-fix'`` (``bisheng/__init__.py``)
    — comparing the CLI against that value would make every compatibility check
    permanently right or permanently wrong, and both are useless.
    """
    from bisheng import __version__ as hardcoded_env_version
    from bisheng.dev_toolkit.domain.services import artifact_service

    client = client_factory()

    data = client.get(VERSIONS_PATH).json()["data"]
    assert data["platform"]["version"] == MANIFEST_PLATFORM_VERSION
    assert data["platform"]["version"] != hardcoded_env_version

    # With nothing staged the field goes null. This is the assertion that bites:
    # "fixing" the empty case with a fallback to ``bisheng.__version__`` would
    # quietly reintroduce the hardcoded literal as the platform's version truth.
    monkeypatch.setattr(artifact_service, "ARTIFACTS_DIR", staged_artifacts / "gone")
    assert client.get(VERSIONS_PATH).json()["data"]["platform"]["version"] is None


def test_download_returns_file_response_with_content_disposition_and_length(staged_artifacts, client_factory):
    client = client_factory()

    response = client.get(DOWNLOAD_PATH)

    assert response.status_code == 200
    assert response.content == WHEEL_BYTES
    assert response.headers["content-length"] == str(len(WHEEL_BYTES))
    # pip resolves the wheel's filename from this header when the URL path does
    # not end in one — without it `pip install <url>` cannot name the artifact.
    assert WHEEL_NAME in response.headers["content-disposition"]
    assert response.headers["content-type"] == "application/octet-stream"


def test_download_requires_no_login_and_no_key(staged_artifacts, client_factory):
    """An administrator forwards a link; the developer downloads before owning a key (AC-01)."""
    client = client_factory()

    anonymous = client.get(DOWNLOAD_PATH)
    # A garbage credential must not change the outcome either — that would mean
    # some credential path is being consulted.
    with_garbage = client.get(
        DOWNLOAD_PATH,
        headers={"Authorization": "Bearer bs-sak-not-a-real-key"},
        cookies={"access_token_cookie": "not-a-real-jwt"},
    )

    assert anonymous.status_code == 200
    assert with_garbage.status_code == 200

    route = _route(client.app, DOWNLOAD_PATH)
    assert _dependency_names(route.dependant) == set()
    assert route.dependant.security_requirements == []


def test_routes_absent_when_open_platform_disabled(staged_artifacts, client_factory):
    """AC-05 lands as *no route*, not as an error code.

    A dedicated error code would tell an unauthenticated caller "there is a
    feature here, it is just switched off". Not registering the router leaves
    FastAPI's own 404 and adds no error code at all (CON-8).
    """
    client = client_factory(open_platform_enabled=False)

    assert client.get(VERSIONS_PATH).status_code == 404
    assert client.get(DOWNLOAD_PATH).status_code == 404
    assert [r for r in client.app.routes if getattr(r, "path", "").startswith("/api/v1/dev-toolkit")] == []


def test_multi_tenant_enabled_no_jwt_does_not_raise_no_tenant_context(monkeypatch, staged_artifacts, client_factory):
    """Regression guard for T029: the path is on ``TENANT_CHECK_EXEMPT_PATHS``.

    With multi-tenancy on and no JWT the middleware never calls
    ``set_current_tenant_id``, so the tenant ContextVar stays empty and any DAO
    SELECT resolves to ``NoTenantContextError``. The exemption puts the whole
    call tree under ``_bypass_tenant_filter``, which is the only reason a
    handler on this path may ever touch a tenant-aware table.
    """
    from bisheng.common.errcode.tenant import NoTenantContextError
    from bisheng.core.context.tenant import is_tenant_filter_bypassed
    from bisheng.core.database.tenant_filter import _resolve_tenant_id
    from bisheng.dev_toolkit.domain.services import artifact_service
    from bisheng.utils import http_middleware

    assert "/api/v1/dev-toolkit" in http_middleware.TENANT_CHECK_EXEMPT_PATHS

    seen: dict[str, bool] = {}
    real_read_snapshot = artifact_service.read_snapshot

    def _probe():
        seen["bypassed"] = is_tenant_filter_bypassed()
        try:
            _resolve_tenant_id()
            seen["context_present"] = True
        except NoTenantContextError:
            seen["context_present"] = False
        return real_read_snapshot()

    monkeypatch.setattr(artifact_service, "read_snapshot", _probe)

    client = client_factory(multi_tenant=True)
    response = client.get(VERSIONS_PATH)

    assert response.status_code == 200
    assert seen["bypassed"] is True
    # The danger is real, not hypothetical: there genuinely is no tenant context
    # on this request, so without the exemption the first SELECT would raise.
    assert seen["context_present"] is False

    # Control: drop the prefix from the exempt list and the very same request
    # runs unprotected. This is what makes the assertion above load-bearing
    # rather than a restatement of the middleware's default.
    monkeypatch.setattr(
        http_middleware,
        "TENANT_CHECK_EXEMPT_PATHS",
        tuple(p for p in http_middleware.TENANT_CHECK_EXEMPT_PATHS if p != "/api/v1/dev-toolkit"),
    )
    seen.clear()
    client.get(VERSIONS_PATH)
    assert seen["bypassed"] is False


def test_missing_artifacts_degrade_readably_not_500(absent_artifacts, client_factory):
    """A checkout that never ran ``scripts/pack_cli_wheel.sh`` has no wheel at all.

    That is a release problem ("the artifact was not committed"), and it must
    read like one. A 500 with a traceback would disguise it as a broken
    platform, and this test is the only automated warning for that class of
    release accident.
    """
    client = client_factory()

    versions = client.get(VERSIONS_PATH)
    assert versions.status_code == 200
    data = versions.json()["data"]
    assert data["cli"] is None
    # The shape survives so an agent's parser does not crash on the degraded case.
    assert set(data["sdk"]) == {"version", "min_compatible", "download_path"}
    assert data["platform"]["open_platform_enabled"] is True
    assert isinstance(data["notice"], str) and data["notice"]

    download = client.get(DOWNLOAD_PATH)
    assert download.status_code == 404
    assert "CLI 安装件未随本次部署发布" in download.json()["status_message"]

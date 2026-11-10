"""F057 T026 — the platform distributes the SDK itself (AC-01 / AC-02 / AC-03 / AC-05 / AC-26).

Four anonymous routes ride the F053 dev-toolkit router: the wheel download (bare
and under its filename), the PEP 503 simple index (root + project page) and the
developer guide. Two different clients read them — a developer or an agent
follows the download path and the guide, while **pip inside a hosted build
container** resolves ``bisheng-sdk`` through the index without any public
internet — so the assertions below pin the pip-facing details (normalised
project name, a link whose last segment is a legal wheel filename, the
``#sha256=`` fragment) as hard as the human-facing ones.
"""

from __future__ import annotations

import hashlib

from test.dev_toolkit.conftest import (
    SDK_MIN_COMPATIBLE,
    SDK_VERSION,
    SDK_WHEEL_BYTES,
    SDK_WHEEL_NAME,
)

VERSIONS_PATH = "/api/v1/dev-toolkit/versions"
SDK_DOWNLOAD_PATH = "/api/v1/dev-toolkit/sdk/download"
SDK_DOWNLOAD_NAMED_PATH = f"/api/v1/dev-toolkit/sdk/download/{SDK_WHEEL_NAME}"
SIMPLE_ROOT_PATH = "/api/v1/dev-toolkit/simple/"
SIMPLE_PROJECT_PATH = "/api/v1/dev-toolkit/simple/bisheng-sdk/"
SDK_GUIDE_PATH = "/api/v1/dev-toolkit/sdk-guide.md"

SDK_SHA256 = hashlib.sha256(SDK_WHEEL_BYTES).hexdigest()


def _route(app, path):
    for route in app.routes:
        if getattr(route, "path", None) == path:
            return route
    return None


def _dependency_names(dependant) -> set[str]:
    names: set[str] = set()
    for dependency in dependant.dependencies:
        call = getattr(dependency, "call", None)
        if call is not None:
            names.add(getattr(call, "__name__", repr(call)))
        names |= _dependency_names(dependency)
    return names


def test_versions_sdk_section_when_staged(staged_artifacts, client_factory):
    """Six keys, values straight off the manifest — no key invented by the endpoint."""
    client = client_factory()

    data = client.get(VERSIONS_PATH).json()["data"]

    assert data["sdk"] == {
        "version": SDK_VERSION,
        "min_compatible": SDK_MIN_COMPATIBLE,
        "filename": SDK_WHEEL_NAME,
        "sha256": SDK_SHA256,
        "download_path": SDK_DOWNLOAD_PATH,
        "index_path": SIMPLE_ROOT_PATH,
    }
    assert data["notice"] is None


def test_versions_sdk_null_and_notice_when_not_staged(staged_cli_only, client_factory):
    """An F053-era deployment: the CLI half is intact and the SDK half says so.

    The whole section goes null rather than null-valued keys: the SDK reads one
    branch to decide "this platform ships no SDK" (which it reports as
    ``PlatformTooOldError``), and a dict of nulls would make that a three-field
    inspection.
    """
    client = client_factory()

    data = client.get(VERSIONS_PATH).json()["data"]

    assert data["sdk"] is None
    assert data["cli"] is not None
    assert "SDK 安装件未随本次部署发布" in data["notice"]


def test_sdk_download_streams_the_wheel_anonymously(staged_artifacts, client_factory):
    """No Bearer, no cookie — the developer installs before anyone hands them a key."""
    client = client_factory()

    response = client.get(SDK_DOWNLOAD_PATH)

    assert response.status_code == 200
    assert response.content == SDK_WHEEL_BYTES
    assert response.headers["content-length"] == str(len(SDK_WHEEL_BYTES))
    assert SDK_WHEEL_NAME in response.headers["content-disposition"]
    assert response.headers["content-type"] == "application/octet-stream"

    route = _route(client.app, SDK_DOWNLOAD_PATH)
    assert route is not None
    assert _dependency_names(route.dependant) == set()
    assert route.dependant.security_requirements == []


def test_sdk_download_with_filename_accepts_only_the_manifest_filename(staged_artifacts, client_factory):
    """pip follows the index link, whose last segment is the wheel's own name."""
    client = client_factory()

    assert client.get(SDK_DOWNLOAD_NAMED_PATH).content == SDK_WHEEL_BYTES
    # A stale link (an older release's filename) must not silently serve today's
    # wheel: the client verified a hash against *that* name.
    other = client.get("/api/v1/dev-toolkit/sdk/download/bisheng_sdk-0.0.9-py3-none-any.whl")
    assert other.status_code == 404


def test_sdk_download_missing_is_a_real_404_with_an_envelope(staged_cli_only, client_factory):
    """Not a 200 carrying JSON (pip would install the envelope), not a 500."""
    client = client_factory()

    for path in (SDK_DOWNLOAD_PATH, SDK_DOWNLOAD_NAMED_PATH):
        response = client.get(path)
        assert response.status_code == 404
        assert "SDK 安装件未随本次部署发布" in response.json()["status_message"]


def test_simple_index_root_lists_the_normalised_project_name(staged_artifacts, client_factory):
    client = client_factory()

    response = client.get(SIMPLE_ROOT_PATH)

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    # PEP 503 normalisation is not cosmetic: pip requests exactly this segment,
    # so `bisheng_sdk/` would make the index look empty to pip alone.
    assert 'href="bisheng-sdk/"' in response.text
    assert _dependency_names(_route(client.app, SIMPLE_ROOT_PATH).dependant) == set()


def test_simple_project_page_links_the_wheel_with_its_hash(staged_artifacts, client_factory):
    """The link pip follows: legal wheel filename + ``#sha256=`` so pip verifies the bytes."""
    client = client_factory()

    response = client.get(SIMPLE_PROJECT_PATH)

    assert response.status_code == 200
    assert f'href="../../sdk/download/{SDK_WHEEL_NAME}#sha256={SDK_SHA256}"' in response.text
    # Two segments up from /api/v1/dev-toolkit/simple/bisheng-sdk/ is
    # /api/v1/dev-toolkit/ — relative so a gateway path prefix survives.
    assert "http://" not in response.text and "https://" not in response.text


def test_simple_project_page_404_when_not_staged(staged_cli_only, client_factory):
    """pip reports "no matching distribution"; an empty 200 page would read as "exists, no releases"."""
    client = client_factory()

    assert client.get(SIMPLE_PROJECT_PATH).status_code == 404
    # The root still answers so the index itself is not mistaken for a bad URL.
    assert client.get(SIMPLE_ROOT_PATH).status_code == 200


def test_sdk_guide_is_served_as_markdown_anonymously(staged_artifacts, client_factory):
    """The guide is the skill pack's own SKILL.md — one source, no second copy (决议-7)."""
    from bisheng.dev_toolkit.domain.services import artifact_service

    client = client_factory()

    response = client.get(SDK_GUIDE_PATH)

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/markdown")
    assert response.text == artifact_service.read_sdk_guide()
    assert _dependency_names(_route(client.app, SDK_GUIDE_PATH).dependant) == set()


def test_sdk_guide_missing_degrades_to_404_not_500(staged_artifacts, client_factory, monkeypatch):
    from bisheng.dev_toolkit.api.endpoints import distribution

    monkeypatch.setattr(distribution.artifact_service, "read_sdk_guide", lambda: None)
    client = client_factory()

    response = client.get(SDK_GUIDE_PATH)

    assert response.status_code == 404
    assert response.json()["status_code"] == 404


def test_all_sdk_routes_absent_when_open_platform_disabled(staged_artifacts, client_factory):
    """AC-05 lands as *no route*: the whole dev-toolkit router is never registered."""
    client = client_factory(open_platform_enabled=False)

    for path in (SDK_DOWNLOAD_PATH, SDK_DOWNLOAD_NAMED_PATH, SIMPLE_ROOT_PATH, SIMPLE_PROJECT_PATH, SDK_GUIDE_PATH):
        assert client.get(path).status_code == 404
    assert [r for r in client.app.routes if getattr(r, "path", "").startswith("/api/v1/dev-toolkit")] == []


def test_multi_tenant_no_jwt_does_not_raise_on_sdk_routes(staged_artifacts, client_factory):
    """The dev-toolkit prefix is tenant-exempt, so an anonymous pip request cannot 500.

    Same guard as the CLI download's: with multi-tenancy on and no JWT the
    tenant ContextVar is empty, and without the exemption the first tenant-aware
    SELECT under these handlers would raise ``NoTenantContextError``.
    """
    from bisheng.utils import http_middleware

    assert "/api/v1/dev-toolkit" in http_middleware.TENANT_CHECK_EXEMPT_PATHS

    client = client_factory(multi_tenant=True)

    assert client.get(SDK_DOWNLOAD_PATH).status_code == 200
    assert client.get(SIMPLE_PROJECT_PATH).status_code == 200
    assert client.get(SDK_GUIDE_PATH).status_code == 200

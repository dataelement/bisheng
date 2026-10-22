"""Offline harness contracts only; no assertion here proves a live deployment.

覆盖 AC: AC-35, AC-36, AC-55, AC-56
"""

from __future__ import annotations

import io
import json
import tarfile

import pytest

from test.e2e.helpers.vibe_runtime import (
    EvidenceJournal,
    Scenario,
    SuiteSettings,
    validate_package,
)


def package(path, document):
    with tarfile.open(path, "w:gz") as archive:
        content = json.dumps(document).encode()
        info = tarfile.TarInfo("bisheng-app.yaml")
        info.size = len(content)
        archive.addfile(info, io.BytesIO(content))
    return path


def test_settings_require_explicit_dedicated_tenant_and_safe_prefix(monkeypatch):
    """AC-55: no default production tenant or broad cleanup prefix is accepted."""
    monkeypatch.setenv("F059_E2E_TENANT_CODE", "production")
    with pytest.raises(ValueError, match="e2e-f059-"):
        SuiteSettings.from_env()


def test_settings_fail_without_explicit_live_opt_in(monkeypatch):
    """AC-55: importing or collecting the suite never starts a live mutation."""
    monkeypatch.setenv("F059_E2E_TENANT_CODE", "e2e-f059-tenant")
    monkeypatch.delenv("F059_E2E", raising=False)
    with pytest.raises(ValueError, match="F059_E2E=1"):
        SuiteSettings.from_env()


def test_package_name_and_slug_must_belong_to_suite(tmp_path):
    """AC-35, AC-55: package inspection rejects another application's identity."""
    path = package(tmp_path / "app.tar.gz", {"name": "foreign", "slug": "e2e-f059-smoke"})
    with pytest.raises(ValueError, match="name"):
        validate_package(path, "e2e-f059-smoke")


def test_package_is_inspected_without_extracting_paths(tmp_path):
    """AC-55: a nested or ambiguous manifest is not used to authorize cleanup."""
    path = tmp_path / "app.tar.gz"
    with tarfile.open(path, "w:gz") as archive:
        info = tarfile.TarInfo("../bisheng-app.yaml")
        info.size = 2
        archive.addfile(info, io.BytesIO(b"{}"))
    with pytest.raises(ValueError, match="root manifest"):
        validate_package(path, "e2e-f059-smoke")
    assert not (tmp_path.parent / "bisheng-app.yaml").exists()


def test_scenario_freezes_exact_slug_and_mode(tmp_path):
    """AC-24, AC-25, AC-55: expected delivery mode is checked before any API call."""
    path = package(
        tmp_path / "app.tar.gz",
        {
            "name": "e2e-f059-smoke",
            "slug": "e2e-f059-smoke",
            "runtime": "python3.11",
            "manifest_version": 2,
            "delivery": {"mode": "bundle"},
        },
    )
    scenario = Scenario.from_dict({"slug": "e2e-f059-smoke", "package": str(path), "mode": "bundle"})
    assert scenario.mode == "bundle"
    with pytest.raises(ValueError, match="delivery"):
        Scenario.from_dict({"slug": "e2e-f059-smoke", "package": str(path), "mode": "image"})


def test_journal_scope_cannot_change_and_contains_no_credentials(tmp_path):
    """AC-55: resume data is exact-scope, atomically saved and non-secret."""
    path = tmp_path / "evidence.json"
    journal = EvidenceJournal(path, tenant_code="e2e-f059-tenant")
    journal.record("case", ["AC-55"], "passed", app_id="app-1")
    journal.save()
    assert json.loads(path.read_text())["events"][0]["kind"] == "live-api"
    assert path.stat().st_mode & 0o077 == 0
    with pytest.raises(ValueError, match="secret"):
        journal.record("bad", ["AC-55"], "passed", access_token="fixture")
    with pytest.raises(ValueError, match="scope"):
        EvidenceJournal(path, tenant_code="e2e-f059-other")


def test_resumed_cleanup_registry_cannot_name_foreign_slug(tmp_path):
    """AC-35, AC-55: journal entries never authorize cleanup of another prefix."""
    path = tmp_path / "evidence.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "tenant_code": "e2e-f059-tenant",
                "apps": {"production": {"app_id": "someone-elses-app"}},
                "events": [],
            }
        )
    )
    with pytest.raises(ValueError, match="slug"):
        EvidenceJournal(path, tenant_code="e2e-f059-tenant")


@pytest.mark.parametrize("mismatch", ["owner", "tenant", "slug"])
async def test_cleanup_revalidates_scope_before_mutation(tmp_path, mismatch):
    """AC-35, AC-55: a listed ID cannot cause writes without a fresh exact owner/scope match."""
    from types import SimpleNamespace

    from test.e2e.helpers.vibe_runtime import LiveVibeSuite

    settings = SuiteSettings("e2e-f059-tenant", (SimpleNamespace(slug="e2e-f059-smoke"),))
    journal = EvidenceJournal(tmp_path / "evidence.json", tenant_code=settings.tenant_code)
    suite = LiveVibeSuite(settings, journal, None)
    suite.tenant_id = 7
    suite.users["OWNER"] = 42
    mutations = []

    async def request(method, path, **kwargs):
        if method != "GET":
            mutations.append((method, path))
            raise AssertionError("unsafe mutation")
        if path == "/apps":
            return [{"app_id": "app-1", "slug": "e2e-f059-smoke"}]
        detail = {
            "app_id": "app-1",
            "slug": "e2e-f059-smoke",
            "name": "e2e-f059-smoke",
            "owner_user_id": 42,
            "tenant_id": 7,
            "state": "online",
        }
        detail[{"owner": "owner_user_id", "tenant": "tenant_id", "slug": "slug"}[mismatch]] = "999"
        return detail

    suite.request = request
    with pytest.raises(AssertionError):
        await suite.cleanup()
    assert not mutations


@pytest.fixture
def tls_material(tmp_path):
    """Ephemeral loopback PKI only; no environment credential is read."""
    import datetime
    import ipaddress

    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID

    now = datetime.datetime.now(datetime.UTC)

    def authority(name):
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, name)])
        cert = (
            x509.CertificateBuilder()
            .subject_name(subject)
            .issuer_name(subject)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - datetime.timedelta(minutes=1))
            .not_valid_after(now + datetime.timedelta(days=1))
            .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
            .sign(key, hashes.SHA256())
        )
        return key, cert

    key, ca = authority("F059 local test CA")
    _, wrong = authority("F059 unrelated CA")
    leaf_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    leaf_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost")])
    leaf = (
        x509.CertificateBuilder()
        .subject_name(leaf_name)
        .issuer_name(ca.subject)
        .public_key(leaf_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(minutes=1))
        .not_valid_after(now + datetime.timedelta(days=1))
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]), critical=False)
        .sign(key, hashes.SHA256())
    )
    paths = {}
    for name, certificate in (("ca", ca), ("wrong-ca", wrong), ("server", leaf)):
        path = tmp_path / (name + ".pem")
        path.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
        paths[name] = path
    private = tmp_path / "server-key.pem"
    private.write_bytes(
        leaf_key.private_bytes(
            serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
        )
    )
    private.chmod(0o600)
    paths["key"] = private
    return paths


def test_explicit_public_ca_builds_verified_context_and_default_keeps_system_trust(tls_material):
    import ssl

    from test.e2e.helpers.vibe_runtime import build_tls_context

    default, custom = build_tls_context(), build_tls_context(tls_material["ca"])
    assert default.verify_mode == custom.verify_mode == ssl.CERT_REQUIRED
    assert default.check_hostname is True and custom.check_hostname is True
    assert len(custom.get_ca_certs()) == len(default.get_ca_certs()) + 1


@pytest.mark.parametrize(
    "invalid", ["missing", "directory", "symlink", "invalid-pem", "private-key", "certificate-and-key"]
)
def test_explicit_ca_rejects_non_public_regular_certificate_files(tmp_path, tls_material, invalid):
    from test.e2e.helpers.vibe_runtime import build_tls_context

    path = tmp_path / "input.pem"
    if invalid == "directory":
        path.mkdir()
    elif invalid == "symlink":
        path.symlink_to(tls_material["ca"])
    elif invalid == "invalid-pem":
        path.write_text("not-a-certificate PRIVATE_MATERIAL_SENTINEL")
    elif invalid == "private-key":
        path.write_bytes(tls_material["key"].read_bytes())
    elif invalid == "certificate-and-key":
        path.write_bytes(tls_material["ca"].read_bytes() + tls_material["key"].read_bytes())
    with pytest.raises(ValueError, match="F059_E2E_CA_FILE") as stopped:
        build_tls_context(path)
    assert "PRIVATE_MATERIAL_SENTINEL" not in str(stopped.value)
    assert "BEGIN" not in str(stopped.value) and str(path) not in str(stopped.value)


def test_settings_read_explicit_ca_file_before_any_http_request(tmp_path, tls_material, monkeypatch):
    import ssl

    from test.e2e.helpers import vibe_runtime

    app = package(
        tmp_path / "app.tar.gz",
        {"name": "e2e-f059-smoke", "slug": "e2e-f059-smoke", "runtime": "python3.11", "delivery": {"mode": "bundle"}},
    )
    scenarios = tmp_path / "scenarios.json"
    scenarios.write_text(json.dumps([{"slug": "e2e-f059-smoke", "package": str(app)}]))
    monkeypatch.setenv("F059_E2E", "1")
    monkeypatch.setenv("F059_E2E_TENANT_CODE", "e2e-f059-tenant")
    monkeypatch.setenv("F059_E2E_SCENARIOS", str(scenarios))
    monkeypatch.setenv("F059_E2E_CA_FILE", str(tls_material["ca"]))
    monkeypatch.setattr(vibe_runtime, "API_BASE", "https://127.0.0.1:9443/api/v1")
    settings = SuiteSettings.from_env()
    assert settings.ssl_context.verify_mode == ssl.CERT_REQUIRED and settings.ssl_context.check_hostname
    assert str(tls_material["ca"]) not in repr(settings)
    monkeypatch.setenv("F059_E2E_CA_FILE", str(tmp_path / "missing.pem"))
    with pytest.raises(ValueError, match="F059_E2E_CA_FILE"):
        SuiteSettings.from_env()


async def test_cli_uses_settings_context_for_http_even_with_trust_env_false(tmp_path, tls_material, monkeypatch):
    import importlib.util
    from pathlib import Path
    from types import SimpleNamespace

    import httpx

    from test.e2e.helpers import vibe_runtime

    path = Path(__file__).resolve().parents[4] / "scripts/e2e_k8s_runtime.py"
    spec = importlib.util.spec_from_file_location("f059_e2e_tls_cli", path)
    command = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(command)
    settings = SuiteSettings("e2e-f059-tenant", (), ssl_context=vibe_runtime.build_tls_context(tls_material["ca"]))
    observed = []

    class Client:
        def __init__(self, **kwargs):
            observed.append(kwargs)

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

    class Suite:
        def __init__(self, actual_settings, journal, client):
            assert actual_settings is settings

        async def authenticate(self):
            return None

        async def installation(self):
            return None

    monkeypatch.setattr(vibe_runtime.SuiteSettings, "from_env", lambda: settings)
    monkeypatch.setattr(vibe_runtime, "LiveVibeSuite", Suite)
    monkeypatch.setattr(httpx, "AsyncClient", Client)
    await command.run(SimpleNamespace(stage="installation", evidence=tmp_path / "evidence.json"))
    assert observed[0]["verify"] is settings.ssl_context and observed[0]["trust_env"] is False


async def test_same_explicit_ca_authenticates_loopback_https_and_websocket_and_wrong_ca_refuses(tmp_path, tls_material):
    """Real TLS/protocol smoke on loopback; not a deployed authorization claim."""
    import ssl
    from types import SimpleNamespace

    import httpx
    from websockets.asyncio.server import serve

    from test.e2e.helpers.vibe_runtime import LiveVibeSuite, build_tls_context

    server_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    server_context.load_cert_chain(tls_material["server"], tls_material["key"])

    async def request(connection, handshake):
        if handshake.path == "/health":
            return connection.respond(200, '{"status":"ok"}')
        if handshake.headers.get("Cookie") != "access_token_cookie=local-owner":
            return connection.respond(403, "refused")
        return None

    async def echo(connection):
        await connection.send(await connection.recv())

    async with serve(echo, "127.0.0.1", 0, ssl=server_context, process_request=request) as server:
        port = server.sockets[0].getsockname()[1]
        origin = f"https://127.0.0.1:{port}"
        context = build_tls_context(tls_material["ca"])
        settings = SuiteSettings("e2e-f059-tenant", (), ssl_context=context)
        journal = EvidenceJournal(tmp_path / "evidence.json", tenant_code=settings.tenant_code)
        async with httpx.AsyncClient(verify=context, trust_env=False) as client:
            assert (await client.get(origin + "/health")).json() == {"status": "ok"}
            suite = LiveVibeSuite(settings, journal, client)
            suite.tokens = {"OWNER": "local-owner", "NONOWNER": "local-nonowner"}
            scenario = SimpleNamespace(slug="e2e-f059-smoke", websocket_path="/ws")
            await suite.websocket(scenario, origin + "/apps/smoke")
        wrong = build_tls_context(tls_material["wrong-ca"])
        async with httpx.AsyncClient(verify=wrong, trust_env=False) as client:
            with pytest.raises(httpx.ConnectError):
                await client.get(origin + "/health")
            suite = LiveVibeSuite(SuiteSettings("e2e-f059-tenant", (), ssl_context=wrong), journal, client)
            suite.tokens = {"OWNER": "local-owner", "NONOWNER": "local-nonowner"}
            with pytest.raises(ssl.SSLCertVerificationError):
                await suite.websocket(scenario, origin + "/apps/smoke")
    assert "PRIVATE KEY" not in (tmp_path / "evidence.json").read_text()
    assert str(tls_material["key"]) not in (tmp_path / "evidence.json").read_text()


@pytest.mark.parametrize("event", ["manager-restart", "runtime-upgrade", "app-restart"])
async def test_fault_checkpoint_after_is_read_only_and_records_exact_observations(tmp_path, monkeypatch, event):
    """AC-33, AC-40, AC-55: checkpoint inspection cannot repair rows by rewriting them."""
    from types import SimpleNamespace

    import httpx

    from test.e2e.helpers.vibe_runtime import LiveVibeSuite

    monkeypatch.setenv("F059_E2E_ENTRY_BASE", "https://entry.invalid")
    scenario = SimpleNamespace(
        slug="e2e-f059-smoke", table="items", entry_path="/", expected_text="e2e-f059", expected_failure_code=None
    )
    settings = SuiteSettings("e2e-f059-tenant", (scenario,))
    journal = EvidenceJournal(tmp_path / "evidence.json", tenant_code=settings.tenant_code)
    journal.document["apps"][scenario.slug] = {"app_id": "app-1"}
    writes = []

    def transport(request):
        assert request.method == "GET"
        assert str(request.url) == "https://entry.invalid/apps/e2e-f059-smoke/"
        return httpx.Response(200, text="e2e-f059")

    async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as client:
        suite = LiveVibeSuite(settings, journal, client)
        suite.tokens["OWNER"] = "fixture-owner"
        suite.users["OWNER"], suite.tenant_id = 42, 7

        async def request(method, path, **kwargs):
            if method != "GET":
                writes.append((method, path))
                raise AssertionError("fault checkpoints cannot mutate app data")
            if path.endswith("/instance"):
                return {"instance_id": "instance-1"}
            if path.endswith("/rows"):
                return {"data": [{"id": 1, "value": "committed"}], "total": 1}
            return {
                "app_id": "app-1",
                "slug": scenario.slug,
                "name": scenario.slug,
                "tenant_id": 7,
                "owner_user_id": 42,
                "state": "online",
                "current_version_id": "version-1",
                "entry_url": "https://entry.invalid/apps/e2e-f059-smoke",
            }

        async def observe(*args):
            raise AssertionError("full observe performs SDK and database writes")

        suite.request, suite.observe = request, observe
        await suite.checkpoint(event)
        await suite.checkpoint(event, verify=True)
    assert writes == []
    fact = journal.document["events"][-1]
    assert fact["injection_verified"] is False
    assert fact["apps"][scenario.slug]["instance_id"] == "instance-1"
    assert fact["apps"][scenario.slug]["version_id"] == "version-1"


@pytest.mark.parametrize("invalid", ["missing", "expired", "scope"])
async def test_fault_checkpoint_rejects_invalid_baseline_before_any_network(tmp_path, invalid):
    """AC-55: an absent/expired or replaced checkpoint scope does not authorize requests."""
    import time
    from types import SimpleNamespace

    from test.e2e.helpers.vibe_runtime import LiveVibeSuite

    scenario = SimpleNamespace(slug="e2e-f059-smoke", expected_failure_code=None)
    settings = SuiteSettings("e2e-f059-tenant", (scenario,))
    journal = EvidenceJournal(tmp_path / "evidence.json", tenant_code=settings.tenant_code)
    journal.document["apps"][scenario.slug] = {"app_id": "app-1"}
    if invalid != "missing":
        journal.document["checkpoint:manager-restart"] = {
            "observed_at": time.time() - (1000 if invalid == "expired" else 0),
            "apps": {scenario.slug: {"app_id": "different-app" if invalid == "scope" else "app-1"}},
        }
    suite = LiveVibeSuite(settings, journal, None)

    async def request(*args, **kwargs):
        raise RuntimeError("invalid checkpoint made a network call")

    suite.request = request
    with pytest.raises((AssertionError, ValueError)):
        await suite.checkpoint("manager-restart", verify=True)


async def test_preview_exercises_real_entry_with_paired_denial_and_preserves_production_rows(tmp_path, monkeypatch):
    """AC-05, AC-36, AC-50: the trial is reached by its raiser and cannot change production data."""
    from types import SimpleNamespace

    import httpx

    from test.e2e.helpers.vibe_runtime import LiveVibeSuite

    monkeypatch.setenv("F059_E2E_ENTRY_BASE", "https://entry.invalid")
    settings = SuiteSettings("e2e-f059-tenant", ())
    journal = EvidenceJournal(tmp_path / "evidence.json", tenant_code=settings.tenant_code)
    seen, reads = [], []

    def transport(request):
        seen.append((request.url.path, request.headers["cookie"]))
        if request.headers["cookie"] == "access_token_cookie=fixture-approver":
            return httpx.Response(200, text="e2e-f059-preview")
        return httpx.Response(404, json={"status_code": 16144, "status_message": "not found", "data": None})

    async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as client:
        suite = LiveVibeSuite(settings, journal, client)
        suite.tokens = {role: "fixture-" + role.lower() for role in ["OWNER", "NONOWNER", "FOREIGN", "APPROVER"]}
        closed = False

        async def request(method, path, **kwargs):
            nonlocal closed
            if path == "/apps/app-1":
                return {
                    "app_id": "app-1",
                    "slug": "e2e-f059-smoke",
                    "name": "e2e-f059-smoke",
                    "tenant_id": 7,
                    "owner_user_id": 42,
                    "state": "online",
                }
            if path.endswith("/publish-status"):
                return {"approval": {"instance_id": "approval-1", "status": "pending"}}
            if path.endswith("/preview"):
                if kwargs.get("expected_code"):
                    assert kwargs["expected_code"] == 16264
                    return None
                return {
                    "session_id": "session-1",
                    "entry_url": "/apps/preview/session-1",
                    "state": "reclaimed" if closed else "running",
                }
            if method == "DELETE":
                closed = True
                return None
            if path == "/approval/my-tasks":
                return {"data": [{"task_id": "task-1", "instance_id": "approval-1", "status": "pending"}]}
            if path == "/approval/my-tasks/task-1":
                return {"status": "approved"}
            return None

        async def rows(scenario, app_id):
            reads.append(app_id)
            return {"data": [{"id": 1, "value": "production-value"}], "total": 1}

        suite.request, suite.rows = request, rows
        suite.users["OWNER"], suite.tenant_id = 42, 7
        scenario = SimpleNamespace(slug="e2e-f059-smoke", table="items", expected_text="e2e-f059")
        await suite.preview_and_approve({"app_id": "app-1", "version_id": "version-1"}, scenario)
    assert reads == ["app-1", "app-1"]
    assert seen == [
        ("/apps/preview/session-1/", "access_token_cookie=fixture-" + role)
        for role in ["approver", "owner", "nonowner", "foreign"]
    ]
    assert journal.document["events"][-1]["name"] == "preview-and-approval"


@pytest.mark.parametrize("change", ["rows", "version_id", "instance_id"])
async def test_fault_checkpoint_cannot_claim_recovery_when_durable_observations_changed(tmp_path, monkeypatch, change):
    """AC-33, AC-40, AC-55: a changed row/version/application instance leaves no PASS event."""
    import time
    from types import SimpleNamespace

    import httpx

    from test.e2e.helpers.vibe_runtime import LiveVibeSuite

    monkeypatch.setenv("F059_E2E_ENTRY_BASE", "https://entry.invalid")
    scenario = SimpleNamespace(
        slug="e2e-f059-smoke", table="items", entry_path="/", expected_text="e2e-f059", expected_failure_code=None
    )
    settings = SuiteSettings("e2e-f059-tenant", (scenario,))
    journal = EvidenceJournal(tmp_path / "evidence.json", tenant_code=settings.tenant_code)
    journal.document["apps"][scenario.slug] = {"app_id": "app-1"}
    baseline = {
        "app_id": "app-1",
        "version_id": "version-1",
        "instance_id": "instance-1",
        "rows": {"data": [{"id": 1, "value": "committed"}]},
    }
    journal.document["checkpoint:manager-restart"] = {"observed_at": time.time(), "apps": {scenario.slug: baseline}}
    current = {**baseline, change: {"data": []} if change == "rows" else "changed"}
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, text="e2e-f059"))
    ) as client:
        suite = LiveVibeSuite(settings, journal, client)
        suite.tokens["OWNER"] = "fixture-owner"
        suite.users["OWNER"], suite.tenant_id = 42, 7

        async def request(method, path, **kwargs):
            assert method == "GET"
            if path.endswith("/instance"):
                return {"instance_id": current["instance_id"]}
            if path.endswith("/rows"):
                return current["rows"]
            return {
                "app_id": "app-1",
                "slug": scenario.slug,
                "name": scenario.slug,
                "tenant_id": 7,
                "owner_user_id": 42,
                "state": "online",
                "current_version_id": current["version_id"],
                "entry_url": "https://entry.invalid/apps/e2e-f059-smoke",
            }

        suite.request = request
        with pytest.raises(AssertionError):
            await suite.checkpoint("manager-restart", verify=True)
    assert journal.document["events"] == []


@pytest.mark.parametrize(
    "entry",
    [
        "https://other.invalid/apps/preview/1",
        "//other.invalid/apps/preview/1",
        "https://entry.invalid@other.invalid/apps/preview/1",
        "/apps/preview/1?credential=not-allowed",
        "/apps/preview/1#unexpected",
    ],
)
def test_entry_evidence_never_sends_identity_to_an_unexpected_origin(monkeypatch, entry):
    """AC-12, AC-55: untrusted entry data cannot redirect a real user's cookie."""
    from test.e2e.helpers.vibe_runtime import LiveVibeSuite

    monkeypatch.setenv("F059_E2E_ENTRY_BASE", "https://entry.invalid")
    with pytest.raises(AssertionError):
        LiveVibeSuite.entry_url(entry)


async def test_pytest_live_fixture_uses_same_verified_tls_context_as_cli(tmp_path, monkeypatch):
    """AC-36, AC-55: pytest and CLI use the same explicit CA without disabling verification."""
    from test.e2e import test_e2e_vibe_k8s_runtime as live

    settings = SuiteSettings("e2e-f059-tenant", ())
    monkeypatch.setattr(live.SuiteSettings, "from_env", lambda: settings)
    monkeypatch.setenv("F059_E2E_EVIDENCE", str(tmp_path / "evidence.json"))
    observed, cleanup = [], []

    class Client:
        def __init__(self, **kwargs):
            observed.append(kwargs)

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

    class Suite:
        def __init__(self, actual_settings, journal, client):
            assert actual_settings is settings

        async def authenticate(self):
            return None

        async def installation(self):
            return None

        async def cleanup(self):
            cleanup.append(True)

    monkeypatch.setattr(live.httpx, "AsyncClient", Client)
    monkeypatch.setattr(live, "LiveVibeSuite", Suite)
    from types import SimpleNamespace

    fixture = live.TestE2EVibeKubernetesRuntime.suite.__wrapped__(None, SimpleNamespace(mktemp=lambda name: tmp_path))
    assert isinstance(await anext(fixture), Suite)
    with pytest.raises(StopAsyncIteration):
        await anext(fixture)
    assert observed[0]["verify"] is settings.ssl_context
    assert observed[0]["trust_env"] is False
    assert cleanup == [True, True]

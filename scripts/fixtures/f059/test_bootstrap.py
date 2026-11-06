"""Local fixture contracts only; these checks do not prove deployed F059 ACs.

Supports T066/T069 preparation. Real API permissions and deployed runtime
acceptance remain the operator's live E2E responsibility.
"""

from __future__ import annotations

import asyncio
import base64
import importlib.util
import json
import os
import secrets
import socket
import sqlite3
import struct
import sys
import tarfile
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path

import httpx
import pytest
import yaml

ROOT = Path(__file__).resolve().parents[3]
SPEC = importlib.util.spec_from_file_location("f059_bootstrap", ROOT / "scripts/bootstrap_f059_acceptance.py")
bootstrap = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(bootstrap)
sys.path[:0] = [str(ROOT / "src/backend"), str(ROOT / "src/bisheng-sdk")]


def inventory():
    names = ("app-python", "app-python-preparer", "app-node", "app-node-preparer", "app-static")
    return {
        "platform": "linux/amd64",
        "images": {
            name: {
                "image": f"registry.invalid/{name}@sha256:" + str(index) * 64,
                "image_id": "sha256:" + str(index + 1) * 64,
                "platform": "linux/amd64",
            }
            for index, name in enumerate(names, 1)
        },
    }


def environment(tmp_path):
    return bootstrap.prepare_environment(tmp_path / "e2e-f059-suite", base="http://127.0.0.1:7860/api/v1")


def test_prepare_is_local_private_stable_and_preserves_existing_admin(tmp_path, monkeypatch, capsys):
    source = tmp_path / "platform.env"
    password = secrets.token_urlsafe(24)
    bootstrap.private_write(source, "E2E_ADMIN_USERNAME=e2e-f059-admin\nE2E_ADMIN_PASSWORD=" + password + "\n")
    suite = tmp_path / "e2e-f059-acceptance"
    monkeypatch.setattr(bootstrap, "bootstrap", lambda *_args, **_kwargs: pytest.fail("unexpected API setup"))
    args = [
        "--api-base",
        "http://127.0.0.1:7860",
        "--suite-dir",
        str(suite),
        "--env-file",
        str(source),
        "--prepare-only",
    ]
    assert bootstrap.main(args) == 0
    values = bootstrap.read_env(suite / "e2e.env")
    assert values["E2E_ADMIN_PASSWORD"] == password
    assert values["E2E_ADMIN_USERNAME"] == "e2e-f059-admin"
    assert source.read_text().splitlines()[-1].endswith(password)
    assert bootstrap.main(args) == 0
    assert bootstrap.read_env(suite / "e2e.env") == values
    assert (suite / "e2e.env").stat().st_mode & 0o777 == 0o600
    assert (suite / "environment-marker.json").stat().st_mode & 0o777 == 0o600
    output = capsys.readouterr().out
    assert password not in output
    assert all(values[f"F059_E2E_{role}_PASSWORD"] not in output for role in bootstrap.ROLES)
    assert '"api_bootstrap_executed": false' in output


def test_platform_env_allowlist_ignores_docker_config_but_keeps_admin_values(tmp_path):
    source = tmp_path / "platform.env"
    sentinel = tmp_path / "must-not-be-created"
    password = secrets.token_urlsafe(16) + "$(touch " + str(sentinel) + ")"
    import shlex

    content = (
        'config={"nested": {"arbitrary": "Docker env value with spaces"}}\n'
        + "LOWER_LEVEL_JSON={not shell syntax with spaces\n"
        + "unknown Docker env syntax\n"
        + "E2E_ADMIN_USERNAME=e2e-f059-admin\n"
        + "export E2E_ADMIN_PASSWORD="
        + shlex.quote(password)
        + "\n"
        + "F059_E2E_OWNER_API_KEY=not-to-be-inherited\n"
    )
    bootstrap.private_write(source, content)
    suite, output, values = bootstrap.prepare_environment(
        tmp_path / "e2e-f059-suite", base="http://127.0.0.1/api/v1", input_env=source
    )
    assert values["E2E_ADMIN_USERNAME"] == "e2e-f059-admin"
    assert values["E2E_ADMIN_PASSWORD"] == password
    assert "F059_E2E_OWNER_API_KEY" not in values
    assert bootstrap.read_env(output)["E2E_ADMIN_PASSWORD"] == password
    assert not sentinel.exists()
    assert source.read_text() == content
    assert suite.is_dir()
    with pytest.raises(bootstrap.BootstrapError, match="env_file_invalid"):
        bootstrap.read_env(source)


@pytest.mark.parametrize(
    "lines,reason",
    [
        ("E2E_ADMIN_PASSWORD=one\nE2E_ADMIN_PASSWORD=one\n", "env_duplicate_key"),
        ("E2E_ADMIN_PASSWORD=two words\n", "env_value_not_a_scalar"),
        ("E2E_ADMIN_PASSWORD='unclosed\n", "env_value_not_a_scalar"),
        ("E2E_ADMIN_PASSWORD\n", "env_file_invalid"),
        ("E2E_ADMIN_PASSWORD =value\n", "env_file_invalid"),
    ],
)
def test_selected_platform_env_values_still_validate(tmp_path, lines, reason):
    source = tmp_path / "platform.env"
    bootstrap.private_write(source, "config=ignored spaces and JSON\n" + lines)
    with pytest.raises(bootstrap.BootstrapError, match=reason):
        bootstrap.read_env(source, allowlist={"E2E_ADMIN_PASSWORD"})


def test_allowlisted_env_still_requires_private_file_and_strict_output_refuses_duplicates(tmp_path):
    source = tmp_path / "platform.env"
    bootstrap.private_write(source, "config=ignored\nE2E_ADMIN_PASSWORD=value\n")
    source.chmod(0o644)
    with pytest.raises(bootstrap.BootstrapError, match="private_file"):
        bootstrap.read_env(source, allowlist={"E2E_ADMIN_PASSWORD"})
    source.chmod(0o600)
    bootstrap.private_write(source, "E2E_ADMIN_PASSWORD=value\nE2E_ADMIN_PASSWORD=value\n")
    with pytest.raises(bootstrap.BootstrapError, match="env_duplicate_key"):
        bootstrap.read_env(source)


@pytest.mark.parametrize(
    "address", ["https://example.com", "http://8.8.8.8", "http://user:secret@127.0.0.1", "http://127.0.0.1?key=secret"]
)
def test_public_or_credential_bearing_api_refused(address):
    with pytest.raises(bootstrap.BootstrapError):
        bootstrap.api_base(address)


def test_dedicated_path_private_input_and_output_guards(tmp_path):
    with pytest.raises(bootstrap.BootstrapError, match="dedicated_suite"):
        bootstrap.prepare_environment(tmp_path / "production", base="http://127.0.0.1/api/v1")
    source = tmp_path / "input.env"
    source.write_text("E2E_ADMIN_USERNAME=e2e-f059-admin\n")
    source.chmod(0o644)
    with pytest.raises(bootstrap.BootstrapError, match="private_file"):
        bootstrap.read_env(source)
    source.chmod(0o600)
    with pytest.raises(bootstrap.BootstrapError, match="must_not_be_overwritten"):
        bootstrap.prepare_environment(
            tmp_path / "e2e-f059-suite", base="http://127.0.0.1/api/v1", input_env=source, output_env=source
        )
    target = tmp_path / "target"
    target.symlink_to(source)
    with pytest.raises(bootstrap.BootstrapError, match="link_refused"):
        bootstrap.private_write(target, "replacement")
    assert source.read_text().startswith("E2E_ADMIN_USERNAME=")


def test_marker_and_admin_mismatch_refuse_reuse(tmp_path):
    suite, output, values = environment(tmp_path)
    source = tmp_path / "changed.env"
    bootstrap.private_write(source, "E2E_ADMIN_PASSWORD=" + secrets.token_urlsafe(16) + "\n")
    with pytest.raises(bootstrap.BootstrapError, match="credential_mismatch"):
        bootstrap.prepare_environment(suite, base=values["E2E_API_BASE"], input_env=source)
    with pytest.raises(bootstrap.BootstrapError, match="marker_mismatch"):
        bootstrap.prepare_environment(suite, base="http://127.0.0.2/api/v1")
    assert bootstrap.read_env(output) == values


@pytest.mark.parametrize("profile_revision", [1, 2])
def test_custom_amd64_profiles_and_five_package_modes_match_real_schemas(tmp_path, monkeypatch, profile_revision):
    from test.e2e.helpers.vibe_runtime import Scenario

    from bisheng.app_publish.domain.schemas.app_manifest import AppManifest
    from bisheng.app_runtime.domain.schemas.runtime_delivery import RuntimeProfileDefinition

    suite, _output, values = environment(tmp_path)
    profiles, scenarios = bootstrap.build_packages(
        suite,
        values,
        inventory=inventory(),
        demo_image="registry.invalid/demo@sha256:" + "a" * 64,
        demo_image_v2="registry.invalid/demo@sha256:" + "b" * 64,
        model_name="acceptance-model",
        knowledge_ids=[37],
        profile_revision=profile_revision,
    )
    assert len(scenarios) == 6
    for profile in profiles:
        validated = RuntimeProfileDefinition.model_validate(profile)
        assert validated.official is False
        assert validated.revision == profile_revision
        assert set(validated.platforms) == {"linux/amd64"}
    for raw in scenarios:
        scenario = Scenario.from_dict(raw)
        for path in [scenario.package, scenario.update]:
            if path is None:
                continue
            with tarfile.open(path) as package:
                manifest = AppManifest.model_validate(yaml.safe_load(package.extractfile("bisheng-app.yaml")))
                assert manifest.slug == scenario.slug
                if scenario.mode == "bundle":
                    assert manifest.delivery.profile.endswith("@" + str(profile_revision))
                elif scenario.mode == "source-image":
                    assert "profile" not in manifest.delivery.model_dump()
                assert all(member.isfile() and member.name[0] != "/" for member in package.getmembers())
        if scenario.runtime == "python3.11" and scenario.expected_failure_code is None:
            assert {check["path"] for check in scenario.application_checks} >= {
                "/sdk/identity",
                "/sdk/storage-roundtrip",
                "/sdk/model",
                "/sdk/retrieve",
            }
    negative = scenarios[-1]
    assert negative["expected_failure_code"] == 16227 and "update" not in negative
    assert (suite / "demo-image-v1/main.py").is_file()
    assert (suite / "demo-image-v2/fixture-version.txt").read_text() == "2"
    assert values["F059_E2E_SCENARIOS"] == str(suite / "scenarios.json")


@pytest.mark.parametrize("mutation", ["platform", "tag", "image_id", "image_arch"])
def test_unfrozen_or_wrong_platform_profile_refused(mutation):
    data = inventory()
    if mutation == "platform":
        data["platform"] = "linux/arm64"
    elif mutation == "tag":
        data["images"]["app-python"]["image"] = "registry.invalid/python:latest"
    elif mutation == "image_id":
        data["images"]["app-python"]["image_id"] = "missing"
    else:
        data["images"]["app-python"]["platform"] = "linux/arm64"
    with pytest.raises(bootstrap.BootstrapError):
        bootstrap.profile_definitions(data)


class FixtureApi:
    """Strict contract double: deliberately not counted as platform proof."""

    calls = []
    non_test_user = False
    invalid_routes = False
    wrong_tenant = False
    approver_already_admin = False
    admin_list_error = False
    values = {}

    def __init__(self, base, client):
        self.base, self.client = base, client
        self.users = [{"user_id": 1, "user_name": self.values["E2E_ADMIN_USERNAME"]}]
        if self.non_test_user:
            self.users.append({"user_id": 80, "user_name": "ordinary-person"})
        self.departments = []
        self.tenants = [{"id": 1, "tenant_code": "default"}]

    async def encrypted(self, _password):
        return "test-rsa-ciphertext"

    async def login(self, role, username, _password):
        user_id = 1 if role == "ADMIN" else list(bootstrap.ROLES).index(role) + 2
        return {"user_id": user_id, "user_name": username, "is_global_super": role == "ADMIN"}

    async def request(self, method, path, *, role="ADMIN", **kwargs):
        self.calls.append((method, path, role, kwargs))
        body = kwargs.get("json", {})
        if (method, path) == ("GET", "/user/list"):
            return {"data": self.users}
        if (method, path) == ("GET", "/tenants/"):
            return {"data": self.tenants}
        if (method, path) == ("GET", "/apps"):
            return []
        if (method, path) == ("GET", "/departments/children"):
            return self.departments if "parent_id" in kwargs.get("params", {}) else [{"id": 1, "dept_id": "BS@root"}]
        if (method, path) == ("POST", "/departments/"):
            row = {"id": len(self.departments) + 10, "dept_id": "BS@test" + str(len(self.departments)), **body}
            self.departments.append(row)
            return row
        if method == "POST" and path.endswith("/mount-tenant"):
            assert path.split("/")[-2].isdigit(), "mount API requires internal integer id"
            tenant = {"id": len(self.tenants) + 1, **body}
            self.tenants.append(tenant)
            return tenant
        if method == "GET" and path.endswith("/assignable-roles"):
            return [{"id": 2}]
        if (method, path) == ("POST", "/departments/local-members"):
            assert body["dept_id"].startswith("BS@test")
            assert body["person_id"] == body["user_name"]
            user = {"user_id": len(self.users) + 1, **body}
            self.users.append(user)
            return user
        if (method, path) == ("GET", "/user/current-tenant"):
            return {"leaf_tenant_id": 1 if self.wrong_tenant else (3 if role == "FOREIGN" else 2)}
        if method == "GET" and path == "/tenants/2/admins":
            if self.admin_list_error:
                raise bootstrap.BootstrapError("api_refused_admin_list")
            return {"user_ids": [5] if self.approver_already_admin else []}
        if method == "POST" and path == "/tenants/2/admins":
            assert body == {"user_id": 5}
            return {}
        if (method, path) == ("GET", "/approval/admin/scenarios"):
            return [{"id": 7, "scenario_code": "app_publish_request", "enabled": True}]
        if (method, path) == ("GET", "/approval/admin/scenarios/7/routes"):
            rows = [{"id": 9, "route_type": "flow", "enabled": True, "flow_definition_id": 8, "match_config": {}}]
            return rows + ([{"id": 11, "route_type": "pass", "enabled": True}] if self.invalid_routes else [])
        if (method, path) == ("PUT", "/approval/admin/flows/8/nodes"):
            assert role == "APPROVER"
            assert body["nodes"][0]["approver_config"] == {"sources": [{"type": "direct_user", "user_ids": [5]}]}
            return body
        if (method, path) == ("GET", "/service-accounts"):
            return {"data": []}
        if (method, path) == ("POST", "/service-accounts"):
            assert role == "APPROVER" and body["resource_owner_user_id"] == 2
            return {"id": 42}
        if (method, path) == ("POST", "/service-accounts/42/keys"):
            assert body["scopes"] == ["app:manage"]
            return {"plaintext": "test-fixture-private-key"}
        if (method, path) == ("POST", "/runtime/profiles"):
            return {"id": body["code"] + "@" + str(body["revision"])}
        if (method, path) == ("GET", "/runtime/profiles/defaults"):
            return []
        if (method, path) == ("PUT", "/runtime/profiles/default"):
            assert body["expected_generation"] == 0
            return body
        raise AssertionError((method, path))


async def run_setup(tmp_path, monkeypatch, **flags):
    suite, output, values = environment(tmp_path)
    FixtureApi.calls = []
    FixtureApi.values = values
    for name in ("non_test_user", "invalid_routes", "wrong_tenant", "approver_already_admin", "admin_list_error"):
        monkeypatch.setattr(FixtureApi, name, flags.get(name, False))
    monkeypatch.setattr(bootstrap, "Api", FixtureApi)

    def identity(request):
        assert request.url.path == "/api/v2/auth/whoami"
        assert request.headers["authorization"] == "Bearer test-fixture-private-key"
        return httpx.Response(
            200,
            json={"data": {"mode": "S", "scopes": ["app:manage"], "resource_owner": {"user_id": 2}, "tenant_id": 2}},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(identity)) as client:
        return await bootstrap.bootstrap(
            values["E2E_API_BASE"],
            suite,
            output,
            values,
            profiles=bootstrap.profile_definitions(inventory(), revision=flags.get("profile_revision", 1)),
            client=client,
        ), suite


def test_api_setup_uses_department_tenants_natural_users_manual_approval_and_mode_s(tmp_path, monkeypatch):
    state, suite = asyncio.run(run_setup(tmp_path, monkeypatch))
    assert state["complete"] is True
    assert state["tenants"]["OWNER"]["id"] == 2 and state["tenants"]["FOREIGN"]["id"] == 3
    assert state["approval"]["manual"] is True
    assert len(state["profiles"]) == 3
    assert all(not row["official"] for row in state["profiles"])
    assert "test-fixture-private-key" not in (suite / "bootstrap-state.json").read_text()
    assert bootstrap.read_env(suite / "e2e.env")["F059_E2E_OWNER_API_KEY"] == "test-fixture-private-key"
    assert not any(
        method == "POST" and path in {"/tenants/", "/user/create", "/user/regist"}
        for method, path, *_ in FixtureApi.calls
    )


@pytest.mark.parametrize(
    "flag, reason",
    [
        ("non_test_user", "non_test_or_unbounded"),
        ("invalid_routes", "manual_publish_route"),
        ("wrong_tenant", "tenant_scope_mismatch"),
    ],
)
def test_api_setup_refuses_unsafe_inventory_or_permissions(tmp_path, monkeypatch, flag, reason):
    with pytest.raises(bootstrap.BootstrapError, match=reason):
        asyncio.run(run_setup(tmp_path, monkeypatch, **{flag: True}))
    if flag == "non_test_user":
        assert not any(method != "GET" for method, *_ in FixtureApi.calls)
    assert not any(path == "/service-accounts" and method == "POST" for method, path, *_ in FixtureApi.calls)


def test_api_client_encrypts_real_rsa_and_never_uses_password_fallback():
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import padding, rsa

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    password, token = secrets.token_urlsafe(16), secrets.token_urlsafe(24)

    def respond(request):
        if request.url.path.endswith("/public_key"):
            data = {
                "public_key": key.public_key()
                .public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
                .decode()
            }
        elif request.url.path.endswith("/login"):
            body = json.loads(request.content)
            assert key.decrypt(base64.b64decode(body["password"]), padding.PKCS1v15()).decode() == password
            assert body["user_name"] == "e2e-f059-admin"
            data = {"access_token": token}
        else:
            assert request.headers["cookie"] == "access_token_cookie=" + token
            data = {"user_id": 1}
        return httpx.Response(200, json={"status_code": 200, "data": data})

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            return await bootstrap.Api("http://127.0.0.1/api/v1", client).login("ADMIN", "e2e-f059-admin", password)

    assert asyncio.run(run()) == {"user_id": 1}


def test_python_demo_real_sqlite_sdk_local_attachment_and_websocket(tmp_path, monkeypatch):
    """Local protocol smoke; no claim of platform authorization or MinIO proof."""
    application = tmp_path / "main.py"
    application.write_text((ROOT / "scripts/fixtures/f059/python_demo.py").read_text())
    (tmp_path / "fixture-version.txt").write_text("1")
    (tmp_path / "capabilities.json").write_text("{}")
    monkeypatch.setenv("BISHENG_APP_DB_PATH", str(tmp_path / "data/app.db"))
    monkeypatch.setenv("BISHENG_APP_STORAGE_DIR", str(tmp_path / "attachments"))
    monkeypatch.delenv("BISHENG_APP_STORAGE_ENDPOINT", raising=False)
    monkeypatch.setenv("BISHENG_APP_ID", "e2e-f059-app")
    spec = importlib.util.spec_from_file_location("f059_demo", application)
    demo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(demo)
    demo.initialize()
    server = ThreadingHTTPServer(("127.0.0.1", 0), demo.Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_port
    headers = {
        "X-BiSheng-User-Id": "2",
        "X-BiSheng-Subject-Kind": "human",
        "X-BiSheng-App-Id": "e2e-f059-app",
        "X-BiSheng-Access-Token": "test-visitor-handle",
    }
    try:
        with httpx.Client(base_url=f"http://127.0.0.1:{port}", trust_env=False, timeout=5) as client:
            assert client.get("/health").json()["version"] == "1"
            assert client.get("/items").json()["items"] == [{"id": 1, "value": "initial"}]
            with sqlite3.connect(demo.DATABASE) as db:
                db.execute("UPDATE items SET value='persisted' WHERE id=1")
            demo.initialize()
            assert client.get("/items").json()["items"] == [{"id": 1, "value": "persisted"}]
            assert client.get("/sdk/identity").status_code == 502
            assert client.get("/sdk/identity", headers=headers).json() == {
                "subject_kind": "human",
                "app_id_matches": True,
                "obo_present": True,
            }
            assert client.get("/sdk/storage-roundtrip", headers=headers).json()["storage_roundtrip"] is True
            assert client.get("/sdk/model", headers=headers).status_code == 409
            assert client.get("/sdk/retrieve", headers=headers).status_code == 409
        with socket.create_connection(("127.0.0.1", port), timeout=5) as stream:
            key = base64.b64encode(os.urandom(16)).decode()
            request = (
                "GET /ws HTTP/1.1\r\nHost: localhost\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Version: 13\r\nSec-WebSocket-Key: "
                + key
                + "\r\n"
                + "".join(name + ": " + value + "\r\n" for name, value in headers.items())
                + "\r\n"
            )
            stream.sendall(request.encode())
            reader = stream.makefile("rb")
            assert reader.readline().startswith(b"HTTP/1.1 101")
            while reader.readline() != b"\r\n":
                pass
            payload, mask = b"e2e-f059 websocket", os.urandom(4)
            stream.sendall(
                bytes([129, 128 | len(payload)])
                + mask
                + bytes(value ^ mask[index % 4] for index, value in enumerate(payload))
            )
            assert reader.read(2) == bytes([129, len(payload)])
            assert reader.read(len(payload)) == payload
            stream.sendall(bytes([136, 128]) + os.urandom(4))
            assert reader.read(2) == struct.pack("BB", 136, 0)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(5)


@pytest.mark.parametrize("value", [0, -1, True, "2", 1.5])
def test_profile_revision_must_be_a_positive_integer(value):
    with pytest.raises(bootstrap.BootstrapError, match="profile_revision_invalid"):
        bootstrap.profile_definitions(inventory(), revision=value)


def test_revision_defaults_to_one_and_cli_generates_revision_two_without_implicit_increment(tmp_path, capsys):
    assert {row["revision"] for row in bootstrap.profile_definitions(inventory())} == {1}
    source = tmp_path / "inventory.json"
    source.write_text(json.dumps(inventory()))
    suite = tmp_path / "e2e-f059-suite"
    arguments = [
        "--api-base",
        "http://127.0.0.1",
        "--suite-dir",
        str(suite),
        "--profile-inventory",
        str(source),
        "--profile-revision",
        "2",
        "--prepare-only",
    ]
    assert bootstrap.main(arguments) == 0
    definitions = json.loads((suite / "profiles.json").read_text())
    assert {row["revision"] for row in definitions} == {2}
    assert bootstrap.main(arguments) == 0
    assert json.loads((suite / "profiles.json").read_text()) == definitions
    with tarfile.open(suite / "e2e-f059-python-bundle-v1.tar.gz") as archive:
        assert yaml.safe_load(archive.extractfile("bisheng-app.yaml"))["delivery"]["profile"] == "e2e-f059-python311@2"
    assert capsys.readouterr().err == ""


def test_api_import_and_defaults_use_selected_revision_two(tmp_path, monkeypatch):
    state, _suite = asyncio.run(run_setup(tmp_path, monkeypatch, profile_revision=2))
    imports = [
        kwargs["json"]
        for method, path, role, kwargs in FixtureApi.calls
        if method == "POST" and path == "/runtime/profiles"
    ]
    defaults = [
        kwargs["json"]["profile_id"]
        for method, path, role, kwargs in FixtureApi.calls
        if method == "PUT" and path == "/runtime/profiles/default"
    ]
    assert len(imports) == len(defaults) == 3
    assert {row["revision"] for row in imports} == {2}
    assert all(reference.endswith("@2") for reference in defaults)
    assert {row["revision"] for row in state["profiles"]} == {2}


def test_profile_immutable_conflict_is_not_retried_as_override(tmp_path, monkeypatch):
    original = FixtureApi.request

    def conflicting_api(self, method, path, **kwargs):
        if method == "POST" and path == "/runtime/profiles":
            FixtureApi.calls.append((method, path, kwargs.get("role", "ADMIN"), kwargs))
            raise bootstrap.BootstrapError("api_refused_profile_immutable_conflict")
        return original(self, method, path, **kwargs)

    async def conflict(self, method, path, **kwargs):
        return await conflicting_api(self, method, path, **kwargs)

    monkeypatch.setattr(FixtureApi, "request", conflict)
    with pytest.raises(bootstrap.BootstrapError, match="profile_immutable_conflict"):
        asyncio.run(run_setup(tmp_path, monkeypatch, profile_revision=2))
    assert sum(method == "POST" and path == "/runtime/profiles" for method, path, role, kwargs in FixtureApi.calls) == 1
    assert not any(
        method == "PUT" and path == "/runtime/profiles/default" for method, path, role, kwargs in FixtureApi.calls
    )


@pytest.mark.parametrize("already_granted", [False, True])
def test_bootstrap_queries_admin_grants_and_only_adds_missing_approver(tmp_path, monkeypatch, already_granted):
    state, _suite = asyncio.run(run_setup(tmp_path, monkeypatch, approver_already_admin=already_granted))
    calls = [
        (method, kwargs.get("json")) for method, path, role, kwargs in FixtureApi.calls if path == "/tenants/2/admins"
    ]
    expected = [("GET", None)] if already_granted else [("GET", None), ("POST", {"user_id": 5})]
    assert calls == expected
    assert state["complete"] is True
    assert len(state["profiles"]) == 3 and state["approval"]["manual"] is True


def test_admin_list_failure_is_not_ignored_or_followed_by_grant(tmp_path, monkeypatch):
    with pytest.raises(bootstrap.BootstrapError, match="api_refused_admin_list"):
        asyncio.run(run_setup(tmp_path, monkeypatch, admin_list_error=True))
    assert any(method == "GET" and path == "/tenants/2/admins" for method, path, role, kwargs in FixtureApi.calls)
    assert not any(method == "POST" and path == "/tenants/2/admins" for method, path, role, kwargs in FixtureApi.calls)
    assert not any(path.startswith("/approval/") for method, path, role, kwargs in FixtureApi.calls)


@pytest.mark.parametrize("suffix", ["r2", "batch-03", "a" * 16])
def test_application_suffix_builds_unique_valid_packages_without_changing_profiles(tmp_path, suffix):
    """AC-01, AC-28: Repeated suites use distinct immutable application slugs."""
    from test.e2e.helpers.vibe_runtime import Scenario

    from bisheng.app_publish.domain.schemas.app_manifest import AppManifest

    suite, _output, values = bootstrap.prepare_environment(
        tmp_path / "e2e-f059-batch",
        base="http://127.0.0.1/api/v1",
        application_suffix=suffix,
    )
    profiles, scenarios = bootstrap.build_packages(
        suite,
        values,
        inventory=inventory(),
        demo_image="registry.invalid/demo@sha256:" + "a" * 64,
    )
    assert profiles == bootstrap.profile_definitions(inventory())
    assert len(scenarios) == 6
    for raw in scenarios:
        scenario = Scenario.from_dict(raw)
        assert scenario.slug.startswith(bootstrap.PREFIX) and scenario.slug.endswith("-" + suffix)
        assert len(scenario.slug) <= 64
        for path in (scenario.package, scenario.update):
            if path is None:
                continue
            assert path.name.startswith(scenario.slug + "-v")
            with tarfile.open(path) as package:
                manifest = AppManifest.model_validate(yaml.safe_load(package.extractfile("bisheng-app.yaml")))
                assert manifest.slug == manifest.name == scenario.slug
                if scenario.runtime == "node20":
                    assert json.load(package.extractfile("package.json"))["name"] == scenario.slug
                    lock = json.load(package.extractfile("package-lock.json"))
                    assert lock["name"] == lock["packages"][""]["name"] == scenario.slug
    assert json.loads((suite / "environment-marker.json").read_text())["application_suffix"] == suffix


@pytest.mark.parametrize("suffix", ["", "R2", "r_2", "-r2", "r2-", "r--2", "r/2", "a" * 17, 2])
def test_application_suffix_rejects_invalid_values_before_creating_suite(tmp_path, suffix):
    suite = tmp_path / "e2e-f059-invalid"
    with pytest.raises(bootstrap.BootstrapError, match="application_suffix_invalid"):
        bootstrap.prepare_environment(suite, base="http://127.0.0.1/api/v1", application_suffix=suffix)
    assert not suite.exists()


def test_application_slug_enforces_final_length_even_with_valid_suffix(monkeypatch):
    monkeypatch.setattr(bootstrap, "PREFIX", "e2e-f059-" + "x" * 47 + "-")
    with pytest.raises(bootstrap.BootstrapError, match="application_slug_invalid"):
        bootstrap.application_slug("python-bundle", "r2")


@pytest.mark.parametrize("initial,changed", [(None, "r2"), ("r2", None), ("r2", "r3")])
def test_existing_batch_rejects_suffix_changes_without_overwriting_files(tmp_path, initial, changed):
    suite, output, values = bootstrap.prepare_environment(
        tmp_path / "e2e-f059-batch",
        base="http://127.0.0.1/api/v1",
        application_suffix=initial,
    )
    bootstrap.private_write(suite / "scenarios.json", "old-batch-evidence")
    before = {path.name: path.read_bytes() for path in suite.iterdir()}
    with pytest.raises(bootstrap.BootstrapError, match="existing_application_suffix_mismatch"):
        bootstrap.prepare_environment(suite, base=values["E2E_API_BASE"], application_suffix=changed)
    assert {path.name: path.read_bytes() for path in suite.iterdir()} == before
    assert bootstrap.read_env(output) == values


def test_suffix_marker_env_disagreement_is_rejected_without_repair(tmp_path):
    suite, output, values = bootstrap.prepare_environment(
        tmp_path / "e2e-f059-batch",
        base="http://127.0.0.1/api/v1",
        application_suffix="r2",
    )
    values["F059_E2E_APPLICATION_SUFFIX"] = "r3"
    bootstrap.save_env(output, values)
    before = {path.name: path.read_bytes() for path in suite.iterdir()}
    with pytest.raises(bootstrap.BootstrapError, match="existing_application_suffix_mismatch"):
        bootstrap.prepare_environment(suite, base=values["E2E_API_BASE"], application_suffix="r2")
    assert {path.name: path.read_bytes() for path in suite.iterdir()} == before


def test_suffix_prepare_then_bootstrap_reuses_credentials_and_keeps_old_batch(tmp_path, monkeypatch, capsys):
    old, old_output, old_values = environment(tmp_path)
    old_values["F059_E2E_OWNER_API_KEY"] = secrets.token_urlsafe(32)
    bootstrap.save_env(old_output, old_values)
    old_before = {path.name: path.read_bytes() for path in old.iterdir()}
    new = tmp_path / "e2e-f059-r2"
    copied = {
        key: value
        for key, value in old_values.items()
        if key
        not in {
            "F059_ACCEPTANCE_INSTANCE",
            "F059_E2E_SCENARIOS",
            "F059_E2E_APPLICATION_SUFFIX",
        }
    }
    bootstrap.save_env(new / "e2e.env", copied)
    source = tmp_path / "inventory.json"
    source.write_text(json.dumps(inventory()))
    arguments = [
        "--api-base",
        old_values["E2E_API_BASE"],
        "--suite-dir",
        str(new),
        "--profile-inventory",
        str(source),
        "--application-suffix",
        "r2",
    ]
    assert bootstrap.main([*arguments, "--prepare-only"]) == 0
    prepared = bootstrap.read_env(new / "e2e.env")
    assert prepared["F059_ACCEPTANCE_INSTANCE"] != old_values["F059_ACCEPTANCE_INSTANCE"]
    assert prepared["F059_E2E_APPLICATION_SUFFIX"] == "r2"
    for key, value in copied.items():
        if key != "F059_E2E_SCENARIOS":
            assert prepared[key] == value
    observed = []

    async def capture(base, suite, output, values, **kwargs):
        observed.append(values.copy())
        assert not kwargs["register_first"]

    monkeypatch.setattr(bootstrap, "bootstrap", capture)
    assert bootstrap.main([*arguments, "--bootstrap"]) == 0
    assert observed == [prepared]
    assert bootstrap.read_env(new / "e2e.env") == prepared
    assert {path.name: path.read_bytes() for path in old.iterdir()} == old_before
    output = capsys.readouterr().out
    assert old_values["F059_E2E_OWNER_API_KEY"] not in output
    assert all(old_values[f"F059_E2E_{role}_PASSWORD"] not in output for role in bootstrap.ROLES)


def test_legacy_default_batch_stays_compatible_and_cannot_be_relabelled(tmp_path):
    suite, output, values = environment(tmp_path)
    marker_path = suite / "environment-marker.json"
    marker = json.loads(marker_path.read_text())
    marker.pop("application_suffix")
    values.pop("F059_E2E_APPLICATION_SUFFIX")
    bootstrap.private_write(marker_path, json.dumps(marker))
    bootstrap.save_env(output, values)
    before = {path.name: path.read_bytes() for path in suite.iterdir()}
    with pytest.raises(bootstrap.BootstrapError, match="existing_application_suffix_mismatch"):
        bootstrap.prepare_environment(suite, base=values["E2E_API_BASE"], application_suffix="r2")
    assert {path.name: path.read_bytes() for path in suite.iterdir()} == before
    _, _, resumed = bootstrap.prepare_environment(suite, base=values["E2E_API_BASE"])
    assert resumed["F059_ACCEPTANCE_INSTANCE"] == values["F059_ACCEPTANCE_INSTANCE"]
    assert resumed["F059_E2E_APPLICATION_SUFFIX"] == ""


def test_bootstrap_rejects_env_marker_batch_disagreement_before_api(tmp_path, monkeypatch):
    suite, output, values = bootstrap.prepare_environment(
        tmp_path / "e2e-f059-batch",
        base="http://127.0.0.1/api/v1",
        application_suffix="r2",
    )
    values["F059_E2E_APPLICATION_SUFFIX"] = "r3"
    monkeypatch.setattr(bootstrap, "Api", lambda *_: pytest.fail("unexpected API construction"))
    with pytest.raises(bootstrap.BootstrapError, match="environment_marker_mismatch"):
        asyncio.run(
            bootstrap.bootstrap(
                values["E2E_API_BASE"],
                suite,
                output,
                values,
                profiles=[],
                client=object(),
            )
        )


# T191 — 覆盖 AC: AC-04、AC-24、AC-36、AC-46、AC-55
VENDOR_VERSIONS = {
    "bisheng-sdk": "0.1.1",
    "httpx": "0.28.1",
    "httpcore": "1.0.9",
    "h11": "0.16.0",
    "anyio": "4.15.1",
    "idna": "3.20",
    "certifi": "2026.10.19",
    "typing-extensions": "4.16.0",
}


def vendor_wheelhouse(tmp_path):
    import hashlib
    import zipfile

    directory = tmp_path / "source-wheelhouse"
    (directory / "wheels").mkdir(parents=True)
    wheels = {}
    for name, version in VENDOR_VERSIONS.items():
        normalized = name.replace("-", "_")
        filename = normalized + "-" + version + "-py3-none-any.whl"
        path = directory / "wheels" / filename
        if name == "bisheng-sdk":
            path.write_bytes((ROOT / "src/backend/bisheng/dev_toolkit/artifacts" / filename).read_bytes())
        else:
            metadata = normalized + "-" + version + ".dist-info/"
            with zipfile.ZipFile(path, "w") as wheel:
                wheel.writestr(normalized + "/__init__.py", "# Contract fixture, not runtime dependency evidence.\n")
                wheel.writestr(metadata + "METADATA", f"Metadata-Version: 2.1\nName: {name}\nVersion: {version}\n")
                wheel.writestr(metadata + "WHEEL", "Wheel-Version: 1.0\nRoot-Is-Purelib: true\nTag: py3-none-any\n")
                wheel.writestr(metadata + "licenses/LICENSE", "Dedicated contract license fixture\n")
        wheels["wheels/" + filename] = "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()
    (directory / "source-vendor.json").write_text(
        json.dumps({"format": "f059-source-wheelhouse-v1", "python": "3.11", "wheels": wheels})
    )
    return directory


def mutate_vendor_wheel(directory, member, *, symlink=False):
    import hashlib
    import zipfile

    path = directory / "wheels/httpx-0.28.1-py3-none-any.whl"
    with zipfile.ZipFile(path, "a") as wheel:
        information = zipfile.ZipInfo(member)
        information.external_attr = (0o120777 if symlink else 0o100644) << 16
        wheel.writestr(information, "outside" if symlink else "unexpected material")
    manifest_path = directory / "source-vendor.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["wheels"]["wheels/" + path.name] = "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()
    manifest_path.write_text(json.dumps(manifest))


def test_source_image_explicit_vendor_preserves_sdk_checks_licenses_and_other_modes(tmp_path, monkeypatch):
    materials = vendor_wheelhouse(tmp_path)
    suite, _output, values = environment(tmp_path)
    # Packaging untrusted input must never import dependency code, install, or call APIs.
    monkeypatch.setattr(httpx, "request", lambda *a, **kw: pytest.fail("network during local packaging"))
    _profiles, scenarios = bootstrap.build_packages(suite, values, inventory=inventory(), source_wheelhouse=materials)
    source = next(item for item in scenarios if item["mode"] == "source-image")
    assert source["source_dependencies"] == "explicit-vendored-wheelhouse"
    assert {item["path"] for item in source["application_checks"]} >= {"/sdk/identity", "/sdk/storage-roundtrip"}
    manifests = []
    for key in ("package", "update"):
        with tarfile.open(source[key]) as package:
            main = package.extractfile("main.py").read().decode()
            compile(main, "main.py", "exec")
            assert main.index("sys.path[:0]") < main.index("from bisheng_sdk import")
            assert package.extractfile("requirements.txt").read() == b""
            assert package.extractfile("_vendor/licenses/bisheng-sdk/LICENSE").read() == (ROOT / "LICENSE").read_bytes()
            manifests.append(package.extractfile("f059-source-vendor.json").read())
            assert (
                package.extractfile("_vendor/wheels/bisheng_sdk-0.1.1-py3-none-any.whl").read()
                == (ROOT / "src/backend/bisheng/dev_toolkit/artifacts/bisheng_sdk-0.1.1-py3-none-any.whl").read_bytes()
            )
    assert manifests[0] == manifests[1]
    for scenario in scenarios:
        if scenario["mode"] != "source-image":
            with tarfile.open(scenario["package"]) as package:
                assert not any(item.name.startswith("_vendor/") for item in package)
                if scenario["runtime"] == "python3.11":
                    assert "sys.path[:0]" not in package.extractfile("main.py").read().decode()


def test_source_image_without_materials_exposes_docker_precondition(tmp_path):
    suite, _output, values = environment(tmp_path)
    _profiles, scenarios = bootstrap.build_packages(suite, values, inventory=inventory())
    source = next(item for item in scenarios if item["mode"] == "source-image")
    assert source["source_dependencies"] == "docker-vendor-unprovided-kubernetes-profile-required"
    with tarfile.open(source["package"]) as package:
        assert not any(member.name.startswith("_vendor/") for member in package)


@pytest.mark.parametrize("mutation", ["missing", "hash", "sdk", "native", "version", "license", "manifest-path"])
def test_source_vendor_rejects_incomplete_tampered_or_unsupported_materials(tmp_path, mutation):
    import hashlib
    import zipfile

    materials = vendor_wheelhouse(tmp_path)
    path = materials / "source-vendor.json"
    manifest = json.loads(path.read_text())
    if mutation == "missing":
        del manifest["wheels"]["wheels/httpcore-1.0.9-py3-none-any.whl"]
    elif mutation == "hash":
        manifest["wheels"]["wheels/httpx-0.28.1-py3-none-any.whl"] = "sha256:" + "0" * 64
    elif mutation == "manifest-path":
        manifest["wheels"]["../outside.whl"] = "sha256:" + "0" * 64
    else:
        original = "bisheng_sdk-0.1.1-py3-none-any.whl" if mutation == "sdk" else "httpx-0.28.1-py3-none-any.whl"
        target = materials / "wheels" / original
        with zipfile.ZipFile(target) as wheel:
            content = {item.filename: wheel.read(item) for item in wheel.infolist()}
        if mutation == "sdk":
            content["bisheng_sdk/auth.py"] += b"\n# modified SDK\n"
        if mutation == "license":
            del content["httpx-0.28.1.dist-info/licenses/LICENSE"]
        if mutation == "native":
            content["httpx-0.28.1.dist-info/WHEEL"] = (
                b"Root-Is-Purelib: false\nTag: cp311-cp311-manylinux_2_17_x86_64\n"
            )
        if mutation == "version":
            content["httpx-0.28.1.dist-info/METADATA"] = b"Name: httpx\nVersion: 0.27.0\n"
        with zipfile.ZipFile(target, "w") as wheel:
            for name, data in content.items():
                wheel.writestr(name, data)
        manifest["wheels"]["wheels/" + original] = "sha256:" + hashlib.sha256(target.read_bytes()).hexdigest()
    path.write_text(json.dumps(manifest))
    suite, _output, values = environment(tmp_path)
    with pytest.raises(bootstrap.BootstrapError, match="source_vendor_"):
        bootstrap.build_packages(suite, values, inventory=inventory(), source_wheelhouse=materials)
    assert not list(suite.glob("*.tar.gz"))


@pytest.mark.parametrize(
    "member", ["../outside", "/absolute", "bad\\path", "inject.pth", "extra.so", "shared/__init__.py"]
)
def test_source_vendor_rejects_unsafe_paths_native_code_and_file_overwrite(tmp_path, member):
    materials = vendor_wheelhouse(tmp_path)
    if member == "shared/__init__.py":
        mutate_vendor_wheel(materials, "h11/__init__.py")
    else:
        mutate_vendor_wheel(materials, member)
    with pytest.raises(bootstrap.BootstrapError, match="source_vendor_"):
        bootstrap.source_vendor_files(materials)


def test_source_vendor_rejects_symlink_wheel_and_member(tmp_path):
    materials = vendor_wheelhouse(tmp_path)
    mutate_vendor_wheel(materials, "linked.py", symlink=True)
    with pytest.raises(bootstrap.BootstrapError, match="source_vendor_"):
        bootstrap.source_vendor_files(materials)
    materials = vendor_wheelhouse(tmp_path / "second")
    target = materials / "wheels/httpcore-1.0.9-py3-none-any.whl"
    original = target.read_bytes()
    target.unlink()
    outside = tmp_path / "outside.whl"
    outside.write_bytes(original)
    target.symlink_to(outside)
    with pytest.raises(bootstrap.BootstrapError, match="source_vendor_"):
        bootstrap.source_vendor_files(materials)


@pytest.mark.parametrize("document", ["[]", '{"format":"f059-source-wheelhouse-v1","format":"other"}'])
def test_source_vendor_rejects_malformed_or_ambiguous_manifest(tmp_path, document):
    materials = vendor_wheelhouse(tmp_path)
    (materials / "source-vendor.json").write_text(document)
    with pytest.raises(bootstrap.BootstrapError, match="source_vendor_"):
        bootstrap.source_vendor_files(materials)


def test_source_wheelhouse_cli_is_explicit_local_only(tmp_path, capsys):
    materials = vendor_wheelhouse(tmp_path)
    profile_inventory = tmp_path / "inventory.json"
    profile_inventory.write_text(json.dumps(inventory()))
    suite = tmp_path / "e2e-f059-vendored-cli"
    assert (
        bootstrap.main(
            [
                "--api-base",
                "http://127.0.0.1:7860",
                "--suite-dir",
                str(suite),
                "--profile-inventory",
                str(profile_inventory),
                "--source-wheelhouse",
                str(materials),
                "--prepare-only",
            ]
        )
        == 0
    )
    summary = json.loads(capsys.readouterr().out)
    assert summary["api_bootstrap_executed"] is False
    source = next(item for item in json.loads((suite / "scenarios.json").read_text()) if item["mode"] == "source-image")
    assert source["source_dependencies"] == "explicit-vendored-wheelhouse"


def test_source_vendor_original_wheels_report_scanner_boundary_and_real_source_key_refusal(tmp_path):
    """T191: Preserve dependency binary skips; real source remains subject to the normal gate."""
    from bisheng.app_publish.domain.services.secret_scanner import scan_package

    materials = vendor_wheelhouse(tmp_path)
    suite, _output, values = environment(tmp_path)
    _profiles, scenarios = bootstrap.build_packages(suite, values, inventory=inventory(), source_wheelhouse=materials)
    source = next(item for item in scenarios if item["mode"] == "source-image")
    extracted = tmp_path / "inspect-source"
    with tarfile.open(source["package"]) as package:
        package.extractall(extracted, filter="data")
    result = scan_package(extracted)
    assert result.blocked is False
    assert result.files_skipped == 8
    assert {item["reason"] for item in result.skipped} == {"binary"}
    assert all(item["file"].startswith("_vendor/wheels/") and item["file"].endswith(".whl") for item in result.skipped)
    # A deliberately invalid synthetic credential shape is test data, never a real credential.
    with (extracted / "main.py").open("a") as stream:
        stream.write("\napi_key = '" + "sk-proj-" + "A" * 32 + "'\n")
    rejected = scan_package(extracted)
    assert rejected.blocked is True
    assert any(item["rule_id"] == "openai_sk" and item["file"] == "main.py" for item in rejected.hits)

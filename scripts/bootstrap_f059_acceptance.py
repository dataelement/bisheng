#!/usr/bin/env python3
"""Prepare private fixtures and bootstrap a dedicated empty F059 instance.

Default mode writes local fixtures only. --bootstrap uses real platform APIs.
No default password, SQL write, manager RPC, container engine, or cluster API is
used. The dedicated admin identity and empty-instance inventory are mandatory.
Application suffixes are immutable per suite. Use a new suite and evidence
journal for each new publication batch; deleted application slugs stay reserved.
"""

from __future__ import annotations

import argparse
import asyncio
import io
import ipaddress
import json
import os
import re
import secrets
import shlex
import stat
import tarfile
import tempfile
from pathlib import Path
from urllib.parse import quote, urlsplit
from uuid import UUID, uuid4

import httpx
import yaml

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "scripts/fixtures/f059"
PREFIX = "e2e-f059-"
IMAGE = re.compile(r"[A-Za-z0-9][A-Za-z0-9./:_-]*@sha256:[a-f0-9]{64}")
DIGEST = re.compile(r"sha256:[a-f0-9]{64}")
ROLES = ("OWNER", "NONOWNER", "FOREIGN", "APPROVER")


class BootstrapError(RuntimeError):
    """Safe diagnostic with no response body, credentials or request content."""


def api_base(value):
    parsed = urlsplit(value)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or parsed.path.rstrip("/") not in {"", "/api/v1"}
    ):
        raise BootstrapError("api_base_invalid")
    try:
        address = ipaddress.ip_address(parsed.hostname)
    except ValueError:
        raise BootstrapError("dedicated_literal_private_address_required") from None
    if not (address.is_private or address.is_loopback):
        raise BootstrapError("public_instance_refused")
    return parsed.scheme + "://" + parsed.netloc + "/api/v1"


def private_read(path):
    path = Path(path)
    information = path.lstat()
    if not stat.S_ISREG(information.st_mode) or information.st_mode & 0o077:
        raise BootstrapError("private_file_permissions_required")
    return path.read_text()


def private_write(path, data):
    path = Path(path)
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if path.is_symlink():
        raise BootstrapError("private_output_link_refused")
    with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, prefix=path.name + ".", delete=False) as stream:
        temporary = Path(stream.name)
        os.fchmod(stream.fileno(), 0o600)
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def read_env(path, *, allowlist=None):
    """Read literals only; optional filtering happens before unrelated parsing."""
    values = {}
    selected = frozenset(allowlist) if allowlist is not None else None
    if path is None:
        return values
    for line in private_read(path).splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:]
        key, separator, raw = line.partition("=")
        if selected is not None and key.strip() not in selected:
            continue
        if not separator or not re.fullmatch(r"[A-Z][A-Z0-9_]*", key):
            raise BootstrapError("env_file_invalid")
        if key in values:
            raise BootstrapError("env_duplicate_key")
        try:
            parts = shlex.split(raw, comments=False)
        except ValueError:
            raise BootstrapError("env_value_not_a_scalar") from None
        if len(parts) > 1:
            raise BootstrapError("env_value_not_a_scalar")
        values[key] = parts[0] if parts else ""
    return values


def validate_application_suffix(value):
    if value is None:
        return ""
    if not isinstance(value, str) or not 1 <= len(value) <= 16 or not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", value):
        raise BootstrapError("application_suffix_invalid")
    return value


def application_slug(case, application_suffix=None):
    suffix = validate_application_suffix(application_suffix)
    slug = PREFIX + case + ("-" + suffix if suffix else "")
    if len(slug) > 64 or not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", slug):
        raise BootstrapError("application_slug_invalid")
    return slug


def prepare_environment(
    suite_dir, *, base, input_env=None, output_env=None, entry_base=None, application_suffix=None
):
    suffix = validate_application_suffix(application_suffix)
    suite = Path(suite_dir).resolve()
    if not any(part.startswith(PREFIX) or part == "e2e-f059" for part in suite.parts):
        raise BootstrapError("dedicated_suite_directory_required")
    suite.mkdir(mode=0o700, parents=True, exist_ok=True)
    suite.chmod(0o700)
    marker_path = suite / "environment-marker.json"
    output = Path(output_env) if output_env else suite / "e2e.env"
    if input_env is not None and output.resolve() == Path(input_env).resolve():
        raise BootstrapError("platform_env_must_not_be_overwritten")
    values = read_env(output) if output.exists() else {}
    if "F059_E2E_APPLICATION_SUFFIX" in values and values["F059_E2E_APPLICATION_SUFFIX"] != suffix:
        raise BootstrapError("existing_application_suffix_mismatch")
    supplied = read_env(input_env, allowlist={"E2E_ADMIN_USERNAME", "E2E_ADMIN_PASSWORD"})
    for key in ("E2E_ADMIN_USERNAME", "E2E_ADMIN_PASSWORD"):
        if key in supplied:
            if key in values and values[key] != supplied[key]:
                raise BootstrapError("existing_admin_credential_mismatch")
            values[key] = supplied[key]
    if marker_path.exists():
        marker = json.loads(private_read(marker_path))
        if marker.get("purpose") != "e2e-f059-only" or marker.get("api_base") != base:
            raise BootstrapError("existing_environment_marker_mismatch")
        str(UUID(marker["instance_id"]))
        if marker.get("application_suffix", "") != suffix:
            raise BootstrapError("existing_application_suffix_mismatch")
    else:
        marker = {
            "purpose": "e2e-f059-only",
            "api_base": base,
            "instance_id": str(uuid4()),
            "application_suffix": suffix,
        }
        private_write(marker_path, json.dumps(marker, indent=2))
    nonce = marker["instance_id"].replace("-", "")[:6]
    values.setdefault("E2E_ADMIN_USERNAME", PREFIX + "root-" + nonce)
    values.setdefault("E2E_ADMIN_PASSWORD", "Aa1!" + secrets.token_urlsafe(16))
    if not values["E2E_ADMIN_USERNAME"].startswith(PREFIX):
        raise BootstrapError("dedicated_admin_identity_required")
    values.update(
        E2E_API_BASE=base,
        F059_E2E="1",
        F059_ACCEPTANCE_INSTANCE=marker["instance_id"],
        F059_E2E_APPLICATION_SUFFIX=suffix,
    )
    values.setdefault("F059_E2E_TENANT_CODE", PREFIX + "tenant-" + nonce)
    values.setdefault("F059_E2E_FOREIGN_TENANT_CODE", PREFIX + "foreign-" + nonce)
    values.setdefault("F059_E2E_EXECUTOR", "kubernetes")
    values.setdefault("F059_E2E_TIMEOUT", "900")
    entry = entry_base or values.get("F059_E2E_ENTRY_BASE", base.rsplit("/api/v1", 1)[0])
    if urlsplit(entry).path.rstrip("/"):
        raise BootstrapError("entry_base_origin_required")
    values["F059_E2E_ENTRY_BASE"] = api_base(entry).removesuffix("/api/v1")
    for role in ROLES:
        values.setdefault(f"F059_E2E_{role}_USERNAME", PREFIX + role.lower() + "-" + nonce)
        values.setdefault(f"F059_E2E_{role}_PASSWORD", "Aa1!" + secrets.token_urlsafe(16))
    for key, value in values.items():
        if key.endswith("USERNAME") or key.endswith("TENANT_CODE"):
            if not value.startswith(PREFIX):
                raise BootstrapError("non_test_identity_refused")
    save_env(output, values)
    return suite, output, values


def save_env(path, values):
    private_write(
        path,
        "# Private F059 acceptance credentials. Do not commit or print.\n"
        + "".join(key + "=" + shlex.quote(value) + "\n" for key, value in sorted(values.items())),
    )


def validate_profile_revision(value):
    if type(value) is not int or value < 1:
        raise BootstrapError("profile_revision_invalid")
    return value


def profile_definitions(inventory, *, revision=1):
    revision = validate_profile_revision(revision)
    if inventory.get("platform") != "linux/amd64":
        raise BootstrapError("native_amd64_inventory_required")
    images = inventory["images"]
    rows = []
    for language, code, runtime, preparer, abi in (
        ("python3.11", "e2e-f059-python311", "app-python", "app-python-preparer", "cp311-linux_x86_64"),
        ("node20", "e2e-f059-node20", "app-node", "app-node-preparer", "node20-linux_x86_64"),
        ("static", "e2e-f059-static", "app-static", "app-node-preparer", "nginx-linux_x86_64"),
    ):
        pair = [images[runtime], images[preparer]]
        if any(
            not IMAGE.fullmatch(row.get("image", ""))
            or not DIGEST.fullmatch(row.get("image_id", ""))
            or row.get("platform", "linux/amd64") != "linux/amd64"
            for row in pair
        ):
            raise BootstrapError("immutable_native_image_metadata_required")
        rows.append(
            {
                "code": code,
                "revision": revision,
                "language": language,
                "official": False,
                "platforms": {
                    "linux/amd64": {
                        "runtime_image": pair[0]["image"],
                        "runtime_digest": pair[0]["image"].rsplit("@", 1)[1],
                        "runtime_image_id": pair[0]["image_id"],
                        "preparer_image": pair[1]["image"],
                        "preparer_digest": pair[1]["image"].rsplit("@", 1)[1],
                        "preparer_image_id": pair[1]["image_id"],
                        "abi": abi,
                        "toolchain": {"platform": "linux/amd64", "profile_source": "dedicated-acceptance-inventory"},
                        "uid": 10001,
                        "gid": 10001,
                    }
                },
            }
        )
    return rows


def archive(path, files):
    path = Path(path)
    with tarfile.open(path, "w:gz") as package:
        for name, content in sorted(files.items()):
            data = content.encode() if isinstance(content, str) else content
            member = tarfile.TarInfo(name)
            member.size, member.mode, member.mtime = len(data), 0o644, 0
            package.addfile(member, io.BytesIO(data))
    path.chmod(0o600)


def application_manifest(
    slug, runtime, mode, *, profile=None, profile_revision=1, image=None, version=1, model_name=None, knowledge_ids=()
):
    document = {
        "manifest_version": 2,
        "name": slug,
        "slug": slug,
        "description": "Dedicated F059 acceptance revision " + str(version),
        "runtime": runtime,
        "port": 8080,
        "delivery": {"mode": mode},
    }
    if mode == "bundle":
        document["delivery"]["profile"] = profile + "@" + str(validate_profile_revision(profile_revision))
    if mode == "image":
        if not image or not IMAGE.fullmatch(image):
            raise BootstrapError("pinned_demo_image_required")
        document["delivery"].update(image=image, startup={"command": ["python", "/workspace/app/main.py"]})
    elif runtime == "python3.11":
        document["delivery"]["startup"] = {"command": ["python", "main.py"]}
    elif runtime == "node20":
        document["delivery"]["startup"] = {"command": ["node", "server.js"]}
    if runtime == "python3.11":
        document["database"] = {
            "tables": [
                {
                    "name": "items",
                    "columns": [
                        {"name": "id", "type": "INTEGER", "nullable": False, "primary_key": True},
                        {"name": "value", "type": "TEXT", "nullable": False, "default": "initial"},
                    ],
                }
            ]
        }
        if model_name or knowledge_ids:
            document["capabilities"] = {
                "models": [{"name": model_name}] if model_name else [],
                "knowledge_bases": [{"id": str(value)} for value in knowledge_ids],
            }
    return document


def build_packages(
    suite,
    values,
    *,
    inventory,
    profile_revision=1,
    demo_image=None,
    demo_image_v2=None,
    model_name=None,
    knowledge_ids=(),
):
    profiles = profile_definitions(inventory, revision=profile_revision)
    (suite / "profiles.json").write_text(json.dumps(profiles, indent=2))
    scenarios = []
    for suffix, runtime, mode, code in (
        ("python-bundle", "python3.11", "bundle", "e2e-f059-python311"),
        ("node-bundle", "node20", "bundle", "e2e-f059-node20"),
        ("static-bundle", "static", "bundle", "e2e-f059-static"),
        ("python-source", "python3.11", "source-image", "e2e-f059-python311"),
        ("python-image", "python3.11", "image", "e2e-f059-python311"),
        ("missing-dependency", "python3.11", "bundle", "e2e-f059-python311"),
    ):
        if mode == "image" and not demo_image:
            continue
        slug = application_slug(suffix, values.get("F059_E2E_APPLICATION_SUFFIX") or None)
        revisions = []
        for version in (1, 2):
            manifest = application_manifest(
                slug,
                runtime,
                mode,
                profile=code,
                profile_revision=profile_revision,
                image=(demo_image_v2 or demo_image) if version == 2 else demo_image,
                version=version,
                model_name=model_name,
                knowledge_ids=knowledge_ids,
            )
            files = {
                "bisheng-app.yaml": yaml.safe_dump(manifest, sort_keys=False),
                "fixture-version.txt": str(version),
                "capabilities.json": json.dumps({"model_name": model_name, "knowledge_base_ids": list(knowledge_ids)}),
            }
            if runtime == "python3.11":
                files["main.py"] = (FIXTURES / "python_demo.py").read_text()
                files["requirements.txt"] = ""
                if suffix == "missing-dependency":
                    files["requirements.txt"] = "e2e-f059-missing-dependency==0.0.1 --hash=sha256:" + "0" * 64 + "\n"
            elif runtime == "node20":
                files["server.js"] = (FIXTURES / "node_demo.js").read_text()
                files["package.json"] = json.dumps(
                    {"name": slug, "version": "1.0.0", "main": "server.js", "scripts": {"start": "node server.js"}}
                )
                files["package-lock.json"] = json.dumps(
                    {
                        "name": slug,
                        "version": "1.0.0",
                        "lockfileVersion": 3,
                        "requires": True,
                        "packages": {"": {"name": slug, "version": "1.0.0"}},
                    }
                )
            else:
                files["index.html"] = (
                    "<!doctype html><meta charset='utf-8'><title>e2e-f059-static</title><p>e2e-f059 static revision "
                    + str(version)
                    + "</p>"
                )
                files["health"] = '{"status":"ok"}'
            path = suite / (slug + "-v" + str(version) + ".tar.gz")
            archive(path, files)
            revisions.append(path)
            if runtime == "python3.11" and mode == "bundle" and suffix == "python-bundle":
                context = suite / ("demo-image-v" + str(version))
                context.mkdir(mode=0o700, exist_ok=True)
                for name in ("main.py", "fixture-version.txt", "capabilities.json"):
                    (context / name).write_text(files[name])
                (context / "Dockerfile").write_text((FIXTURES / "Dockerfile.demo").read_text())
        scenario = {
            "slug": slug,
            "package": str(revisions[0]),
            "update": str(revisions[1]),
            "mode": mode,
            "runtime": runtime,
            "entry_path": "/",
            "expected_text": "e2e-f059",
        }
        if suffix == "missing-dependency":
            scenario.pop("update")
            scenario.update(expected_failure_code=16227, expected_failure_stage="precheck_build")
        else:
            scenario["application_checks"] = [{"path": "/health", "expected_json": {"status": "ok"}}]
            if runtime == "python3.11":
                scenario.update(
                    table="items", row_key="1", update_values={"value": "e2e-f059-persisted"}, websocket_path="/ws"
                )
                scenario["application_checks"] += [
                    {
                        "path": "/sdk/identity",
                        "expected_json": {"subject_kind": "human", "app_id_matches": True, "obo_present": True},
                    },
                    {
                        "path": "/sdk/storage-roundtrip",
                        "expected_json": {"storage_roundtrip": True, "bytes": 32, "subject_kind": "human"},
                    },
                ]
                if model_name:
                    scenario["application_checks"].append(
                        {"path": "/sdk/model", "expected_json": {"model": model_name, "subject_kind": "human"}}
                    )
                if knowledge_ids:
                    scenario["application_checks"].append(
                        {"path": "/sdk/retrieve", "expected_json": {"subject_kind": "human"}}
                    )
            elif runtime == "node20":
                scenario["websocket_path"] = "/ws"
        scenarios.append(scenario)
    path = suite / "scenarios.json"
    path.write_text(json.dumps(scenarios, indent=2))
    values["F059_E2E_SCENARIOS"] = str(path)
    return profiles, scenarios


def items(value):
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        return value.get("data", [])
    raise BootstrapError("list_response_invalid")


class Api:
    def __init__(self, base, client):
        self.base, self.client = base, client
        self.tokens = {}

    async def request(self, method, path, *, role="ADMIN", raw=False, **kwargs):
        headers = {"Cookie": "access_token_cookie=" + self.tokens[role]} if role in self.tokens else {}
        response = await self.client.request(method, self.base + path, headers=headers, **kwargs)
        if raw:
            return response
        try:
            body = response.json()
            code = body["status_code"]
        except Exception:
            raise BootstrapError("api_response_invalid") from None
        if response.status_code not in {200, 201, 202} or code != 200:
            raise BootstrapError("api_refused_" + str(code if isinstance(code, int) else response.status_code))
        return body["data"]

    async def encrypted(self, password):
        import base64

        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric import padding

        document = await self.request("GET", "/user/public_key")
        key = serialization.load_pem_public_key(document["public_key"].encode())
        return base64.b64encode(key.encrypt(password.encode(), padding.PKCS1v15())).decode()

    async def login(self, role, username, password):
        # RSA encryption and JWT login use the same public API as browsers.
        # No test-helper fallback password or process-global API base is used.
        data = await self.request(
            "POST", "/user/login", json={"user_name": username, "password": await self.encrypted(password)}
        )
        self.tokens[role] = data["access_token"]
        return await self.request("GET", "/user/info", role=role)


async def bootstrap(base, suite, output, values, *, profiles, register_first=False, client=None):
    marker = json.loads(private_read(suite / "environment-marker.json"))
    if (
        marker.get("api_base") != base
        or marker.get("instance_id") != values["F059_ACCEPTANCE_INSTANCE"]
        or marker.get("application_suffix", "") != values.get("F059_E2E_APPLICATION_SUFFIX", "")
    ):
        raise BootstrapError("environment_marker_mismatch")
    if client is None:
        async with httpx.AsyncClient(timeout=60, trust_env=False, follow_redirects=False) as session:
            return await bootstrap(
                base, suite, output, values, profiles=profiles, register_first=register_first, client=session
            )
    api = Api(base, client)
    if register_first:
        await api.request(
            "POST",
            "/user/regist",
            json={
                "user_name": values["E2E_ADMIN_USERNAME"],
                "external_id": values["E2E_ADMIN_USERNAME"],
                "password": await api.encrypted(values["E2E_ADMIN_PASSWORD"]),
            },
        )
    admin = await api.login("ADMIN", values["E2E_ADMIN_USERNAME"], values["E2E_ADMIN_PASSWORD"])
    if (
        int(admin.get("user_id", 0)) != 1
        or admin.get("is_global_super") is not True
        or admin.get("user_name") != values["E2E_ADMIN_USERNAME"]
    ):
        raise BootstrapError("first_dedicated_super_admin_required")
    users = items(await api.request("GET", "/user/list", params={"page_size": 100, "page_num": 1}))
    if any(not row.get("user_name", "").startswith(PREFIX) for row in users) or len(users) >= 100:
        raise BootstrapError("non_test_or_unbounded_user_inventory_refused")
    tenants = items(await api.request("GET", "/tenants/", params={"page_size": 100, "page": 1}))
    if len(tenants) >= 100 or any(int(row["id"]) != 1 and not row["tenant_code"].startswith(PREFIX) for row in tenants):
        raise BootstrapError("non_test_tenant_inventory_refused")
    apps = items(await api.request("GET", "/apps"))
    if any(not row.get("slug", "").startswith(PREFIX) for row in apps):
        raise BootstrapError("non_test_application_inventory_refused")
    roots = items(await api.request("GET", "/departments/children"))
    root = next((row for row in roots if row.get("dept_id") == "BS@root"), None)
    if root is None:
        raise BootstrapError("root_department_missing")
    state = {
        "instance_id": marker["instance_id"],
        "api_base": base,
        "setup_kind": "real-platform-api-fixture",
        "tenants": {},
        "users": {},
        "profiles": [],
    }

    def save():
        private_write(suite / "bootstrap-state.json", json.dumps(state, indent=2))

    for label, key in (("OWNER", "F059_E2E_TENANT_CODE"), ("FOREIGN", "F059_E2E_FOREIGN_TENANT_CODE")):
        code = values[key]
        children = items(await api.request("GET", "/departments/children", params={"parent_id": root["id"]}))
        department = next((row for row in children if row["name"] == code), None)
        if department is None:
            department = await api.request(
                "POST", "/departments/", json={"name": code, "parent_id": root["id"], "default_role_ids": [2]}
            )
        existing = next((row for row in tenants if row["tenant_code"] == code), None)
        if existing:
            detail = await api.request("GET", f"/tenants/{existing['id']}")
            if int(detail.get("root_dept_id") or 0) != int(department["id"]):
                raise BootstrapError("existing_test_tenant_department_mismatch")
        tenant = existing or await api.request(
            "POST",
            "/departments/" + str(department["id"]) + "/mount-tenant",
            json={"tenant_code": code, "tenant_name": code},
        )
        if int(tenant["id"]) == 1:
            raise BootstrapError("root_tenant_cannot_be_test_tenant")
        state["tenants"][label] = {"id": int(tenant["id"]), "tenant_code": code, "department": department}
        save()
    existing_users = {row["user_name"]: row for row in users}
    if len(existing_users) != len(users):
        raise BootstrapError("ambiguous_existing_test_identity")
    for role in ROLES:
        username = values[f"F059_E2E_{role}_USERNAME"]
        tenant = state["tenants"]["FOREIGN" if role == "FOREIGN" else "OWNER"]
        department = tenant["department"]
        user = existing_users.get(username)
        if user is None:
            allowed = items(
                await api.request("GET", "/departments/" + quote(department["dept_id"], safe="") + "/assignable-roles")
            )
            if not any(int(row["id"]) == 2 for row in allowed):
                raise BootstrapError("global_default_role_not_assignable")
            user = await api.request(
                "POST",
                "/departments/local-members",
                json={
                    "dept_id": department["dept_id"],
                    "user_name": username,
                    "person_id": username,
                    "password": await api.encrypted(values[f"F059_E2E_{role}_PASSWORD"]),
                    "role_ids": [2],
                },
            )
        state["users"][role] = {"id": int(user.get("user_id") or user["id"]), "name": username}
        save()
        info = await api.login(role, username, values[f"F059_E2E_{role}_PASSWORD"])
        current = await api.request("GET", "/user/current-tenant", role=role)
        if info.get("is_global_super") or int(current["leaf_tenant_id"]) != tenant["id"]:
            raise BootstrapError("natural_person_tenant_scope_mismatch")
    tenant_id, approver_id = state["tenants"]["OWNER"]["id"], state["users"]["APPROVER"]["id"]
    administrators = await api.request("GET", f"/tenants/{tenant_id}/admins")
    administrator_ids = administrators.get("user_ids") if isinstance(administrators, dict) else None
    if not isinstance(administrator_ids, list) or any(
        type(value) is not int or value < 1 for value in administrator_ids
    ):
        raise BootstrapError("tenant_admin_list_invalid")
    if approver_id not in administrator_ids:
        await api.request("POST", f"/tenants/{tenant_id}/admins", json={"user_id": approver_id})
    # Refresh login so child-admin status and permission context are fresh.
    await api.login("APPROVER", values["F059_E2E_APPROVER_USERNAME"], values["F059_E2E_APPROVER_PASSWORD"])
    scenario = next(
        (
            row
            for row in items(await api.request("GET", "/approval/admin/scenarios", role="APPROVER"))
            if row["scenario_code"] == "app_publish_request"
        ),
        None,
    )
    if scenario is None:
        raise BootstrapError("seeded_publish_approval_missing")
    routes = items(await api.request("GET", f"/approval/admin/scenarios/{scenario['id']}/routes", role="APPROVER"))
    active = [row for row in routes if row.get("enabled", True)]
    manual = active[0] if len(active) == 1 and active[0]["route_type"] == "flow" else None
    if manual is None or manual.get("match_config", {}):
        raise BootstrapError("manual_publish_route_missing")
    flow = manual["flow_definition_id"]
    await api.request(
        "PUT",
        f"/approval/admin/flows/{flow}/nodes",
        role="APPROVER",
        json={
            "nodes": [
                {
                    "node_code": "e2e-f059-manual",
                    "node_name": "e2e-f059 manual review",
                    "node_order": 1,
                    "node_mode": "or",
                    "approver_config": {"sources": [{"type": "direct_user", "user_ids": [approver_id]}]},
                }
            ]
        },
    )
    if not scenario.get("enabled"):
        await api.request("PUT", f"/approval/admin/scenarios/{scenario['id']}", role="APPROVER", json={"enabled": True})
    state["approval"] = {
        "scenario_id": scenario["id"],
        "flow_id": flow,
        "approver_user_id": approver_id,
        "manual": True,
    }
    account_name = PREFIX + "publisher-" + marker["instance_id"][:6]
    accounts = items(await api.request("GET", "/service-accounts", role="APPROVER", params={"page_size": 200}))
    matching = [row for row in accounts if row["name"] == account_name]
    if len(matching) > 1:
        raise BootstrapError("ambiguous_existing_publisher")
    account = matching[0] if matching else None
    if account and account.get("resource_owner", {}).get("user_id") != state["users"]["OWNER"]["id"]:
        raise BootstrapError("existing_publisher_owner_mismatch")
    if not values.get("F059_E2E_OWNER_API_KEY"):
        account = account or await api.request(
            "POST",
            "/service-accounts",
            role="APPROVER",
            json={
                "name": account_name,
                "description": "Dedicated acceptance owner publisher",
                "resource_owner_user_id": state["users"]["OWNER"]["id"],
            },
        )
        issued = await api.request(
            "POST",
            f"/service-accounts/{account['id']}/keys",
            role="APPROVER",
            json={"name": PREFIX + "app-manage", "scopes": ["app:manage"]},
        )
        values["F059_E2E_OWNER_API_KEY"] = issued["plaintext"]
        save_env(output, values)
    if account:
        state["publisher_service_account_id"] = account["id"]
    identity = await client.get(
        base.rsplit("/api/v1", 1)[0] + "/api/v2/auth/whoami",
        headers={"Authorization": "Bearer " + values["F059_E2E_OWNER_API_KEY"]},
    )
    principal = identity.json().get("data", {})
    if (
        identity.status_code != 200
        or principal.get("mode") != "S"
        or "app:manage" not in principal.get("scopes", [])
        or principal.get("resource_owner", {}).get("user_id") != state["users"]["OWNER"]["id"]
        or int(principal.get("tenant_id", 0)) != tenant_id
    ):
        raise BootstrapError("publisher_key_identity_mismatch")
    for profile in profiles:
        imported = await api.request("POST", "/runtime/profiles", json=profile)
        defaults = items(await api.request("GET", "/runtime/profiles/defaults"))
        default = next((row for row in defaults if row["language"] == profile["language"]), None)
        if not default or default["profile_id"] != imported["id"]:
            await api.request(
                "PUT",
                "/runtime/profiles/default",
                json={
                    "language": profile["language"],
                    "profile_id": imported["id"],
                    "expected_generation": default["generation"] if default else 0,
                },
            )
        state["profiles"].append(
            {
                "id": imported["id"],
                "code": profile["code"],
                "revision": profile["revision"],
                "official": False,
                "platform": "linux/amd64",
            }
        )
        save()
    state["complete"] = True
    save()
    save_env(output, values)
    return state


class SafeParser(argparse.ArgumentParser):
    def error(self, _message):
        self.print_usage()
        raise BootstrapError("invalid_arguments")


def main(argv=None):
    parser = SafeParser(description=__doc__)
    parser.add_argument("--api-base", required=True)
    parser.add_argument("--suite-dir", type=Path, required=True)
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("--output-env-file", type=Path)
    parser.add_argument("--entry-base")
    parser.add_argument(
        "--application-suffix",
        help="Optional 1-16 lowercase letters/digits and single hyphens; immutable per suite. New batch needs a new journal.",
    )
    parser.add_argument("--profile-inventory", type=Path)
    parser.add_argument("--profile-revision", type=int, default=1)
    parser.add_argument("--demo-image")
    parser.add_argument("--demo-image-v2")
    parser.add_argument("--model-name")
    parser.add_argument("--knowledge-id", type=int, action="append", default=[])
    parser.add_argument("--prepare-only", action="store_true")
    parser.add_argument("--bootstrap", action="store_true")
    parser.add_argument("--register-first-admin", action="store_true")
    args = parser.parse_args(argv)
    validate_profile_revision(args.profile_revision)
    if (args.prepare_only and args.bootstrap) or (args.register_first_admin and not args.bootstrap):
        raise BootstrapError("mode_invalid")
    base = api_base(args.api_base)
    suite, output, values = prepare_environment(
        args.suite_dir,
        base=base,
        input_env=args.env_file,
        output_env=args.output_env_file,
        entry_base=args.entry_base,
        application_suffix=args.application_suffix,
    )
    profiles, scenarios = [], []
    if args.profile_inventory:
        inventory = json.loads(args.profile_inventory.read_text())
        profiles, scenarios = build_packages(
            suite,
            values,
            inventory=inventory,
            profile_revision=args.profile_revision,
            demo_image=args.demo_image,
            demo_image_v2=args.demo_image_v2,
            model_name=args.model_name,
            knowledge_ids=args.knowledge_id,
        )
        save_env(output, values)
    if args.bootstrap:
        if not profiles:
            raise BootstrapError("profile_inventory_required_for_api_bootstrap")
        asyncio.run(bootstrap(base, suite, output, values, profiles=profiles, register_first=args.register_first_admin))
    print(
        json.dumps(
            {
                "suite_dir": str(suite),
                "env_file": str(output),
                "packages": len(scenarios),
                "api_bootstrap_executed": bool(args.bootstrap),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        # Never render exception text or response bodies; they may contain keys.
        print(
            "F059 acceptance bootstrap failed ("
            + (str(error) if isinstance(error, BootstrapError) else type(error).__name__)
            + ")",
            file=__import__("sys").stderr,
        )
        raise SystemExit(1) from None

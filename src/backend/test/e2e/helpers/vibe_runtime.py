"""Real platform-API journeys shared by the F059 CLI and pytest entry points.

No cluster credentials, manager RPC, database access or mock execution lives here.
Infrastructure fault injection is performed by the operator; checkpoint comparison
records only what the public platform and application entry actually observe.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import tarfile
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote, urlsplit

import httpx
import yaml

from test.e2e.helpers.api import API_BASE, assert_resp_200, assert_resp_error
from test.e2e.helpers.auth import auth_headers, get_admin_token, get_user_token
from test.e2e.helpers.cleanup import ensure_test_tenant

PREFIX = "e2e-f059-"
ROLES = ("OWNER", "NONOWNER", "FOREIGN", "APPROVER")
SECRET_KEYS = {"password", "token", "access_token", "authorization", "cookie", "secret", "credential"}


def required(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise ValueError(f"{name} is required")
    return value


def validate_slug(slug: str) -> str:
    if not re.fullmatch(r"e2e-f059-[a-z0-9]+(?:-[a-z0-9]+)*", slug) or len(slug) > 64:
        raise ValueError("slug must be a complete e2e-f059- application identifier")
    return slug


def validate_package(path: Path, slug: str) -> dict:
    """Inspect the root manifest without extracting the untrusted package."""
    validate_slug(slug)
    with tarfile.open(path, "r:gz") as archive:
        candidates = [member for member in archive if member.name in {"bisheng-app.yaml", "./bisheng-app.yaml"}]
        if len(candidates) != 1 or not candidates[0].isfile() or candidates[0].size > 65536:
            raise ValueError("one bounded regular root manifest is required")
        stream = archive.extractfile(candidates[0])
        document = yaml.safe_load(stream.read())
    if not isinstance(document, dict) or not str(document.get("name", "")).startswith(PREFIX):
        raise ValueError("package name must start with e2e-f059-")
    if document.get("slug") != slug:
        raise ValueError("package slug must match the exact scenario slug")
    return document


@dataclass(frozen=True)
class Scenario:
    slug: str
    package: Path
    mode: str
    runtime: str
    update: Path | None = None
    table: str = ""
    row_key: str = "1"
    update_values: dict | None = None
    entry_path: str = "/"
    expected_text: str = ""
    expected_failure_code: int | None = None
    expected_failure_stage: str | None = None
    application_checks: tuple[dict, ...] = ()
    websocket_path: str = ""

    @classmethod
    def from_dict(cls, value: dict):
        slug = validate_slug(value["slug"])
        path = Path(value["package"]).resolve(strict=True)
        manifest = validate_package(path, slug)
        mode = manifest.get("delivery", {}).get("mode", "source-image")
        if value.get("mode", mode) != mode or mode not in {"bundle", "image", "source-image"}:
            raise ValueError("scenario delivery mode must match the frozen package")
        update = Path(value["update"]).resolve(strict=True) if value.get("update") else None
        if update:
            update_manifest = validate_package(update, slug)
            if (
                update_manifest.get("runtime") != manifest["runtime"]
                or update_manifest.get("delivery", {}).get("mode", "source-image") != mode
            ):
                raise ValueError("update must retain scenario runtime and delivery mode")
        entry_path = value.get("entry_path", "/")
        if not entry_path.startswith("/") or entry_path.startswith("//") or "?" in entry_path:
            raise ValueError("entry_path must be an application-relative path")
        application_checks = tuple(value.get("application_checks", []))
        for check in application_checks:
            check_path = check.get("path", "")
            if not check_path.startswith("/") or check_path.startswith("//") or "?" in check_path:
                raise ValueError("application check must use a relative path")
            if not isinstance(check.get("expected_json"), dict) or not check["expected_json"]:
                raise ValueError("application check needs nonempty expected_json")
        websocket_path = value.get("websocket_path", "")
        if websocket_path and (
            not websocket_path.startswith("/") or websocket_path.startswith("//") or "?" in websocket_path
        ):
            raise ValueError("WebSocket check must use a relative path")
        return cls(
            slug,
            path,
            mode,
            manifest["runtime"],
            update,
            value.get("table", ""),
            str(value.get("row_key", "1")),
            value.get("update_values"),
            entry_path,
            value.get("expected_text", ""),
            value.get("expected_failure_code"),
            value.get("expected_failure_stage"),
            application_checks,
            websocket_path,
        )


@dataclass(frozen=True)
class SuiteSettings:
    tenant_code: str
    scenarios: tuple[Scenario, ...]
    timeout: float = 600
    executor_kind: str = "kubernetes"

    @classmethod
    def from_env(cls):
        tenant = os.environ.get("F059_E2E_TENANT_CODE", "")
        validate_slug(tenant)
        if os.environ.get("F059_E2E") != "1":
            raise ValueError("F059_E2E=1 is required for live execution")
        api = urlsplit(API_BASE)
        if api.scheme not in {"http", "https"} or not api.netloc or api.username or api.password:
            raise ValueError("E2E_API_BASE must be an HTTP(S) platform API address")
        if not api.path.rstrip("/").endswith("/api/v1"):
            raise ValueError("E2E_API_BASE must end in /api/v1")
        raw = json.loads(Path(required("F059_E2E_SCENARIOS")).read_text())
        scenarios = tuple(Scenario.from_dict(item) for item in raw)
        if not scenarios or len({item.slug for item in scenarios}) != len(scenarios):
            raise ValueError("nonempty scenarios with distinct exact slugs are required")
        timeout = float(os.environ.get("F059_E2E_TIMEOUT", "600"))
        if not 30 <= timeout <= 1800:
            raise ValueError("F059_E2E_TIMEOUT must be between 30 and 1800 seconds")
        executor = os.environ.get("F059_E2E_EXECUTOR", "kubernetes")
        if executor not in {"docker", "kubernetes"}:
            raise ValueError("F059_E2E_EXECUTOR must be docker or kubernetes")
        return cls(tenant, scenarios, timeout, executor)


class EvidenceJournal:
    """Exact-scope resumable IDs and non-secret evidence, never a source of trust."""

    def __init__(self, path: Path, *, tenant_code: str):
        validate_slug(tenant_code)
        self.path = path
        self.document = {"schema_version": 1, "tenant_code": tenant_code, "apps": {}, "events": []}
        if path.exists():
            self.document = json.loads(path.read_text())
            if self.document.get("schema_version") != 1 or self.document.get("tenant_code") != tenant_code:
                raise ValueError("evidence journal scope mismatch")
            for slug in self.document["apps"]:
                validate_slug(slug)

    def record(self, name, acs, outcome, **facts):
        def reject_secrets(value):
            if isinstance(value, dict):
                for key, item in value.items():
                    if any(word in str(key).lower() for word in SECRET_KEYS):
                        raise ValueError("secret fields cannot enter the evidence journal")
                    reject_secrets(item)
            elif isinstance(value, (list, tuple)):
                for item in value:
                    reject_secrets(item)

        reject_secrets(facts)
        self.document["events"].append(
            {"name": name, "acs": acs, "outcome": outcome, "kind": "live-api", "observed_at": time.time(), **facts}
        )
        self.save()

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="w", prefix=self.path.name + ".", dir=self.path.parent, delete=False
        ) as stream:
            temporary = Path(stream.name)
            os.fchmod(stream.fileno(), 0o600)
            json.dump(self.document, stream, indent=2, ensure_ascii=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, self.path)


class LiveVibeSuite:
    def __init__(self, settings: SuiteSettings, journal: EvidenceJournal, client: httpx.AsyncClient):
        self.settings, self.journal, self.client = settings, journal, client
        self.tokens: dict[str, str] = {}
        self.users: dict[str, int] = {}
        self.tenant_id = 0

    async def request(self, method, path, *, role="OWNER", expected_code=None, **kwargs):
        url = API_BASE.rstrip("/") + path
        response = await self.client.request(method, url, headers=auth_headers(self.tokens[role]), **kwargs)
        body = response.json()
        assert {"status_code", "status_message", "data"} <= body.keys(), "missing platform response envelope"
        if expected_code is not None:
            assert response.status_code == 200, "business refusals must preserve the platform envelope HTTP status"
            return assert_resp_error(response, expected_code)
        assert response.status_code in {200, 202}, f"unexpected HTTP status: {response.status_code}"
        if response.status_code == 202:
            assert body["status_code"] == 200
            return body["data"]
        return assert_resp_200(response)

    async def authenticate(self):
        self.tokens["ADMIN"] = await get_admin_token(self.client)
        tenant = await ensure_test_tenant(self.client, self.tokens["ADMIN"], self.settings.tenant_code)
        assert tenant.get("id") and tenant["tenant_code"] == self.settings.tenant_code
        self.tenant_id = int(tenant["id"])
        assert self.tenant_id != 1, "root tenant is never an F059 test tenant"
        for role in ROLES:
            username = required(f"F059_E2E_{role}_USERNAME")
            assert username.startswith(PREFIX), "all live identities must be dedicated e2e-f059- users"
            self.tokens[role] = await get_user_token(self.client, username, required(f"F059_E2E_{role}_PASSWORD"))
            identity = await self.request("GET", "/user/info", role=role)
            self.users[role] = int(identity.get("user_id") or identity["id"])
            scope = await self.request("GET", "/user/current-tenant", role=role)
            actual = int(scope["leaf_tenant_id"])
            assert (actual != self.tenant_id) if role == "FOREIGN" else (actual == self.tenant_id)
            assert not identity.get("is_global_super"), "business identities must not bypass tenant authorization"
        assert len(set(self.users.values())) == len(ROLES), "allow/deny identities must be distinct users"
        self.open_api_key = required("F059_E2E_OWNER_API_KEY")
        whoami = await self.client.get(
            API_BASE.rsplit("/api/v1", 1)[0] + "/api/v2/auth/whoami",
            headers={"Authorization": "Bearer " + self.open_api_key},
        )
        assert {"status_code", "status_message", "data"} <= whoami.json().keys()
        principal = assert_resp_200(whoami)
        assert principal["mode"] == "S" and "app:manage" in principal["scopes"]
        assert int(principal["tenant_id"]) == self.tenant_id
        assert int(principal["resource_owner"]["user_id"]) == self.users["OWNER"]

    async def poll(self, reader, predicate, *, description, timeout=None):
        deadline = time.monotonic() + (timeout or self.settings.timeout)
        while True:
            value = await reader()
            if predicate(value):
                return value
            if time.monotonic() >= deadline:
                raise AssertionError(f"timed out waiting for {description}")
            await asyncio.sleep(2)

    async def installation(self):
        """AC-01, AC-30, AC-32: public diagnostics, without substituting for cluster probes."""
        status = await self.request("GET", "/apps/runtime-status", role="ADMIN")
        assert status["executor_kind"] == self.settings.executor_kind and status["protocol_version"] == 2
        assert status["ready"] and status["backend_available"]
        assert status["preflight"] and all(check["ok"] for check in status["preflight"])
        await self.request("GET", "/apps/runtime-status", expected_code=16106)
        profiles = await self.request("GET", "/runtime/profiles")
        defaults = await self.request("GET", "/runtime/profiles/defaults")
        assert profiles and defaults
        self.journal.record(
            "runtime-diagnostics",
            ["AC-01", "AC-30", "AC-32"],
            "passed",
            executor_kind=status["executor_kind"],
            checks=[item["name"] for item in status["preflight"]],
        )

    async def owned(self, app_id, slug):
        detail = await self.request("GET", f"/apps/{app_id}")
        assert detail["app_id"] == app_id and detail["slug"] == validate_slug(slug)
        assert detail["name"].startswith(PREFIX)
        assert int(detail["tenant_id"]) == self.tenant_id and int(detail["owner_user_id"]) == self.users["OWNER"]
        return detail

    async def cleanup(self):
        """Delete only configured exact slugs, after fresh tenant and owner checks."""
        allowed = {scenario.slug for scenario in self.settings.scenarios}
        apps = await self.request("GET", "/apps")
        for item in apps:
            if item.get("slug") not in allowed:
                continue
            app_id, slug = item["app_id"], item["slug"]
            detail = await self.owned(app_id, slug)
            if detail["state"] == "online":
                await self.request("POST", f"/apps/{app_id}/actions/stop")
                await self.poll(
                    lambda app_id=app_id, slug=slug: self.owned(app_id, slug),
                    lambda value: value["state"] == "stopped",
                    description="cleanup stop confirmation",
                )
            await self.request("DELETE", f"/apps/{app_id}")
            await self.request("GET", f"/apps/{app_id}", expected_code=16101)
            self.journal.document["apps"].pop(slug, None)
            self.journal.record("cleanup", ["AC-35", "AC-55"], "passed", app_id=app_id, slug=slug)

    async def deploy(self, scenario, *, update=False):
        path = scenario.update if update else scenario.package
        previous = self.journal.document["apps"].get(scenario.slug)
        if update:
            assert previous, "an update requires this suite's recorded first deployment"
            await self.owned(previous["app_id"], scenario.slug)
        endpoint = API_BASE.rsplit("/api/v1", 1)[0] + "/api/v2/apps/deploy"
        form = {"app_id": previous["app_id"]} if update else {}
        with path.open("rb") as stream:
            response = await self.client.post(
                endpoint,
                headers={"Authorization": "Bearer " + self.open_api_key},
                data=form,
                files={"package": (path.name, stream, "application/gzip")},
            )
        assert {"status_code", "status_message", "data"} <= response.json().keys()
        accepted = assert_resp_200(response)
        app_id = accepted["app_id"]
        record = {key: accepted[key] for key in ["app_id", "deployment_id", "version_id"]}
        record.update({"mode": scenario.mode, "runtime": scenario.runtime})
        self.journal.document["apps"][scenario.slug] = record
        self.journal.save()
        await self.owned(app_id, scenario.slug)
        status_url = endpoint.rsplit("/deploy", 1)[0] + "/deployments/" + accepted["deployment_id"]

        async def read():
            response = await self.client.get(status_url, headers={"Authorization": "Bearer " + self.open_api_key})
            assert {"status_code", "status_message", "data"} <= response.json().keys()
            return assert_resp_200(response)

        deployment = await self.poll(
            read,
            lambda value: value["status"] == "failed" or value.get("approval") is not None,
            description="publication precheck and approval",
        )
        if scenario.expected_failure_code is not None:
            assert deployment["status"] == "failed" and deployment["approval"] is None
            assert deployment["failure"]["code"] == scenario.expected_failure_code
            assert deployment["failure"]["stage"] == scenario.expected_failure_stage
            versions = await self.request("GET", f"/apps/{app_id}/versions")
            assert not any(item["version_id"] == accepted["version_id"] for item in versions["data"])
            self.journal.record(
                "preapproval-failure",
                ["AC-08", "AC-09", "AC-28"],
                "passed",
                app_id=app_id,
                stage=deployment["failure"]["stage"],
                code=deployment["failure"]["code"],
            )
            return record
        assert deployment["status"] != "failed", "publication failed; inspect the platform's deployment failure"
        await self.preview_and_approve(record)
        await self.poll(
            lambda: self.owned(app_id, scenario.slug),
            lambda value: value["state"] == "online" and value["current_version_id"] == record["version_id"],
            description="approved version online",
        )
        final = await read()
        assert final["app_state"] == "online" and final["version_id"] == record["version_id"]
        self.journal.record(
            "iteration" if update else "publish",
            ["AC-04", "AC-05", "AC-24", "AC-25", "AC-36"],
            "passed",
            **record,
            package_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
        )
        return record

    async def preview_and_approve(self, record):
        app_id, version = record["app_id"], record["version_id"]
        status = await self.request("GET", f"/apps/{app_id}/publish-status")
        approval = status["approval"]
        assert approval and approval["status"] == "pending", (
            "configure a distinct human approver; auto-approval skips this journey"
        )
        path = f"/apps/{app_id}/versions/{version}/preview"
        await self.request("POST", path, role="NONOWNER", expected_code=16264)
        preview = await self.request("POST", path, role="APPROVER")
        current = await self.request("GET", path, role="APPROVER")
        assert current["session_id"] == preview["session_id"] and current["entry_url"]
        await self.request("DELETE", path + "/" + preview["session_id"], role="APPROVER")
        closed = await self.request("GET", path, role="APPROVER")
        assert closed["state"] != "running"
        tasks = await self.request("GET", "/approval/my-tasks", role="APPROVER")
        pending = [
            item
            for item in tasks["data"]
            if item["instance_id"] == approval["instance_id"] and item["status"] == "pending"
        ]
        assert len(pending) == 1, "configure one approval node with the one dedicated approver"
        for task in pending:
            path = f"/approval/tasks/{task['task_id']}/decision"
            await self.request(
                "POST",
                path,
                role="NONOWNER",
                expected_code=18101,
                json={"action": "approve", "comment": "e2e-f059-denied"},
            )
            await self.request("POST", path, role="APPROVER", json={"action": "approve", "comment": "e2e-f059-review"})
            detail = await self.request("GET", f"/approval/my-tasks/{task['task_id']}", role="APPROVER")
            assert detail["status"] == "approved"
        self.journal.record(
            "preview-and-approval",
            ["AC-05", "AC-36", "AC-50"],
            "passed",
            app_id=app_id,
            instance_id=approval["instance_id"],
            session_id=preview["session_id"],
        )

    async def observe(self, scenario):
        """AC-10, AC-33, AC-36, AC-46: management and proxy boundaries."""
        record = self.journal.document["apps"][scenario.slug]
        app_id = record["app_id"]
        detail = await self.owned(app_id, scenario.slug)
        assert detail["state"] == "online"
        await self.request("GET", f"/apps/{app_id}/instance")
        logs = await self.request("GET", f"/apps/{app_id}/logs", params={"tail": 20, "since": "5m"})
        assert "lines" in logs
        await self.request("GET", f"/apps/{app_id}", role="NONOWNER", expected_code=16106)
        await self.request("GET", f"/apps/{app_id}", role="FOREIGN", expected_code=16101)
        await self.request("GET", f"/apps/{app_id}/logs", role="NONOWNER", expected_code=16161)
        await self.request("GET", f"/apps/{app_id}/runtime/snapshots")
        for role in ["NONOWNER", "FOREIGN"]:
            await self.request("GET", f"/apps/{app_id}/runtime/snapshots", role=role, expected_code=16105)
            await self.request(
                "GET", f"/apps/{app_id}/data/tables", role=role, expected_code=16101 if role == "FOREIGN" else 16162
            )
        entry = detail["entry_url"].rstrip("/") + scenario.entry_path
        actual_origin, expected_origin = urlsplit(entry), urlsplit(required("F059_E2E_ENTRY_BASE"))
        assert (actual_origin.scheme, actual_origin.netloc) == (expected_origin.scheme, expected_origin.netloc), (
            "entry must use the exact configured gateway origin"
        )
        assert actual_origin.scheme in {"http", "https"} and not actual_origin.username and not actual_origin.password
        response = await self.client.get(entry, headers=auth_headers(self.tokens["OWNER"]))
        assert response.status_code == 200 and scenario.expected_text in response.text
        unauthenticated = await self.client.get(entry, headers={"Cookie": ""})
        assert unauthenticated.status_code == 401
        assert unauthenticated.json()["status_code"] == 16141
        for check in scenario.application_checks:
            checked = await self.client.get(
                detail["entry_url"].rstrip("/") + check["path"], headers=auth_headers(self.tokens["OWNER"])
            )
            assert checked.status_code == 200
            body = checked.json()
            assert all(body.get(key) == value for key, value in check["expected_json"].items())
            self.journal.record("application-check", ["AC-36", "AC-46"], "passed", app_id=app_id, path=check["path"])
        if scenario.websocket_path:
            await self.websocket(scenario, detail["entry_url"])
        if scenario.table:
            await self.data_roundtrip(scenario, app_id)
        self.journal.record(
            "owner-and-entry-boundaries",
            ["AC-10", "AC-12", "AC-33", "AC-36", "AC-46"],
            "passed",
            app_id=app_id,
            entry_status=response.status_code,
        )

    async def websocket(self, scenario, entry):
        from websockets.asyncio.client import connect
        from websockets.exceptions import InvalidStatus

        uri = entry.rstrip("/") + scenario.websocket_path
        uri = ("wss://" if uri.startswith("https://") else "ws://") + uri.split("://", 1)[1]
        async with connect(
            uri, additional_headers=auth_headers(self.tokens["OWNER"]), proxy=None, open_timeout=15
        ) as socket:
            await socket.send("e2e-f059-echo")
            assert await asyncio.wait_for(socket.recv(), timeout=15) == "e2e-f059-echo"
        try:
            async with connect(
                uri, additional_headers=auth_headers(self.tokens["NONOWNER"]), proxy=None, open_timeout=15
            ):
                raise AssertionError("nonowner WebSocket must be refused before upgrade")
        except InvalidStatus as exc:
            assert exc.response.status_code == 403
        self.journal.record("websocket-allow-deny", ["AC-12", "AC-36", "AC-53"], "passed", slug=scenario.slug)

    async def rows(self, scenario, app_id):
        return await self.request("GET", f"/apps/{app_id}/data/tables/{quote(scenario.table, safe='')}/rows")

    async def data_roundtrip(self, scenario, app_id):
        tables = await self.request("GET", f"/apps/{app_id}/data/tables")
        assert scenario.table in json.dumps(tables)
        table_path = f"/apps/{app_id}/data/tables/{quote(scenario.table, safe='')}"
        await self.request("GET", table_path + "/schema")
        await self.rows(scenario, app_id)
        if scenario.update_values:
            path = table_path + "/rows/" + quote(scenario.row_key, safe="")
            await self.request("PATCH", path, json={"values": scenario.update_values})
            for role in ["NONOWNER", "FOREIGN"]:
                await self.request(
                    "PATCH",
                    path,
                    role=role,
                    expected_code=16101 if role == "FOREIGN" else 16162,
                    json={"values": scenario.update_values},
                )
            after = await self.rows(scenario, app_id)
            assert all(str(value) in json.dumps(after) for value in scenario.update_values.values())
        response = await self.client.get(
            API_BASE + f"/apps/{app_id}/data/export",
            params={"table": scenario.table},
            headers=auth_headers(self.tokens["OWNER"]),
        )
        assert response.status_code == 200 and response.headers["content-type"].startswith("text/csv")
        assert response.content
        for role in ["NONOWNER", "FOREIGN"]:
            await self.request(
                "GET",
                f"/apps/{app_id}/data/export",
                role=role,
                expected_code=16101 if role == "FOREIGN" else 16162,
                params={"table": scenario.table},
            )

    async def cycle(self, scenario):
        """AC-29, AC-33, AC-35: stop/resume preserves committed SQLite rows."""
        app_id = self.journal.document["apps"][scenario.slug]["app_id"]
        before = await self.rows(scenario, app_id) if scenario.table else None
        await self.request("POST", f"/apps/{app_id}/actions/stop", role="NONOWNER", expected_code=16106)
        await self.request("POST", f"/apps/{app_id}/actions/stop")
        stopped = await self.owned(app_id, scenario.slug)
        assert stopped["state"] == "stopped"
        await self.request("POST", f"/apps/{app_id}/actions/resume", role="NONOWNER", expected_code=16106)
        await self.request("POST", f"/apps/{app_id}/actions/resume")
        await self.poll(
            lambda: self.owned(app_id, scenario.slug),
            lambda value: value["state"] == "online",
            description="resumed online application",
        )
        if scenario.table:
            assert await self.rows(scenario, app_id) == before
        self.journal.record("stop-resume", ["AC-29", "AC-33", "AC-35", "AC-36"], "passed", app_id=app_id)

    async def checkpoint(self, event, *, verify=False):
        """Observe an operator-driven restart/upgrade; never inject faults concurrently."""
        if event not in {"manager-restart", "runtime-upgrade", "app-restart"}:
            raise ValueError("checkpoint supports manager-restart, runtime-upgrade or app-restart")
        key = "checkpoint:" + event
        results = {}
        for scenario in self.settings.scenarios:
            if scenario.expected_failure_code is not None:
                continue
            record = self.journal.document["apps"][scenario.slug]
            app_id = record["app_id"]
            detail = await self.owned(app_id, scenario.slug)
            results[scenario.slug] = {
                "app_id": app_id,
                "version_id": detail["current_version_id"],
                "instance": await self.request("GET", f"/apps/{app_id}/instance"),
                "rows": await self.rows(scenario, app_id) if scenario.table else None,
            }
            if verify:
                await self.observe(scenario)
        if not verify:
            self.journal.document[key] = {"observed_at": time.time(), "apps": results}
            self.journal.save()
            return
        before = self.journal.document[key]
        assert time.time() - before["observed_at"] <= self.settings.timeout, (
            "checkpoint exceeded configured recovery deadline"
        )
        for slug, current in results.items():
            old = before["apps"][slug]
            assert current["version_id"] == old["version_id"] and current["rows"] == old["rows"]
            if event != "app-restart":
                assert current["instance"]["instance_id"] == old["instance"]["instance_id"], (
                    "control upgrade rebuilt an application"
                )
        # This proves API observations only. The installer/operator must attach
        # the actual changed deployment/Pod UID and fault timestamps separately.
        self.journal.record(
            "checkpoint-observation",
            ["AC-06", "AC-07", "AC-33", "AC-40", "AC-55"],
            "passed",
            event=event,
            injection_verified=False,
            apps=list(results),
        )

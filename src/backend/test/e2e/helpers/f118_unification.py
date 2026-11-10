"""Real HTTP fixtures for F118; never import an in-process app or mock a provider.

Required opt-in environment (no defaults to a running developer server):
F118_E2E=1, F118_E2E_ENVIRONMENT=f118-e2e, E2E_API_BASE,
F118_E2E_READY_SHA (the operator-verified deployed commit), F118_E2E_RUN_ID,
F118_E2E_PARENT_DEPARTMENT_ID, F118_E2E_MEMBER_PASSWORD,
F118_E2E_AUTH_FILE and F118_E2E_MODEL_FIXTURE_FILE.

The private auth JSON contains either access_token or username/password. The
private model JSON contains an actual LLMServerCreateReq as ``server``, two
``embedding_model_names`` and ``chat_model_name`` matching its vendor model_name
values. Its URL/type/config must come from the dedicated environment owner.
No provider endpoint, model key, credentials or mock response is invented here.

Dedicated tenant/people are retained for repeatability and audit. Setup and
teardown remove only the exact business names below after tenant/owner checks.
They never clear a tenant, delete old migration samples or force a blocked plan.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import time
from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

import httpx

from test.e2e.helpers.api import API_BASE, assert_resp_200, assert_resp_error
from test.e2e.helpers.auth import auth_headers, encrypt_password, get_public_key, get_user_token

RESOURCE_NAMES = (
    "native",
    "legacy",
    "qa",
    "default-a",
    "default-b",
    "permissions",
    "rules",
    "four-kinds",
    "versions",
    "delete-files",
    "clear",
    "delete-space",
)


def required(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise ValueError(f"{name} must be explicit for F118 E2E")
    return value


def private_json(variable: str) -> dict:
    path = Path(required(variable))
    if path.stat().st_mode & 0o077:
        raise ValueError(f"{variable} must reference an owner-only private file")
    value = json.loads(path.read_text())
    if not isinstance(value, dict):
        raise ValueError(f"{variable} must contain a JSON object")
    return value


@dataclass(repr=False)
class F118Environment:
    client: httpx.AsyncClient
    run_id: str
    parent_id: int
    member_password: str = field(repr=False)
    credentials: dict = field(repr=False)
    model_fixture: dict = field(repr=False)
    root: dict = field(default_factory=dict, repr=False)
    owner: dict = field(default_factory=dict, repr=False)
    reader: dict = field(default_factory=dict, repr=False)
    outsider: dict = field(default_factory=dict, repr=False)
    owner_id: int = 0
    reader_id: int = 0
    tenant_id: int = 0
    server_id: int | None = None
    models: dict = field(default_factory=dict, repr=False)
    timeout: float = 180
    events: list[dict] = field(default_factory=list)

    @classmethod
    def from_environment(cls, client):
        if required("F118_E2E_ENVIRONMENT") != "f118-e2e":
            raise ValueError("Only the isolated f118-e2e deployment is permitted")
        base = required("E2E_API_BASE").rstrip("/")
        parsed = urlsplit(base)
        if (
            parsed.scheme not in {"http", "https"}
            or parsed.port == 3005
            or parsed.path != "/api/v1"
            or parsed.username is not None
            or parsed.password is not None
        ):
            raise ValueError("An explicit isolated API /api/v1 URL is required; port 3005 is forbidden")
        if base != API_BASE.rstrip("/"):
            raise ValueError("E2E_API_BASE must be exported before importing shared API helpers")
        if not re.fullmatch(r"[0-9a-f]{40}", required("F118_E2E_READY_SHA")):
            raise ValueError("F118_E2E_READY_SHA must record the operator-verified deployed commit")
        run_id = required("F118_E2E_RUN_ID")
        if not re.fullmatch(r"[a-z0-9]{1,12}", run_id) or os.environ.get("PYTEST_XDIST_WORKER"):
            raise ValueError("Use a serial run with a stable 1-12 character lowercase alphanumeric run ID")
        return cls(
            client=client,
            run_id=run_id,
            parent_id=int(required("F118_E2E_PARENT_DEPARTMENT_ID")),
            member_password=required("F118_E2E_MEMBER_PASSWORD"),
            credentials=private_json("F118_E2E_AUTH_FILE"),
            model_fixture=private_json("F118_E2E_MODEL_FIXTURE_FILE"),
            timeout=float(os.environ.get("F118_E2E_TIMEOUT_SECONDS", "180")),
        )

    @property
    def prefix(self):
        return f"e2e-f118-{self.run_id}-"

    def name(self, suffix):
        assert suffix in RESOURCE_NAMES
        return self.prefix + suffix

    async def request(self, method, path, *, actor=None, **kwargs):
        response = await self.client.request(method, API_BASE + path, headers=actor or self.owner, **kwargs)
        body = response.json()
        assert isinstance(body, dict) and "status_code" in body and "status_message" in body
        # The existing main.py validation handler intentionally has no data key.
        if body["status_code"] != 422:
            assert "data" in body
        return response

    async def ok(self, method, path, **kwargs):
        return assert_resp_200(await self.request(method, path, **kwargs))

    async def error(self, method, path, code, **kwargs):
        return assert_resp_error(await self.request(method, path, **kwargs), code)

    async def prepare(self):
        if self.credentials.get("access_token"):
            token = self.credentials["access_token"]
        else:
            token = await get_user_token(self.client, self.credentials["username"], self.credentials["password"])
        self.root = auth_headers(token)
        info = await self.ok("GET", "/user/info", actor=self.root)
        assert info["role"] == "admin" and not info.get("is_child_admin")
        self.root["X-Management-Tenant"] = str(info["leaf_tenant_id"])
        code = self.prefix + "tenant"
        candidates = await self.ok("GET", "/tenants/", actor=self.root, params={"keyword": code, "page_size": 100})
        exact = [row for row in candidates["data"] if row["tenant_code"] == code]
        assert len(exact) <= 1
        if exact:
            tenant = await self.ok("GET", f"/tenants/{exact[0]['id']}", actor=self.root)
            department = await self.ok("GET", f"/departments/{tenant['root_dept_id']}", actor=self.root)
        else:
            siblings = await self.ok(
                "GET", "/departments/children", actor=self.root, params={"parent_id": self.parent_id}
            )
            existing = [row for row in siblings if row["name"] == code]
            assert len(existing) <= 1
            department = (
                existing[0]
                if existing
                else await self.ok(
                    "POST",
                    "/departments/",
                    actor=self.root,
                    json={"name": code, "parent_id": self.parent_id, "default_role_ids": []},
                )
            )
            tenant = await self.ok(
                "POST",
                f"/departments/{department['id']}/mount-tenant",
                actor=self.root,
                json={"tenant_name": code, "tenant_code": code},
            )
        assert department["name"] == code and department["parent_id"] == self.parent_id
        self.tenant_id = int(tenant["id"])
        assert self.tenant_id > 1 and tenant["tenant_code"] == code
        people = {}
        public_key = await get_public_key(self.client)
        for role in ("owner", "reader", "outsider"):
            account = self.prefix + role
            page = await self.ok(
                "GET",
                f"/departments/{department['dept_id']}/members",
                actor=self.root,
                params={"keyword": account, "limit": 100},
            )
            matches = [row for row in page["data"] if row["user_name"] == account]
            assert len(matches) <= 1
            person = (
                matches[0]
                if matches
                else await self.ok(
                    "POST",
                    f"/departments/{department['dept_id']}/local-members",
                    actor=self.root,
                    json={
                        "user_name": account,
                        "person_id": account,
                        "password": encrypt_password(self.member_password, public_key),
                        "role_ids": [],
                    },
                )
            )
            people[role] = int(person["user_id"])
        await self.ok("POST", f"/tenants/{self.tenant_id}/admins", actor=self.root, json={"user_id": people["owner"]})
        for role in people:
            token = await get_user_token(self.client, self.prefix + role, self.member_password)
            headers = auth_headers(token)
            identity = await self.ok("GET", "/user/info", actor=headers)
            assert identity["leaf_tenant_id"] == self.tenant_id
            assert identity["user_name"] == self.prefix + role
            assert identity["role"] != "admin"
            assert bool(identity.get("is_child_admin")) == (role == "owner")
            setattr(self, role, headers)
        self.owner["X-Management-Tenant"] = str(self.tenant_id)
        self.owner_id, self.reader_id = people["owner"], people["reader"]
        await self.clean_business_resources()
        await self.remove_fixture_server()
        payload = deepcopy(self.model_fixture["server"])
        assert "id" not in payload and len(payload["models"]) == 3
        payload.update(name=self.prefix + "provider", share_to_children=False)
        expected = [*self.model_fixture["embedding_model_names"], self.model_fixture["chat_model_name"]]
        assert len(set(expected)) == 3 and {row["model_name"] for row in payload["models"]} == set(expected)
        for index, model in enumerate(payload["models"]):
            assert "id" not in model
            model["name"] = self.prefix + f"model-{index}"
        server = await self.ok("POST", "/llm", json=payload)
        self.server_id = int(server["id"])
        actual = await self.ok("GET", "/llm/info", params={"server_id": self.server_id})
        assert actual["tenant_id"] == self.tenant_id and actual["user_id"] == self.owner_id
        self.models = {row["model_name"]: row for row in actual["models"]}
        assert set(self.models) == set(expected)
        assert all(self.models[name]["model_type"] == "embedding" for name in expected[:2])
        assert self.models[expected[2]]["model_type"] == "llm"
        for model in self.models.values():
            probed = await self.ok("POST", "/llm/verify", json={"model_id": model["id"]})
            assert probed["id"] == model["id"] and probed["status"] == 0
        verified = await self.ok("GET", "/llm/info", params={"server_id": self.server_id})
        assert all(model["status"] == 0 for model in verified["models"])
        await self.set_workbench(self.embedding(0))

    def embedding(self, index):
        return self.models[self.model_fixture["embedding_model_names"][index]]

    async def set_workbench(self, embedding):
        chat = self.models[self.model_fixture["chat_model_name"]]
        await self.ok(
            "POST",
            "/llm/workbench",
            json={
                "models": [{"id": str(chat["id"]), "name": chat["name"]}],
                "chat_default_model_id": str(chat["id"]),
                "linsight_default_model_id": str(chat["id"]),
                "embedding_model": {"id": str(embedding["id"]), "name": embedding["name"]} if embedding else None,
            },
        )
        stored = (await self.ok("GET", "/llm/workbench/settings"))["data"]
        assert (stored["embedding_model"]["id"] if stored["embedding_model"] else None) == (
            str(embedding["id"]) if embedding else None
        )

    async def space(self, suffix, *, legacy_type=None, **advanced):
        payload = {"name": self.name(suffix), "auth_type": "private", "is_released": False}
        if legacy_type is None:
            result = await self.ok("POST", "/knowledge/space", json={**payload, **advanced})
        else:
            result = await self.ok(
                "POST",
                "/knowledge/create",
                json={
                    **payload,
                    "type": legacy_type,
                    "model": str(self.embedding(0)["id"]),
                    "expected_tenant_id": self.tenant_id,
                },
            )
        assert result["tenant_id"] == self.tenant_id and result["user_id"] == self.owner_id
        assert result["name"] == self.name(suffix)
        return result

    async def info(self, space_id, *, actor=None):
        return await self.ok("GET", f"/knowledge/space/{space_id}/info", actor=actor)

    async def files(self, space_id, *, actor=None, **params):
        return await self.ok(
            "GET", f"/knowledge/space/{space_id}/children", actor=actor, params={"page_size": 200, **params}
        )

    async def file(self, space_id, file_id):
        # This reader follows the legacy primary-file list; history uses the version API.
        page = await self.ok(
            "GET", f"/knowledge/file_list/{space_id}", params={"file_ids": [file_id], "page_size": 200}
        )
        rows = [row for row in page["data"] if row["id"] == file_id]
        assert len(rows) == 1
        return rows[0]

    async def wait_file(self, space_id, file_id):
        deadline = time.monotonic() + self.timeout
        while time.monotonic() < deadline:
            row = await self.file(space_id, file_id)
            if row["status"] in {2, 3, 6, 7}:
                assert row["status"] == 2, f"file {file_id} ended with status {row['status']}"
                return row
            await asyncio.sleep(1)
        raise AssertionError(f"file {file_id} did not reach a terminal state")

    async def upload(self, space_id, name, content, *, overrides=None, wait=True):
        staged = await self.ok("POST", "/knowledge/upload", files={"file": (self.prefix + name, content, "text/plain")})
        payload = {"file_path": [staged["file_path"]]}
        if overrides is not None:
            payload["overrides"] = overrides
        rows = await self.ok("POST", f"/knowledge/space/{space_id}/files", json=payload)
        assert len(rows) == 1 and rows[0]["knowledge_id"] == space_id
        return await self.wait_file(space_id, rows[0]["id"]) if wait else rows[0]

    async def processing(self, space_id, kind, parameters, targets=None):
        payload = {"kind": kind, "parameters": parameters}
        if targets is not None:
            payload["targets"] = targets
        plan = await self.ok("POST", f"/knowledge/space/{space_id}/processing-jobs/precheck", json=payload)
        assert plan["check_complete"] is True and plan["can_execute"] is True
        command = self.confirmation(plan)
        accepted = await self.ok("POST", f"/knowledge/space/{space_id}/processing-jobs", json=command)
        assert accepted["accepted"] is True and accepted["job_id"]
        deadline = time.monotonic() + self.timeout
        while time.monotonic() < deadline:
            job = await self.ok("GET", f"/knowledge/space/{space_id}/processing-jobs/{accepted['job_id']}")
            assert job["kind"] == kind and job["space_id"] == space_id
            if job["state"] in {"succeeded", "failed", "partial_failed", "obsolete"}:
                assert job["state"] == "succeeded", f"{kind} ended as {job['state']} code={job.get('error_code')}"
                assert job["total_count"] > 0 and job["succeeded_count"] == job["total_count"]
                assert job["failed_count"] == job["pending_count"] == 0
                items = await self.ok(
                    "GET", f"/knowledge/space/{space_id}/processing-jobs/{job['id']}/items", params={"page_size": 200}
                )
                assert len(items["data"]) == job["total_count"] and all(
                    row["state"] == "succeeded" for row in items["data"]
                )
                self.events.append({"space_id": space_id, "kind": kind, "job_id": job["id"], "state": job["state"]})
                return job
            await asyncio.sleep(1)
        raise AssertionError(f"{kind} did not reach a terminal state")

    @staticmethod
    def confirmation(plan):
        assert re.fullmatch(r"[0-9a-f]{64}", plan["plan_digest"])
        return {
            "confirmation_id": plan["confirmation_id"],
            "plan_digest": plan["plan_digest"],
            "idempotency_key": uuid4().hex,
        }

    async def delete(self, space_id, *, items=None, clear=False):
        base = f"/knowledge/space/{space_id}"
        suffix = "files/delete/precheck" if items is not None else "clear/precheck" if clear else "delete/precheck"
        plan = await self.ok("POST", f"{base}/{suffix}", json={"items": items} if items is not None else {})
        assert plan["check_complete"] is True and plan["can_execute"] is True
        assert not plan["invalid_items"] and not plan["requires_skip_confirmation"]
        command = self.confirmation(plan)
        accepted = await self.ok("POST", f"{base}/deletion/confirm", json=command)
        deadline = time.monotonic() + self.timeout
        while time.monotonic() < deadline:
            state = await self.ok("GET", f"{base}/deletion/{accepted['job_id']}")
            if state["state"] in {"succeeded", "failed"}:
                assert state["state"] == "succeeded" and state["business_phase"] == "finalized"
                return command
            await asyncio.sleep(1)
        raise AssertionError("deletion did not finalize")

    async def clean_business_resources(self):
        if not self.owner:
            return
        allowed = {self.name(name) for name in RESOURCE_NAMES}
        cursor = None
        rows = []
        for _ in range(100):
            page = await self.ok(
                "GET",
                "/knowledge/space/list",
                params={"keyword": self.prefix, "page_size": 200, **({"cursor": cursor} if cursor else {})},
            )
            rows.extend(page["data"])
            if not page["has_more"]:
                break
            next_cursor = page["next_cursor"]
            assert next_cursor and next_cursor != cursor
            cursor = next_cursor
        else:
            raise AssertionError("cleanup pagination incomplete; no rows were deleted")
        for row in rows:
            if row["name"] not in allowed:
                continue
            facts = await self.info(row["id"])
            assert (
                facts["tenant_id"] == self.tenant_id and facts["user_id"] == self.owner_id and facts["name"] in allowed
            )
            await self.delete(row["id"])
            await self.error("GET", f"/knowledge/space/{row['id']}/info", 18000)
        page = await self.ok("GET", "/knowledge", params={"type": 1, "name": self.name("qa"), "page_size": 200})
        assert not page["has_more"]
        for row in page["data"]:
            if row["name"] == self.name("qa"):
                assert row["type"] == 1 and row["tenant_id"] == self.tenant_id and row["user_id"] == self.owner_id
                await self.ok("DELETE", "/knowledge/", json={"knowledge_id": row["id"]})

    async def remove_fixture_server(self):
        if not self.owner:
            return
        servers = await self.ok("GET", "/llm")
        names = {self.prefix + suffix for suffix in ("provider", "unused-provider")}
        exact = [row for row in servers if row["name"] in names]
        assert len(exact) == len({row["name"] for row in exact})
        if not exact:
            return
        for server in exact:
            await self.remove_exact_server(server)

    async def remove_exact_server(self, server):
        assert server["name"] in {self.prefix + suffix for suffix in ("provider", "unused-provider")}
        assert server["tenant_id"] == self.tenant_id and server["user_id"] == self.owner_id
        # Only this suite's own default row is released; never edit Root defaults.
        if server["name"] == self.prefix + "provider":
            await self.ok("POST", "/llm/settings/defaults/linsight_llm/inheritance")
        plan = await self.ok("POST", "/llm/server-removal-plan", json={"server_id": server["id"]})
        assert plan["inspection"]["check_complete"] is True and plan["inspection"]["blocked"] is False
        confirmation = plan["confirmation"]
        await self.ok(
            "DELETE",
            "/llm",
            json={"server_id": server["id"]},
            params={
                "confirmation_id": confirmation["confirmation_id"],
                "plan_digest": confirmation["plan_digest"],
            },
        )
        remaining = await self.ok("GET", "/llm")
        assert not any(row["id"] == server["id"] for row in remaining)

    async def cleanup(self):
        await self.clean_business_resources()
        await self.remove_fixture_server()

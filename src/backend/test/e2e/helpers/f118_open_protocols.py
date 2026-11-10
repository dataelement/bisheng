"""Real F118 v2/MCP fixtures; secrets stay in memory and out of assertions.

Uses the existing F118 explicit environment, private auth/model JSON and ready
SHA contract. ``op``/``oq`` run namespaces isolate these Childs from the main
F118 suite. Only exact named resources/accounts in those Childs are cleaned.
No application runtime credential is fabricated for the separate public
bisheng_sdk.retrieve dual-credential contract.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field

import httpx

from test.e2e.helpers.api import API_BASE, assert_resp_200, assert_resp_error
from test.e2e.helpers.f118_unification import F118Environment
from test.e2e.helpers.service_accounts import select_service_account_tenant


@dataclass(repr=False)
class ProtocolKey:
    account_id: int
    credential_id: int
    scopes: tuple[str, ...]
    plaintext: str = field(repr=False)

    def headers(self):
        return {"Authorization": "Bearer " + self.plaintext, "Cookie": ""}


def private_success(response, operation):
    """Do not let pytest render a login/key response or its private headers."""
    __tracebackhide__ = True
    if response.status_code != 200:
        raise AssertionError(f"{operation}: HTTP {response.status_code}")
    data = response.json()
    if data.get("status_code") != 200:
        raise AssertionError(f"{operation}: business code {data.get('status_code')}")
    return data.get("data")


@dataclass(repr=False)
class F118OpenProtocols:
    client: httpx.AsyncClient = field(repr=False)
    target: F118Environment = field(repr=False)
    foreign: F118Environment = field(repr=False)
    managers: dict = field(default_factory=dict, repr=False)
    account_ids: dict = field(default_factory=dict)
    keys: dict = field(default_factory=dict, repr=False)
    foreign_space: dict = field(default_factory=dict)

    @classmethod
    def from_environment(cls, client):
        target = F118Environment.from_environment(client)
        foreign = F118Environment.from_environment(client)
        target.run_id, foreign.run_id = "op" + target.run_id, "oq" + foreign.run_id
        return cls(client, target, foreign)

    @property
    def origin(self):
        return API_BASE.removesuffix("/api/v1")

    @property
    def mcp_url(self):
        # Actual exact-path Streamable HTTP router; no trailing slash redirect.
        return self.origin + "/api/v2/mcp"

    async def prepare(self):
        __tracebackhide__ = True
        for env in (self.target, self.foreign):
            await env.prepare()
            token = env.owner["Cookie"].partition("=")[2]
            self.managers[env.tenant_id] = await select_service_account_tenant(self.client, token, env.tenant_id)
            await self.clean_accounts(env)
        for label, env, scopes in (
            ("full", self.target, ("knowledge:read", "knowledge:write")),
            ("read", self.target, ("knowledge:read",)),
            ("foreign", self.foreign, ("knowledge:read", "knowledge:write")),
        ):
            manager = self.managers[env.tenant_id]
            catalog = await env.ok("GET", "/service-accounts/scopes", actor=manager)
            if not set(scopes).issubset({row["code"] for row in catalog["scopes"]}):
                raise AssertionError("Actual service-account catalog lacks knowledge scopes")
            account = await env.ok(
                "POST",
                "/service-accounts",
                actor=manager,
                json={"name": env.prefix + "protocol-" + label, "resource_owner_user_id": env.owner_id},
            )
            self.account_ids[label] = (env.tenant_id, account["id"])
            if account["tenant_id"] != env.tenant_id or account["resource_owner"]["user_id"] != env.owner_id:
                raise AssertionError("Dedicated service-account ownership changed")
            response = await self.client.post(
                API_BASE + f"/service-accounts/{account['id']}/keys",
                headers=manager,
                json={"name": env.prefix + "protocol-key-" + label, "scopes": list(scopes)},
            )
            issued = private_success(response, "key issuance")
            secret = issued.pop("plaintext", None)
            if not isinstance(secret, str) or not secret:
                raise AssertionError("Key issuance omitted its one-time credential")
            key = ProtocolKey(account["id"], issued["id"], scopes, secret)
            self.keys[label] = key
            who = await self.v2("GET", "/auth/whoami", key=key)
            if (
                who["actor_kind"] != "service_account"
                or who["mode"] != "S"
                or who["tenant_id"] != env.tenant_id
                or str(who["authorization_subject_id"]) != str(account["id"])
                or who["authorization_subject_type"] != "service_account"
                or who["resource_owner"]["user_id"] != env.owner_id
                or set(who["scopes"]) != set(scopes)
            ):
                raise AssertionError("Issued service-account identity/scopes do not match setup")
        self.foreign_space = await self.foreign.space("native")

    async def v2_response(self, method, path, *, key=None, **kwargs):
        __tracebackhide__ = True
        key = key or self.keys["full"]
        return await self.client.request(method, self.origin + "/api/v2" + path, headers=key.headers(), **kwargs)

    async def v2(self, method, path, *, key=None, **kwargs):
        __tracebackhide__ = True
        response = await self.v2_response(method, path, key=key, **kwargs)
        return assert_resp_200(response)

    async def refused(self, method, path, code, http_status, *, key=None, **kwargs):
        __tracebackhide__ = True
        response = await self.v2_response(method, path, key=key, **kwargs)
        if response.status_code != http_status:
            raise AssertionError(f"v2 refusal HTTP {response.status_code}, expected {http_status}")
        assert_resp_error(response, code)

    async def assert_native(self, resource, suffix):
        env = self.target
        assert resource["type"] == 0 and resource["name"] == env.name(suffix)
        facts = await env.info(resource["id"])
        assert facts["type"] == 3 and facts["id"] == resource["id"]
        assert facts["tenant_id"] == env.tenant_id and facts["user_id"] == env.owner_id
        assert str(facts["model"]) == str(env.embedding(0)["id"])
        roster = await env.ok("GET", f"/permissions/resources/knowledge_space/{resource['id']}/grants")
        assert any(
            row["subject"]["type"] == "user"
            and row["subject"]["id"] == str(env.owner_id)
            and row["source"]["type"] == "CREATOR"
            and row["protected"]
            for row in roster["data"]
        )
        assert any(
            row["subject"]["type"] == "service_account"
            and row["subject"]["id"] == str(self.keys["full"].account_id)
            and row["source"]["type"] == "CREATOR_GRANT"
            and not row["protected"]
            for row in roster["data"]
        )
        return facts

    async def assert_worker_and_version(self, sid, fid):
        env = self.target
        row = await env.wait_file(sid, fid)
        assert row["status"] == 2 and row["id"] == fid and row["knowledge_id"] == sid
        chain = await env.ok("GET", f"/knowledge/space/file/{fid}/versions")
        assert len(chain["versions"]) == 1 and chain["document_id"] > 0
        version = chain["versions"][0]
        assert version["knowledge_file_id"] == fid and version["version_no"] == 1 and version["is_primary"]
        chunks = await env.ok("GET", "/knowledge/chunk", params={"knowledge_id": sid, "file_ids": [fid], "limit": 200})
        assert chunks["total"] > 0 and chunks["data"]
        return chain

    async def assert_creator_delete_source(self, sid):
        """Check the original manager CREATOR_GRANT, without adding a grant.

        Runtime.check_action/_creator_delete_batch allow this exact same-tenant
        creating SA to delete even though manager's Catalog actions omit delete.
        The following real v2/MCP delete exercises that compatibility decision.
        """
        env = self.target
        base = f"/permissions/resources/knowledge_space/{sid}"
        catalog = await env.ok("GET", "/permissions/catalog")
        manager = next(row for row in catalog["models"] if row["key"] == "manager")
        assert manager["active"] and "delete" not in manager["action_codes"]
        roster = await env.ok("GET", base + "/grants")
        assert any(
            row["subject"]["type"] == "user"
            and row["subject"]["id"] == str(env.owner_id)
            and row["source"]["type"] == "CREATOR"
            and row["protected"]
            for row in roster["data"]
        )
        sources = [
            row
            for row in roster["data"]
            if row["subject"]["type"] == "service_account" and row["subject"]["id"] == str(self.keys["full"].account_id)
        ]
        assert len(sources) == 1
        assert sources[0]["model"]["key"] == "manager" and sources[0]["model"]["active"]
        assert sources[0]["source"]["type"] == "CREATOR_GRANT" and not sources[0]["protected"]
        facts = await env.info(sid)
        page = await self.v2("GET", "/filelib/", params={"type": 0, "name": facts["name"], "page_size": 200})
        rows = [row for row in page["data"] if row["id"] == sid]
        assert len(rows) == 1 and "delete" in rows[0]["actions"]

    async def wait_absent(self, sid):
        env = self.target
        deadline = time.monotonic() + env.timeout
        while time.monotonic() < deadline:
            response = await env.request("GET", f"/knowledge/space/{sid}/info")
            if response.json()["status_code"] == 18000:
                return
            assert_resp_200(response)
            await asyncio.sleep(1)
        raise AssertionError(f"Dedicated space {sid} was not deleted after protocol success")

    async def clean_accounts(self, env):
        manager = self.managers[env.tenant_id]
        names = {env.prefix + "protocol-" + suffix for suffix in ("full", "read", "foreign")}
        found, consumed = [], 0
        for page in range(1, 101):
            result = await env.ok(
                "GET",
                "/service-accounts",
                actor=manager,
                params={"keyword": env.prefix + "protocol-", "page": page, "page_size": 100},
            )
            for row in result["data"]:
                if row["name"] in names:
                    assert row["tenant_id"] == env.tenant_id and row["resource_owner"]["user_id"] == env.owner_id
                    found.append(row["id"])
            consumed += len(result["data"])
            if consumed >= result["total"]:
                break
            assert result["data"], "Incomplete dedicated account pagination"
        else:
            raise AssertionError("Dedicated account pagination exceeded limit; none deleted")
        for account_id in found:
            await env.ok("DELETE", f"/service-accounts/{account_id}", actor=manager)
        return found

    async def cleanup(self):
        try:
            for env in (self.target, self.foreign):
                if env.owner:
                    await env.clean_business_resources()
                    if env.tenant_id in self.managers:
                        await self.clean_accounts(env)
                        assert not await self.clean_accounts(env)
                    await env.remove_fixture_server()
        finally:
            self.keys.clear()

"""Local HTTP stories with real signed JWT, ToolExecutor, socket upstream and Redis.

SQL/identity/OpenFGA/Gateway are isolated adapters; deployment acceptance is separate.
Run with --confcutdir=test/dsh to avoid the repository's global middleware fixtures.
"""

import json

import httpx
import pytest

from bisheng.core.context.tenant import set_current_tenant_id
from bisheng.dsh.domain.schemas.tool_publications import ToolPublicationInput
from test.dsh.test_access import token
from test.dsh.test_tool_leases import lease_redis  # noqa: F401
from test.e2e.helpers.published_tools import harness, upstream


class TestE2EPublishedTools:
    @pytest.fixture
    async def setup(self, monkeypatch, lease_redis):  # noqa: F811
        with upstream() as (host, received):
            context = harness(monkeypatch, lease_redis, host)
            user = type("Admin", (), {"tenant_id": 2, "is_global_super": False})()
            scope = set_current_tenant_id(2)
            try:
                await context.service.put(user, "bs_web_search", ToolPublicationInput(tool_id=1, enabled=True))
                await context.service.put(user, "convert", ToolPublicationInput(tool_id=2, enabled=True))
                assert (await context.service.get(user, "convert")).tool_id == 2
            finally:
                scope.var.reset(scope)
            context.received = received
            yield context

    async def test_two_saved_schemas(self, setup):
        """AC-08, AC-16, AC-17, AC-23, AC-26: same route dispatches two real executors."""
        setup.snapshots[1][1].extra = json.dumps({"path": "/unvalidated", "parameters": [], "method": "get"})
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=setup.app), base_url="http://test") as client:
            first = await client.post(
                "/api/v1/dsh/tools/bs_web_search/invoke",
                headers=setup.headers,
                json={"arguments": {"query": " hello "}},
            )
            second = await client.post(
                "/api/v1/dsh/tools/convert/invoke", headers=setup.headers, json={"arguments": {"amount": 3}}
            )
        assert first.status_code == second.status_code == 200
        assert first.json()["result"]["results"][0]["title"] == "hello"
        assert second.json() == {"tool": "convert", "result": {"converted": 6}}
        assert [row[:2] for row in setup.received] == [("/search", {"query": "hello"}), ("/convert", {"amount": 3})]
        assert setup.telemetry.await_count == 2

    async def test_ambient_callbacks_never_receive_arguments(self, setup):
        """AC-21: inherited runnable callbacks and trace collectors see no payload."""
        from langchain_core.callbacks import BaseCallbackHandler
        from langchain_core.runnables.config import var_child_runnable_config
        from langchain_core.tracers.context import collect_runs

        calls = []

        class Recorder(BaseCallbackHandler):
            def on_tool_start(self, *args, **kwargs):
                calls.append((args, kwargs))

        context = var_child_runnable_config.set({"callbacks": [Recorder()]})
        try:
            with collect_runs() as collector:
                async with httpx.AsyncClient(
                    transport=httpx.ASGITransport(app=setup.app), base_url="http://test"
                ) as client:
                    response = await client.post(
                        "/api/v1/dsh/tools/convert/invoke", headers=setup.headers, json={"arguments": {"amount": 3}}
                    )
                assert response.status_code == 200
                assert collector.traced_runs == []
            assert calls == []
        finally:
            context.var.reset(context)

    async def test_deny_permission_disable_and_wrong_tenant(self, setup):
        """AC-06, AC-10, AC-11, AC-12: current permission, publication state and tenant."""
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=setup.app), base_url="http://test") as client:
            path = "/api/v1/dsh/tools/convert/invoke"
            setup.allowed["value"] = False
            denied = await client.post(path, headers=setup.headers, json={"arguments": {"amount": 3}})
            assert denied.status_code == 403 and denied.json()["error"]["code"] == "tool_permission_denied"
            setup.allowed["value"] = True
            setup.repository.rows[2, "convert"] = setup.repository.rows[2, "convert"].model_copy(
                update={"enabled": False}
            )
            disabled = await client.post(path, headers=setup.headers, json={"arguments": {"amount": 3}})
            assert disabled.status_code == 404 and disabled.json()["error"]["code"] == "tool_publication_not_found"
            wrong_tenant = await client.post(
                path, headers={"Authorization": "Bearer " + token(tenant_id="3")}, json={"arguments": {"amount": 3}}
            )
            assert wrong_tenant.status_code == 404
        assert setup.received == []

    async def test_forged_credentials_and_schema_rejection(self, setup):
        """AC-09, AC-14, AC-15: real credential verification and strict saved arguments."""
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=setup.app), base_url="http://test") as client:
            invalid = await client.post(
                "/api/v1/dsh/tools/convert/invoke",
                headers={"Authorization": "Bearer forged"},
                json={"arguments": {"amount": 3}},
            )
            assert invalid.status_code == 401 and invalid.json()["error"]["code"] == "invalid_access_token"
            for arguments in ({"amount": True}, {"amount": 3, "proxy": "https://bad"}, {"query": "x"}):
                response = await client.post(
                    "/api/v1/dsh/tools/convert/invoke", headers=setup.headers, json={"arguments": arguments}
                )
                assert response.status_code == 400 and response.json()["error"]["code"] == "tool_arguments_invalid"
        assert setup.received == []

"""Isolated local publication integration harness; never touches deployment stores."""

import json
import threading
from contextlib import asynccontextmanager, contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace
from unittest.mock import AsyncMock

from fastapi import FastAPI

from bisheng.core.context.tenant import get_current_tenant_id
from bisheng.dsh.api.dependencies import get_runtime
from bisheng.dsh.api.endpoints import tools
from bisheng.dsh.domain.repositories.tool_publications import PublicationRecord
from bisheng.dsh.domain.services.tool_publications import ToolPublicationService
from bisheng.dsh.infrastructure.tool_leases import ToolLeases
from bisheng.dsh.tool_runtime import get_tool_service
from bisheng.tool.domain.services.published_tools import PublishedToolService
from test.dsh.test_access import service as access_service
from test.dsh.test_access import token

PREFIX = "e2e-published-tools-"


@contextmanager
def upstream():
    received = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            received.append((self.path, body, self.headers.get("Authorization")))
            payload = {
                "results": [{"url": "https://example.org/result", "title": body.get("query", "")}],
                "truncated": False,
            }
            if self.path == "/convert":
                payload = {"converted": body["amount"] * 2}
            data = json.dumps(payload).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *_args):
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", received
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


class Publications:
    def __init__(self):
        self.rows = {}

    @asynccontextmanager
    async def locked(self, tenant, code, initial=None):
        key = tenant, code
        created = key not in self.rows and initial is not None
        record = PublicationRecord(self.rows.get(key, initial), created)
        yield record
        if record.publication is not None:
            self.rows[key] = record.publication

    async def list(self, tenant, offset, limit):
        items = [row for (owner, _), row in sorted(self.rows.items()) if owner == tenant]
        return items[offset : offset + limit], len(items)


def saved_tool(tool_id, path, name, field, scalar, host):
    schema = {"type": "object", "properties": {field: {"type": scalar}}, "required": [field]}
    operation = {"operationId": name, "requestBody": {"content": {"application/json": {"schema": schema}}}}
    document = {"openapi": "3.0.3", "paths": {path: {"post": operation}}}
    tool = SimpleNamespace(
        id=tool_id,
        name=name,
        desc=PREFIX + name,
        tool_key=PREFIX + name,
        type=tool_id,
        is_preset=0,
        is_delete=0,
        tenant_id=2,
        extra=json.dumps(
            {
                "path": path,
                "method": "post",
                "parameters": [{"name": field, "in": "body", "required": True, "schema": {"type": scalar}}],
            }
        ),
    )
    category = SimpleNamespace(
        id=tool_id,
        tenant_id=2,
        is_preset=0,
        is_delete=0,
        openapi_schema=json.dumps(document),
        server_host=host,
        extra="{}",
        auth_method=0,
        auth_type="basic",
        api_key=None,
    )
    return tool, category


def harness(monkeypatch, redis, host):
    from bisheng.common.dependencies.user_deps import UserPayload
    from bisheng.tool.domain.services import executor

    snapshots = {
        1: saved_tool(1, "/search", "search", "query", "string", host),
        2: saved_tool(2, "/convert", "convert", "amount", "integer", host),
    }
    allowed = {"value": True}

    async def permission(_user, **kwargs):
        assert kwargs["resource_type"] == "tool" and kwargs["action"] in {"use", "edit"}
        return allowed["value"]

    async def user(user_id, tenant_id):
        return UserPayload(
            user_id=user_id, user_name="tester", user_role=[], tenant_id=tenant_id, is_global_super=False
        )

    async def snapshot(tool_id):
        assert get_current_tenant_id() in {2, 3}
        return snapshots[tool_id]

    monkeypatch.setattr(executor.ToolExecutor, "_build_permission_user", staticmethod(user))
    monkeypatch.setattr(executor, "check_business_action", permission)
    telemetry = AsyncMock()
    monkeypatch.setattr(executor.telemetry_service, "log_event", telemetry)
    repository = Publications()
    tools_service = PublishedToolService(SimpleNamespace(snapshot=snapshot), permission)
    service = ToolPublicationService(repository, tools_service, ToolLeases(redis))
    app = FastAPI()
    app.include_router(tools.router, prefix="/api/v1")
    app.dependency_overrides[get_runtime] = lambda: SimpleNamespace(access=access_service())
    app.dependency_overrides[get_tool_service] = lambda: service
    return SimpleNamespace(
        app=app,
        service=service,
        repository=repository,
        snapshots=snapshots,
        allowed=allowed,
        telemetry=telemetry,
        headers={"Authorization": "Bearer " + token()},
    )

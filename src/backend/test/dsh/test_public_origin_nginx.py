"""Real proxy transport: run with NGINX_BIN pointing to an installed nginx binary.

The fixture loads the production maps and header directives into an isolated
proxy. Application routing, database authentication and model calls have their
own acceptance gates.
"""

import asyncio
import os
import re
import socket
import ssl
import subprocess
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
import uvicorn
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.routing import Route

from bisheng.dsh.work_mcp import WorkMcpResponse, create_work_mcp_runtime, work_transport_security


def available_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.mark.parametrize("template", ["default.conf", "websocket.conf"])
@pytest.mark.parametrize("tls", [False, True], ids=["one-proxy-http", "two-proxies-https"])
async def test_real_nginx_preserves_public_origin(template, tls, tmp_path, monkeypatch):
    binary = os.environ.get("NGINX_BIN")
    if not binary:
        pytest.skip("Set NGINX_BIN to exercise the real proxy")
    root = Path(__file__).resolve().parents[4]
    template_root = Path(os.environ.get("BISHENG_NGINX_TEMPLATE_ROOT", root / "docker/nginx/conf.d"))
    source = (template_root / template).read_text()
    maps = "\n".join(re.findall(r"map\s+[^{}]+\{[^{}]+\}", source))
    directives = "\n".join(re.findall(r"proxy_set_header\s+[^;]+;", source))
    assert "proxy_set_header Host" in directives
    inner_port, outer_port = available_port(), available_port()
    public_origin = f"{'https' if tls else 'http'}://work.example:{outer_port if tls else inner_port}"
    authority = public_origin.split("://", 1)[1]
    service = SimpleNamespace(
        list_tools=AsyncMock(
            return_value=[
                {
                    "name": "bisheng_tool_7",
                    "description": "Read test data",
                    "inputSchema": {"type": "object", "properties": {}},
                }
            ]
        )
    )
    monkeypatch.setattr("bisheng.dsh.work_mcp.WorkCapabilitiesService", lambda user: service)
    manager = create_work_mcp_runtime(work_transport_security(public_origin))
    observed = []

    async def endpoint(request: Request):
        observed.append(dict(request.headers))
        return WorkMcpResponse(manager, SimpleNamespace(user_id=42, tenant_id=2))

    app = Starlette(routes=[Route("/api/v1/dsh/work/mcp", endpoint, methods=["POST"])])
    backend_socket = socket.socket()
    backend_socket.bind(("127.0.0.1", 0))
    backend_port = backend_socket.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, log_level="error", lifespan="off", proxy_headers=False))
    certificate, key = tmp_path / "cert.pem", tmp_path / "key.pem"
    outer = ""
    verify = True
    if tls:
        subprocess.run(
            [
                "openssl",
                "req",
                "-x509",
                "-newkey",
                "rsa:2048",
                "-nodes",
                "-days",
                "1",
                "-keyout",
                str(key),
                "-out",
                str(certificate),
                "-subj",
                "/CN=127.0.0.1",
                "-addext",
                "subjectAltName=IP:127.0.0.1",
            ],
            check=True,
            capture_output=True,
        )
        verify = ssl.create_default_context(cafile=str(certificate))
        outer = f"""
        server {{
            listen 127.0.0.1:{outer_port} ssl;
            ssl_certificate {certificate}; ssl_certificate_key {key};
            location / {{
                proxy_pass http://127.0.0.1:{inner_port};
                proxy_set_header Host $http_host;
                proxy_set_header X-Forwarded-Proto $scheme;
            }}
        }}"""
    config = tmp_path / "nginx.conf"
    config.write_text(f"""
        daemon off; master_process off; pid {tmp_path}/nginx.pid;
        error_log {tmp_path}/error.log;
        events {{ worker_connections 64; }}
        http {{
            access_log off;
            client_body_temp_path {tmp_path}/body;
            proxy_temp_path {tmp_path}/proxy;
            {maps}
            server {{
                listen 127.0.0.1:{inner_port};
                location / {{
                    proxy_pass http://127.0.0.1:{backend_port};
                    {directives}
                }}
            }}
            {outer}
        }}
    """)
    process = None
    async with manager.run():
        server_task = asyncio.create_task(server.serve(sockets=[backend_socket]))
        try:
            async with asyncio.timeout(10):
                while not server.started:
                    await asyncio.sleep(0.01)
            process = subprocess.Popen([binary, "-p", str(tmp_path), "-c", str(config)], stderr=subprocess.PIPE)
            target_port = outer_port if tls else inner_port
            async with asyncio.timeout(10):
                while True:
                    if process.poll() is not None:
                        pytest.fail(process.stderr.read().decode())
                    try:
                        _, writer = await asyncio.open_connection("127.0.0.1", target_port)
                        writer.close()
                        await writer.wait_closed()
                        break
                    except OSError:
                        await asyncio.sleep(0.01)
            headers = {"host": authority, "origin": public_origin, "accept": "application/json, text/event-stream"}
            async with httpx.AsyncClient(
                base_url=f"{'https' if tls else 'http'}://127.0.0.1:{target_port}",
                headers=headers,
                verify=verify,
                trust_env=False,
            ) as client:
                message = {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": "2025-11-25",
                        "capabilities": {},
                        "clientInfo": {"name": "nginx-regression", "version": "1"},
                    },
                }
                response = await client.post("/api/v1/dsh/work/mcp", json=message)
                assert response.status_code == 200, response.text
                assert observed[-1]["host"] == authority
                assert observed[-1]["x-forwarded-proto"] == ("https" if tls else "http")
                response = await client.post(
                    "/api/v1/dsh/work/mcp",
                    json={
                        "jsonrpc": "2.0",
                        "id": 2,
                        "method": "tools/list",
                    },
                )
                assert response.status_code == 200, response.text
                assert response.json()["result"]["tools"][0]["name"] == "bisheng_tool_7"
                for extra, status in [
                    ({"host": "other.example", "x-forwarded-host": authority}, 421),
                    ({"origin": "https://other.example"}, 403),
                ]:
                    response = await client.post("/api/v1/dsh/work/mcp", json=message, headers=extra)
                    assert response.status_code == status
        finally:
            if process is not None:
                if process.poll() is None:
                    process.terminate()
                await asyncio.to_thread(process.communicate, timeout=10)
            server.should_exit = True
            await asyncio.wait_for(server_task, timeout=10)
            backend_socket.close()

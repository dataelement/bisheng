"""覆盖 AC: AC-15、AC-28、AC-46、AC-47、AC-51.

The always-on tests exercise real backend material authentication and guard the
product ingress boundary. Set NGINX_BIN to additionally proxy the same signed
requests through a real local nginx; absence is an explicit integration skip.
"""

import asyncio
import os
import re
import shutil
import socket
import subprocess
from datetime import UTC
from pathlib import Path
from uuid import uuid4

import httpx
import pytest

from bisheng.app_runtime.domain.services import runtime_material_protocol as wire
from bisheng.app_runtime.domain.services.runtime_protocol import canonical_json
from test.app_runtime.test_runtime_kubernetes_repository import UID
from test.app_runtime.test_runtime_kubernetes_repository import repo as repo
from test.app_runtime.test_runtime_kubernetes_service import control as control
from test.app_runtime.test_runtime_material_api import api_client as api_client
from test.app_runtime.test_runtime_material_api import grant
from test.app_runtime.test_runtime_material_service import KEY_ID
from test.app_runtime.test_runtime_material_service import materials as materials
from test.app_runtime.test_runtime_material_transfers import DATA
from test.app_runtime.test_runtime_material_transfers import transfers as transfers

CONF = Path(__file__).resolve().parents[4] / "docker/nginx/conf.d/default.conf"
PREFIX = "/internal/app-runtime/v2/material-access/"


def material_location():
    text = CONF.read_text()
    match = re.search(r"(?m)^\s*location\s+\^~\s+" + re.escape(PREFIX) + r"\s*\{([^{}]*)\}", text)
    assert match is not None, "The HTTPS origin must route the exact workload material root to backend."
    return match.group(0), match.group(1)


def test_material_location_preserves_signed_target_and_bounded_streaming():
    _, body = material_location()
    directives = [line.split("#", 1)[0].strip() for line in body.splitlines()]
    assert "proxy_pass http://backend_server;" in directives
    assert "proxy_http_version 1.1;" in directives
    assert "proxy_request_buffering off;" in directives
    assert "proxy_buffering off;" in directives
    assert "client_max_body_size 16m;" in directives
    assert "client_body_timeout 60s;" in directives
    assert "proxy_connect_timeout 60s;" in directives
    assert "proxy_send_timeout 65s;" in directives
    assert "proxy_read_timeout 65s;" in directives
    assert not any(line.startswith(("rewrite ", "auth_request ", "proxy_intercept_errors on")) for line in directives)
    assert not any(
        "proxy_set_header X-Material-" in line or "proxy_set_header Authorization" in line for line in directives
    )


def test_material_location_does_not_expose_other_internal_or_workspace_paths():
    active = "\n".join(line.split("#", 1)[0] for line in CONF.read_text().splitlines())
    internal_locations = [line.strip() for line in active.splitlines() if "location" in line and "/internal" in line]
    assert internal_locations == ["location ^~ " + PREFIX + " {"]
    assert "/workspace/internal/" not in active


async def exercise_backend_authentication(client, api):
    target = wire.PREFIX + "/exchange"
    unsigned = await client.post(target, content=b"{}")
    assert unsigned.status_code == 401
    assert unsigned.json() == {"error": {"reason": "material_key_refused"}}
    delegation = await grant(api)

    async def signed(method, path, *, document=None, session=None, tamper=False):
        raw = canonical_json(document) if document is not None else b""
        headers = wire.signed_headers(
            method,
            path,
            raw,
            private_key=api.t.m.signer,
            delegation_id=delegation["delegation_id"],
            key_id=KEY_ID,
            pod_uid=UID,
            timestamp=int(api.t.m.clock["now"].replace(tzinfo=UTC).timestamp()),
            nonce=uuid4().hex,
            ticket=session["ticket"] if session else "",
        )
        return await client.request(method, path, content=raw + (b" " if tamper else b""), headers=headers)

    declaration = {"action": "download", "artifact_id": api.t.m.content["compiled_artifact_id"]}
    exchange = await signed("POST", target, document=declaration)
    assert exchange.status_code == 200
    session = exchange.json()
    ranged_target = wire.PREFIX + "/transfers/" + session["transfer_id"] + "/content?length=4&offset=2"
    ranged = await signed("GET", ranged_target, session=session)
    assert ranged.status_code == 206 and ranged.content == DATA[2:6]
    assert ranged.headers["content-range"] == "bytes 2-5/10"
    assert ranged.headers["content-length"] == "4"
    tampered = await signed("POST", target, document=declaration, tamper=True)
    assert tampered.status_code == 401
    for alias in ("/api/v1" + target, "/workspace" + target, "/internal/unrelated"):
        assert (await client.post(alias, content=b"{}")).status_code == 404
    return ranged_target


async def test_real_backend_material_root_returns_authentication_failure_and_accepts_signed_range(api_client):
    await exercise_backend_authentication(api_client.client, api_client)


@pytest.fixture
async def nginx_ingress(api_client, tmp_path):
    binary = shutil.which(os.environ.get("NGINX_BIN", "nginx"))
    if binary is None:
        pytest.skip("Real nginx unavailable; set NGINX_BIN for local ingress integration.")
    import uvicorn

    location, _ = material_location()
    seen = []
    backend = api_client.client._transport.app

    async def application(scope, receive, send):
        if scope["type"] == "http":
            target = scope["raw_path"].decode("ascii")
            if scope.get("query_string"):
                target += "?" + scope["query_string"].decode("ascii")
            seen.append(target)
        await backend(scope, receive, send)

    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen()
    listener.setblocking(False)
    upstream_port = listener.getsockname()[1]
    with socket.socket() as reservation:
        reservation.bind(("127.0.0.1", 0))
        port = reservation.getsockname()[1]
    # Reuse the product's forwarded-header maps with its exact location body.
    maps = CONF.read_text().split("upstream backend_server", 1)[0]
    configuration = tmp_path / "nginx.conf"
    configuration.write_text(
        "\n".join(
            [
                "worker_processes 1;",
                f"pid {tmp_path / 'nginx.pid'};",
                "error_log stderr warn;",
                "events { worker_connections 32; }",
                "http { access_log off;",
                maps,
                f"client_body_temp_path {tmp_path / 'client-body'};",
                f"proxy_temp_path {tmp_path / 'proxy'};",
                f"upstream backend_server {{ server 127.0.0.1:{upstream_port}; }}",
                f"server {{ listen 127.0.0.1:{port};",
                location,
                "location / { return 404; }",
                "} }",
            ]
        )
    )
    checked = subprocess.run(
        [binary, "-t", "-p", str(tmp_path) + "/", "-c", str(configuration)], capture_output=True, text=True, check=False
    )
    if checked.returncode != 0:
        listener.close()
        pytest.fail(checked.stderr)
    server = uvicorn.Server(uvicorn.Config(application, log_level="critical", access_log=False, lifespan="off"))
    task = asyncio.create_task(server.serve(sockets=[listener]))
    process = None
    try:
        for _ in range(100):
            if server.started:
                break
            if task.done():
                await task
                pytest.fail("Test backend stopped before startup.")
            await asyncio.sleep(0.01)
        assert server.started
        process = subprocess.Popen(
            [binary, "-p", str(tmp_path) + "/", "-c", str(configuration), "-g", "daemon off;"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        async with httpx.AsyncClient(base_url="http://127.0.0.1:" + str(port), trust_env=False, timeout=5) as client:
            for _ in range(100):
                assert process.poll() is None, "Test nginx failed to start."
                try:
                    await client.get("/__fixture_ready")
                    break
                except httpx.ConnectError:
                    await asyncio.sleep(0.01)
            else:
                pytest.fail("Test nginx did not become reachable.")
            yield client, seen
    finally:
        if process is not None:
            process.terminate()
            await asyncio.to_thread(process.wait, timeout=5)
        server.should_exit = True
        await asyncio.wait_for(task, timeout=5)
        listener.close()


async def test_real_nginx_keeps_backend_authentication_and_raw_signed_path_query(api_client, nginx_ingress):
    client, seen = nginx_ingress
    target = await exercise_backend_authentication(client, api_client)
    assert target in seen
    assert not any(path.startswith(("/api/", "/workspace/", "/internal/unrelated")) for path in seen)

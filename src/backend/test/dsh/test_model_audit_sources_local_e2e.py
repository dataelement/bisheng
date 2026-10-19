"""Opt-in actual Desktop HTTP boundary; memory and owned Docker results are separate."""

import asyncio
import json
import os
import secrets
import shutil
import socket
from contextlib import contextmanager
from pathlib import Path

import httpx
import pytest
import uvicorn
from sqlmodel import SQLModel

from bisheng.core.database import tenant_filter
from bisheng.dsh.domain.schemas.model_audit import AuditModeCommand
from bisheng.dsh.infrastructure.model_audit_activity import RedisAuditActivity
from bisheng.dsh.infrastructure.model_audit_keys import AuditKeyRing
from bisheng.dsh.infrastructure.model_audit_storage import BishengMinioAuditObjects, EncryptedAuditStorage
from test.dsh.audit_local_server import docker_stores
from test.dsh.model_audit_fixtures import AUDIT_MODELS, FaultAuditObjects, audit_database
from test.dsh.model_audit_harness import AuditHarness
from test.e2e.helpers.api import assert_resp_200

pytestmark = pytest.mark.e2e


@contextmanager
def memory_stores():
    with audit_database() as engine:
        yield engine, None, FaultAuditObjects()


async def test_actual_desktop_sources_against_owned_mysql_redis_minio():
    """AC-40, AC-41, AC-42, AC-43, AC-44, AC-45, AC-46, AC-47, AC-48."""
    mode = os.environ.get("DSH_AUDIT_SOURCES_REAL_STORES")
    if mode not in {"1", "memory"}:
        pytest.skip("Explicit owned-store opt-in required")
    client_root = Path(os.environ["DSH_AUDIT_CLIENT_WORKTREE"])
    probe = client_root / "scripts/verify-audit-sources.mjs"
    assert probe.is_file()
    token, admin = secrets.token_hex(24), secrets.token_hex(24)
    with docker_stores() if mode == "1" else memory_stores() as (engine, redis, stores):
        from bisheng.user.domain.models.user import User

        SQLModel.metadata.create_all(engine, tables=[model.__table__ for model in AUDIT_MODELS] + [User.__table__])
        tenant_filter.register_tenant_filter_events()
        tenant_filter._tenant_aware_tables.update(model.__tablename__ for model in AUDIT_MODELS)
        storage = EncryptedAuditStorage(
            BishengMinioAuditObjects() if mode == "1" else stores,
            AuditKeyRing({"fixture": secrets.token_bytes(32)}, active_id="fixture"),
        )
        activity = (
            RedisAuditActivity(redis, interval=1, maximum=4096, observation_window=300) if redis is not None else None
        )
        harness = AuditHarness(engine, storage, tokens={token: 20, admin: 1}, activity=activity)
        await harness.modes.change_admin(
            1, 2, AuditModeCommand(operation_id="e2e-source-mode", expected_version=0, mode="CONTENT")
        )
        sock = socket.socket()
        sock.bind(("127.0.0.1", 0))
        base = "http://127.0.0.1:" + str(sock.getsockname()[1])
        server = uvicorn.Server(uvicorn.Config(harness.app, access_log=False, log_level="error"))
        task = asyncio.create_task(server.serve(sockets=[sock]))
        process = None
        try:
            async with asyncio.timeout(10):
                while not server.started:
                    await asyncio.sleep(0.02)
            process = await asyncio.create_subprocess_exec(
                shutil.which("node"),
                str(probe),
                cwd=client_root,
                env={**os.environ, "DSH_AUDIT_BASE": base, "DSH_AUDIT_USER_TOKEN": token},
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=30)
            assert process.returncode == 0, stderr.decode()[:200]
            result = json.loads(stdout)
            await harness.drain()
            assert harness.calls == 4 and harness.writer.failed == 0
            headers = {"Authorization": "Bearer " + admin}
            async with httpx.AsyncClient(base_url=base, timeout=10, trust_env=False) as client:
                for index, call in enumerate(result["calls"]):
                    path = "/api/v1/dsh/admin/model-audit/requests/" + call["request_id"]
                    detail = assert_resp_200(await client.get(path, headers=headers))
                    assert detail["request_kind"] == ("compaction" if index % 2 else "chat")
                    assert detail["session_origin"] == ("subagent" if index >= 2 else "main")
                    assert detail["content_status"] == "COMPLETE"
                    response = await client.post(path + "/body-access?include_message_sources=true", headers=headers)
                    frames = [json.loads(line) for line in response.text.splitlines()]
                    assert frames[1]["message_sources_status"] == "AVAILABLE"
                    assert frames[1]["items"] == call["context"]["message_sources"]["items"]
                    assert "audit_context" not in "".join(frame.get("fragment", "") for frame in frames)
                    assert frames[-1]["transfer_status"] == "COMPLETED"
                    if index >= 2:
                        parent = assert_resp_200(await client.get(path + "/parent-conversation", headers=headers))
                        assert parent == {"status": "AVAILABLE", "user_id": 20, "conversation_id": result["parent"]}
        finally:
            if process is not None and process.returncode is None:
                process.kill()
                await process.wait()
            server.should_exit = True
            await task
            await harness.close()
            if redis is not None:
                await redis.aclose()

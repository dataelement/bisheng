"""Local V1 upload contract. A test resolver is never deployment evidence."""

from hashlib import sha256
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, Mock

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import event
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from bisheng.knowledge.api.endpoints import knowledge_space as api
from bisheng.knowledge.application import provider_upload_v1 as uploads
from bisheng.knowledge.domain.models.provider_control import KnowledgeProviderOperation as Op

PATH = "/api/v1/knowledge/space/14/provider-uploads/key"
PARAMS = {"file_name": "test.txt", "byte_count": 3, "sha256": sha256(b"abc").hexdigest(), "parent_id": 9}


@pytest.fixture
async def http(monkeypatch):
    user = NS(tenant_id=3, user_id=17)
    actor = NS(current_tenant_id=3, subject_type="user", subject_id=17)
    svc = NS(
        login_user=user,
        _permission_actor=AsyncMock(return_value=actor),
        _require_action=AsyncMock(),
        require_upload_container=AsyncMock(return_value=NS(tenant_id=3)),
        upload_application_factory=Mock(side_effect=AssertionError("must not register an upload")),
    )
    route = NS(
        tenant_id=3,
        provider_key="weknora",
        capability_revision=7,
        space_id=14,
        instance_id=1,
        generation=2,
        remote_scope_id="3",
        remote_kb_id="lib",
    )
    monkeypatch.setattr(uploads, "get_current_tenant_id", lambda: 3)
    monkeypatch.setattr(uploads, "resolve_space_route", AsyncMock(return_value=route))
    monkeypatch.setattr(api.provider, "resolve_space_route", AsyncMock(return_value=route))
    app = FastAPI()
    app.include_router(api.router, prefix="/api/v1")
    app.dependency_overrides[api.get_knowledge_space_service] = lambda: svc
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        yield client, svc, route


async def unread():
    pytest.fail("received bytes without admission")
    yield b""


async def test_unregistered_upload_port_rejects_before_reading(http):
    client, svc, _ = http
    caps = (await client.get("/api/v1/knowledge/space/14/capabilities")).json()["data"]["capabilities"]
    assert (caps["upload"], caps["preview_edit"]) == ("unverified", "unsupported")
    with pytest.raises(uploads.ProviderFeatureUnavailable):
        await client.post(PATH, params=PARAMS, headers={"Content-Type": "application/octet-stream"}, content=unread())
    svc.require_upload_container.assert_awaited_once_with(14, 9)
    svc.upload_application_factory.assert_not_called()


@pytest.mark.parametrize(
    ("params", "mime", "status"),
    [
        ({"sha256": "bad"}, "application/octet-stream", 422),
        ({"byte_count": -1}, "application/octet-stream", 422),
        ({"file_name": "../file"}, "application/octet-stream", 422),
        ({"parent_id": 0}, "application/octet-stream", 422),
        ({}, "multipart/form-data", 415),
    ],
)
async def test_request_validation_never_parses_upload_body(http, params, mime, status):
    client, svc, _ = http
    response = await client.post(PATH, params=PARAMS | params, headers={"Content-Type": mime}, content=unread())
    assert response.status_code == status
    svc.upload_application_factory.assert_not_called()


@pytest.fixture
async def ledger(monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite://")
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Op.__table__.create)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        monkeypatch.setattr(uploads, "get_async_db_session", sessions)
        statements = []

        def record(conn, cursor, statement, *args):
            statements.append(statement)

        event.listen(engine.sync_engine, "before_cursor_execute", record)
        yield sessions, statements
    finally:
        await engine.dispose()


async def seed(sessions, **changes):
    op = Op(
        **(
            {
                "operation_id": "original",
                "tenant_id": 3,
                "actor_user_id": 17,
                "space_id": 14,
                "request_key": "key",
                "kind": "upload",
                "phase": "upload",
                "request_hash": "a" * 64,
                "provider_instance_id": 2,
                "remote_scope_id": "scope",
                "remote_kb_id": "kb",
                "generation": 1,
                "operation_epoch": 1,
                "capability_revision": 7,
                "target_manifest": [{"file_id": 12, "version_id": 13, "parent_id": 9}],
                "state": "sending",
            }
            | changes
        )
    )
    async with sessions.begin() as db:
        db.add(op)


@pytest.mark.parametrize(
    ("state", "error", "expected"),
    [
        ("succeeded", None, "accepted"),
        ("sending", None, "unknown"),
        ("reconciling", None, "unknown"),
        ("failed", "not_received", "reupload_required"),
        ("manual_review", None, "conflict"),
    ],
)
async def test_read_uses_ledger_original_parent_and_never_claims_or_calls_upstream(
    http, ledger, state, error, expected
):
    client, svc, _ = http
    sessions, statements = ledger
    await seed(sessions, state=state, last_error_code=error)
    statements.clear()
    for _ in range(2):
        result = (await client.get(PATH, params={"parent_id": 99})).json()
        assert result["status_code"] == 200 and result["data"] == {
            "state": expected,
            "operation_id": "original",
            "file_id": 12,
            "version_id": 13,
        }
        assert svc.require_upload_container.await_args.args == (14, 9)
    assert svc.require_upload_container.await_count == 2
    assert len(statements) == 2 and all(sql.lstrip().upper().startswith("SELECT") for sql in statements)
    uploads.resolve_space_route.assert_not_awaited()
    svc.upload_application_factory.assert_not_called()


@pytest.mark.parametrize(
    "changes", [None, {"actor_user_id": 18}, {"tenant_id": 4}, {"space_id": 15}, {"kind": "provision"}]
)
async def test_absent_and_foreign_items_are_indistinguishable(http, ledger, changes):
    client, svc, _ = http
    sessions, _ = ledger
    if changes:
        await seed(sessions, **changes)
    result = (await client.get(PATH, params={"parent_id": 21})).json()["data"]
    assert result == {"state": "not_found", "operation_id": None, "file_id": None, "version_id": None}
    svc.require_upload_container.assert_awaited_once_with(14, 21)


async def test_revoked_original_folder_cannot_be_substituted(http, ledger):
    client, svc, _ = http
    sessions, _ = ledger
    await seed(sessions)
    svc.require_upload_container.side_effect = PermissionError
    with pytest.raises(PermissionError):
        await client.get(PATH, params={"parent_id": 88})
    svc.require_upload_container.assert_awaited_once_with(14, 9)


@pytest.mark.parametrize("case", ["no_user_budget", "no_tenant_budget", "stale_instance", "no_lookup"])
async def test_incomplete_deployment_does_not_admit_or_consume_body(http, monkeypatch, case):
    client, svc, route = http
    port = NS(
        context=NS(operation="upload", **vars(route)),
        capability_revision=7,
        validate_upload=Mock(),
        send=AsyncMock(),
        lookup=AsyncMock(),
    )
    if case == "stale_instance":
        port.context.instance_id += 1
    if case == "no_lookup":
        port.lookup = None
    resolver = AsyncMock(
        return_value=uploads.UploadAdmission(
            port, None if case == "no_user_budget" else 8, 0 if case == "no_tenant_budget" else 8
        )
    )
    monkeypatch.setattr(uploads, "_UPLOAD_DEPLOYMENTS", {"weknora": resolver})
    caps = (await client.get("/api/v1/knowledge/space/14/capabilities")).json()["data"]["capabilities"]
    assert caps["upload"] == "unverified"
    with pytest.raises(uploads.ProviderFeatureUnavailable):
        await client.post(PATH, params=PARAMS, headers={"Content-Type": "application/octet-stream"}, content=unread())
    svc.upload_application_factory.assert_not_called()


async def test_changed_actor_or_request_tenant_stops_before_ledger(http, monkeypatch):
    client, svc, _ = http
    svc._permission_actor.return_value.subject_id = 99
    sessions = Mock(side_effect=AssertionError("must not query before actor verification"))
    monkeypatch.setattr(uploads, "get_async_db_session", sessions)
    with pytest.raises(uploads.ProviderFeatureUnavailable):
        await client.get(PATH)
    svc._permission_actor.return_value.subject_id = 17
    monkeypatch.setattr(uploads, "get_current_tenant_id", lambda: 4)
    with pytest.raises(uploads.ProviderFeatureUnavailable):
        await client.post(PATH, params=PARAMS, headers={"Content-Type": "application/octet-stream"}, content=unread())
    svc.require_upload_container.assert_not_awaited()
    sessions.assert_not_called()


async def test_post_forwarding_preserves_raw_stream_and_uses_only_server_budgets(http, monkeypatch):
    # Verify plumbing, not success: the application deliberately reports unknown.
    from bisheng.knowledge.application.provider_upload_item import UploadItemResult

    client, svc, route = http
    port = NS(
        context=NS(operation="upload", **vars(route)),
        capability_revision=route.capability_revision,
        validate_upload=Mock(),
        send=AsyncMock(),
        lookup=AsyncMock(),
    )
    resolver = AsyncMock(return_value=uploads.UploadAdmission(port, 128, 256))
    monkeypatch.setattr(uploads, "_UPLOAD_DEPLOYMENTS", {"weknora": resolver})

    async def create(**kwargs):
        assert kwargs["knowledge"] is svc.require_upload_container.return_value
        assert (kwargs["user_limit"], kwargs["tenant_limit"], kwargs["port"]) == (128, 256, port)
        assert (
            kwargs["file_name"],
            kwargs["checksum"],
            kwargs["byte_count"],
            kwargs["parent_id"],
            kwargs["request_key"],
        ) == ("test.txt", PARAMS["sha256"], 3, 9, "key")
        assert b"".join([block async for block in kwargs["chunks"]]) == b"abc"
        return UploadItemResult("unknown", "local", 6, 7)

    svc.upload_application_factory = Mock(return_value=NS(acreate_provider_file=create))
    result = (
        await client.post(
            PATH,
            params=PARAMS | {"user_limit": 9999},
            headers={"Content-Type": "application/octet-stream"},
            content=b"abc",
        )
    ).json()
    resolver.assert_awaited_once_with(route, 17)
    assert result["data"] == {"state": "unknown", "operation_id": "local", "file_id": 6, "version_id": 7}

"""Report callback/issuer authorization, with no remote or storage I/O."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import jwt
import pytest
from fastapi import HTTPException

from bisheng.api.services import report_editor_security as security
from bisheng.api.v1 import report
from bisheng.core.context.tenant import get_current_tenant_id, tenant_execution_scope

SECRET = "test-only-office-key-with-at-least-32-bytes"


def _body():
    return {"status": 2, "url": "http://office.local/cache/a", "key": "valid_key"}


def _editor(key="valid_key", workflow=False):
    return {
        "documentType": "word",
        "document": {"fileType": "docx", "key": key, "url": ""},
        "editorConfig": {
            "callbackUrl": "https://bisheng.local/api/v1/"
            + ("workflow/report/callback" if workflow else "report/callback")
        },
    }


async def test_unsigned_callback_refused_before_download(monkeypatch):
    fetch = AsyncMock(return_value=None)
    monkeypatch.setattr(report, "afetch_office_document", fetch)
    monkeypatch.setattr(report, "bisheng_settings", Mock(get_from_db=lambda key: "test-office-secret"))
    result = await report.callback({"status": 2, "url": "http://office.local/cache/a", "key": "victim"})
    assert result == {"error": 1}
    fetch.assert_not_awaited()


async def test_issuer_is_not_callback_signing_oracle(monkeypatch):
    monkeypatch.setattr(report, "bisheng_settings", Mock(get_from_db=lambda key: "test-office-secret"))
    with pytest.raises(HTTPException):
        await report.get_office_token(
            {"status": 2, "url": "http://office.local/cache/a", "key": "victim"},
            login_user=Mock(user_id=7, tenant_id=2),
        )


async def test_issuer_requires_configured_secret(monkeypatch):
    monkeypatch.setattr(report, "bisheng_settings", Mock(get_from_db=lambda key: ""))
    with pytest.raises(HTTPException):
        await report.get_office_token({}, login_user=Mock(user_id=7, tenant_id=2))


@pytest.mark.parametrize("nested", [False, True])
def test_callback_signature_binds_exact_body(nested):
    body = _body()
    token = jwt.encode({"payload": body} if nested else body, SECRET, algorithm="HS256")
    assert security.verify_callback({**body, "token": token}, SECRET) == body
    assert security.verify_callback(body, SECRET, f"Bearer {token}") == body
    for field, value in [("status", 6), ("key", "victim"), ("url", "http://office.local/cache/victim")]:
        assert security.verify_callback({**body, field: value, "token": token}, SECRET) is None


@pytest.mark.parametrize("trimmed", [False, True])
def test_callback_accepts_distinct_outbox_tokens(trimmed):
    full_body = {**_body(), "history": {"changes": []}, "changesurl": "http://office.local/cache/changes"}
    body = {**_body(), "history": {}} if trimmed else full_body
    body_token = jwt.encode(full_body, SECRET, algorithm="HS256")
    header_token = jwt.encode({"payload": body}, SECRET, algorithm="HS256")
    assert security.verify_callback({**body, "token": body_token}, SECRET, f"Bearer {header_token}") == body


@pytest.mark.parametrize("field,value", [
    ("status", 6),
    ("key", "another_key"),
    ("url", "http://office.local/cache/b"),
    ("history", {"changes": ["different"]}),
    ("changesurl", "http://office.local/cache/other-changes"),
])
def test_callback_requires_both_tokens_to_bind_the_save(field, value):
    body = {**_body(), "history": {"changes": []}, "changesurl": "http://office.local/cache/changes"}
    body_token = jwt.encode(body, SECRET, algorithm="HS256")
    altered = {**body, field: value}
    header_token = jwt.encode({"payload": altered}, SECRET, algorithm="HS256")
    assert security.verify_callback({**altered, "token": body_token}, SECRET, f"Bearer {header_token}") is None


@pytest.mark.parametrize("invalid_position", ["body", "header"])
def test_callback_rejects_either_invalid_signature(invalid_position):
    body = _body()
    wrong_secret = "a-different-test-signing-key-at-least-32-bytes"
    body_token = jwt.encode(body, wrong_secret if invalid_position == "body" else SECRET, algorithm="HS256")
    header_token = jwt.encode(
        {"payload": body}, wrong_secret if invalid_position == "header" else SECRET, algorithm="HS256"
    )
    assert security.verify_callback({**body, "token": body_token}, SECRET, f"Bearer {header_token}") is None


@pytest.mark.parametrize("kind", ["wrong", "expired", "editor", "none", "empty"])
def test_callback_token_rejections(kind):
    body = _body()
    payload = {**body, "exp": 1} if kind == "expired" else _editor() if kind == "editor" else body
    token = jwt.encode(payload, "wrong-key" if kind == "wrong" else SECRET, algorithm="HS256")
    if kind == "none":
        token = jwt.encode(body, "", algorithm="none")
    assert security.verify_callback({**body, "token": token}, "" if kind == "empty" else SECRET) is None


@pytest.fixture
def editor_boundary(monkeypatch):
    row = SimpleNamespace(id=5, tenant_id=2, flow_id="wf", object_name=None)
    redis = SimpleNamespace(aset=AsyncMock(), aget=AsyncMock())
    permission = AsyncMock(return_value=True)
    monkeypatch.setattr(
        security, "settings", SimpleNamespace(open_api=SimpleNamespace(public_base_url="https://bisheng.local"))
    )
    minio = SimpleNamespace(
        tmp_bucket="tmp",
        bucket="bucket",
        put_object=AsyncMock(),
        get_share_link=AsyncMock(return_value="https://minio.local/empty-signed"),
    )
    monkeypatch.setattr(security, "get_minio_storage", AsyncMock(return_value=minio))
    monkeypatch.setattr(security.ReportRepository, "find_by_key", Mock(return_value=row))
    monkeypatch.setattr(security.ReportRepository, "editor_is_active", Mock(return_value=True))
    monkeypatch.setattr(security, "get_redis_client", AsyncMock(return_value=redis))
    monkeypatch.setattr(security, "check_business_action", permission)
    return SimpleNamespace(row=row, redis=redis, permission=permission)


async def test_report_issuer_grant_binds_actual_key_and_parent(editor_boundary):
    user = SimpleNamespace(user_id=7, tenant_id=2)
    with tenant_execution_scope(99):
        await security.authorize_editor(_editor(), user)
        assert get_current_tenant_id() == 99
    grant = editor_boundary.redis.aset.await_args.args[1]
    assert grant == {"report_id": 5, "tenant_id": 2, "flow_id": "wf", "user_id": 7, "key": "valid_key"}
    assert editor_boundary.permission.await_args.kwargs["action"] == "edit"


@pytest.mark.parametrize("reason", ["missing", "tenant", "denied", "url"])
async def test_report_issuer_denied_has_no_grant(editor_boundary, monkeypatch, reason):
    payload = _editor()
    if reason == "missing":
        monkeypatch.setattr(security.ReportRepository, "find_by_key", lambda key: None)
    elif reason == "tenant":
        editor_boundary.row.tenant_id = 3
    elif reason == "denied":
        editor_boundary.permission.return_value = False
    else:
        payload["document"]["url"] = "http://169.254.169.254/a"
        minio = SimpleNamespace(bucket="bucket", get_minio_share_host=lambda: "http://minio.local")
        monkeypatch.setattr(security, "get_minio_storage", AsyncMock(return_value=minio))
    with pytest.raises(HTTPException):
        await security.authorize_editor(payload, SimpleNamespace(user_id=7, tenant_id=2))
    editor_boundary.redis.aset.assert_not_awaited()


async def test_workflow_issuer_requires_owned_edit_session(editor_boundary, monkeypatch):
    key = "a" * 32 + "-" + "b" * 32 + "_123"
    session = {"workflow_id": "a" * 32, "can_edit": True}
    monkeypatch.setattr(security.report_template, "aget_edit_session", AsyncMock(return_value=session))
    await security.authorize_editor(_editor(key, workflow=True), SimpleNamespace(user_id=7, tenant_id=2))
    editor_boundary.redis.aset.assert_not_awaited()
    session["workflow_id"] = "victim"
    with pytest.raises(HTTPException):
        await security.authorize_editor(_editor(key, workflow=True), SimpleNamespace(user_id=7, tenant_id=2))


@pytest.mark.parametrize("reason", ["missing", "row", "tenant", "parent", "permission", "inactive", "valid"])
async def test_callback_grant_scopes_and_rechecks_before_io(editor_boundary, reason):
    grant = {"report_id": 5, "tenant_id": 2, "flow_id": "wf", "user_id": 7, "key": "valid_key"}
    if reason == "missing":
        grant = None
    elif reason == "row":
        grant["report_id"] = 999
    elif reason == "tenant":
        grant["tenant_id"] = 3
    elif reason == "parent":
        grant["flow_id"] = "victim"
    elif reason == "permission":
        editor_boundary.permission.return_value = False
    elif reason == "inactive":
        security.ReportRepository.editor_is_active.return_value = False
    editor_boundary.redis.aget.return_value = grant
    with tenant_execution_scope(99):
        result = await security.resolve_callback_report("valid_key")
        assert get_current_tenant_id() == 99
    assert (result is editor_boundary.row) == (reason == "valid")


async def test_signed_unknown_key_never_fetches(monkeypatch):
    body = _body()
    monkeypatch.setattr(report, "bisheng_settings", Mock(get_from_db=lambda key: SECRET))
    monkeypatch.setattr(report, "resolve_callback_report", AsyncMock(return_value=None))
    fetch = AsyncMock()
    monkeypatch.setattr(report, "afetch_office_document", fetch)
    assert await report.callback({**body, "token": jwt.encode(body, SECRET, algorithm="HS256")}) == {"error": 1}
    fetch.assert_not_awaited()


async def test_signed_authorized_callback_writes_after_binding(monkeypatch):
    body = _body()
    events = []
    row = SimpleNamespace(id=5, tenant_id=2)

    async def resolve(key):
        events.append("authorize")
        return row

    async def fetch(url):
        assert get_current_tenant_id() == 2
        events.append("fetch")
        return b"docx"

    async def put(**kwargs):
        events.append("write")
        assert kwargs["object_name"].startswith("report/5/valid_key/")
        assert kwargs["file"] == b"docx"

    monkeypatch.setattr(report, "bisheng_settings", Mock(get_from_db=lambda key: SECRET))
    monkeypatch.setattr(report, "resolve_callback_report", resolve)
    monkeypatch.setattr(report, "afetch_office_document", fetch)
    monkeypatch.setattr(
        report, "get_minio_storage", AsyncMock(return_value=SimpleNamespace(bucket="bucket", put_object=put))
    )
    save = Mock(return_value=True)
    monkeypatch.setattr(report.ReportRepository, "save_callback", save)
    with tenant_execution_scope(99):
        assert await report.callback({**body, "token": jwt.encode(body, SECRET, algorithm="HS256")}) == {"error": 0}
        assert get_current_tenant_id() == 99
    assert events == ["authorize", "fetch", "write"]
    assert save.call_args.args[:2] == (5, "valid_key")


@pytest.fixture
def report_db(monkeypatch):
    from contextlib import contextmanager

    from sqlalchemy.pool import StaticPool
    from sqlmodel import Session, create_engine

    from bisheng.api.services import report_repository
    from bisheng.database.models.report import Report

    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Report.__table__.create(engine)
    for model in (report_repository.User, report_repository.Tenant, report_repository.UserTenant):
        model.__table__.create(engine)

    @contextmanager
    def session():
        with Session(engine) as value:
            yield value

    monkeypatch.setattr(report_repository, "get_sync_db_session", session)
    yield SimpleNamespace(session=session, model=Report, repo=report_repository.ReportRepository)
    engine.dispose()


def test_repository_rejects_deleted_duplicate_and_stale_keys(report_db):
    with tenant_execution_scope(2):
        with report_db.session() as session:
            session.add(report_db.model(id=1, flow_id="wf", tenant_id=2, version_key="old", newversion_key="active"))
            session.add(report_db.model(id=2, flow_id="deleted", tenant_id=2, version_key="deleted", del_yn=1))
            session.commit()
        assert report_db.repo.find_by_key("missing") is None
        assert report_db.repo.find_by_key("deleted") is None
        assert report_db.repo.find_by_key("old") is None
        assert not report_db.repo.save_callback(1, "old", "should-not-write")
        assert report_db.repo.find_by_key("active").id == 1
        assert report_db.repo.save_callback(1, "active", "report/immutable.docx")
        row = report_db.repo.find_by_key("active")
        assert (row.object_name, row.version_key, row.newversion_key) == ("report/immutable.docx", "active", None)
        with report_db.session() as session:
            session.add(report_db.model(id=3, flow_id="other", tenant_id=2, newversion_key="active"))
            session.commit()
        assert report_db.repo.find_by_key("active") is None


def test_repository_editor_must_remain_active(report_db):
    from bisheng.api.services import report_repository as repository

    with tenant_execution_scope(2):
        with report_db.session() as session:
            session.add(repository.User(user_id=7, user_name="editor", password="test-only-hash"))
            session.add(repository.Tenant(id=2, tenant_code="t2", tenant_name="test"))
            session.add(repository.UserTenant(user_id=7, tenant_id=2, is_active=1))
            session.commit()
        assert report_db.repo.editor_is_active(7, 2)
        assert not report_db.repo.editor_is_active(7, 3)
        with report_db.session() as session:
            user = session.get(repository.User, 7)
            user.delete = 1
            session.add(user)
            session.commit()
        assert not report_db.repo.editor_is_active(7, 2)


async def test_viewer_cannot_mint_report_edit_version(monkeypatch):
    from bisheng.common.errcode.http_error import UnAuthorizedError

    permission = AsyncMock(return_value=False)
    monkeypatch.setattr(report, "check_business_action", permission)
    db = Mock(side_effect=AssertionError("viewer reached report write"))
    monkeypatch.setattr(report, "get_sync_db_session", db)
    with pytest.raises(UnAuthorizedError):
        await report.get_template(flow_id="wf", login_user=SimpleNamespace(user_id=7, tenant_id=2))
    assert permission.await_args.kwargs["action"] == "edit"
    db.assert_not_called()


async def test_issuer_returns_only_authorized_editor_signature(editor_boundary, monkeypatch):
    monkeypatch.setattr(report, "bisheng_settings", Mock(get_from_db=lambda key: SECRET))
    payload = _editor()
    response = await report.get_office_token(payload, login_user=SimpleNamespace(user_id=7, tenant_id=2))
    assert jwt.decode(response.data["token"], SECRET, algorithms=["HS256"]) == response.data["config"]
    assert response.data["config"]["document"]["url"] == "https://minio.local/empty-signed"
    assert payload["document"]["url"] == ""


def test_repository_foreign_tenant_is_not_visible(report_db):
    with tenant_execution_scope(3):
        with report_db.session() as session:
            session.add(report_db.model(id=1, flow_id="foreign", tenant_id=3, version_key="foreign-key"))
            session.commit()
    with tenant_execution_scope(2):
        assert report_db.repo.find_by_key("foreign-key") is None
        assert not report_db.repo.save_callback(1, "foreign-key", "forbidden")


async def test_fastapi_callback_accepts_document_server_header(monkeypatch):
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient

    app = FastAPI()
    app.include_router(report.router)
    body = _body()
    token = jwt.encode({"payload": body}, SECRET, algorithm="HS256")
    monkeypatch.setattr(report, "bisheng_settings", Mock(get_from_db=lambda key: SECRET))
    resolve = AsyncMock(return_value=None)
    monkeypatch.setattr(report, "resolve_callback_report", resolve)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/report/callback", json=body, headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 200
        assert response.json() == {"error": 1}
    resolve.assert_awaited_once_with("valid_key")

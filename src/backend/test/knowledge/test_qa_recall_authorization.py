"""Recall endpoints require a current message/session and source-file entitlement."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import httpx
import pytest
from fastapi import FastAPI, HTTPException

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.http_error import UnAuthorizedError
from bisheng.core.context.tenant import current_tenant_id


@pytest.fixture
def harness(monkeypatch):
    from bisheng.knowledge.domain.services import qa_recall_service as service

    message = SimpleNamespace(id=42, chat_id="own", flow_id="app", tenant_id=1, user_id=7)
    session = SimpleNamespace(
        chat_id="own", flow_id="app", tenant_id=1, user_id=7, is_delete=False, api_subject_type=None
    )
    chunk = SimpleNamespace(
        message_id=42,
        chat_id="own",
        file_id=9,
        keywords='["canary"]',
        chunk="canary",
        meta_data=json.dumps({"bbox": '{"page":1}', "right": True}),
    )
    file = SimpleNamespace(id=9, tenant_id=1, file_name="private.pdf", parse_type="local")
    repo = SimpleNamespace(
        parent=Mock(return_value=(message, session)), chunks=Mock(return_value=[chunk]), files=Mock(return_value=[file])
    )
    audit = AsyncMock(side_effect=UnAuthorizedError())
    permission = AsyncMock(return_value=None)
    sign = Mock(return_value=("signed-original", "signed-preview"))
    monkeypatch.setattr(service, "QaRecallRepository", repo)
    monkeypatch.setattr(service.AuditLogService, "assert_session_in_audit_scope", audit)
    monkeypatch.setattr(service, "require_business_action", permission)
    monkeypatch.setattr(service.KnowledgeService, "get_file_share_url", sign)
    tid = current_tenant_id.set(1)
    try:
        yield SimpleNamespace(
            service=service.QaRecallService,
            repo=repo,
            message=message,
            session=session,
            chunk=chunk,
            file=file,
            audit=audit,
            permission=permission,
            sign=sign,
            user=SimpleNamespace(user_id=7, tenant_id=1),
        )
    finally:
        current_tenant_id.reset(tid)


async def test_owner_gets_keywords_and_authorized_source(harness):
    h = harness
    assert await h.service.keywords(h.user, 42) == ["canary"]
    result = await h.service.original_files(h.user, 42, "canary")
    assert result[0]["original_url"] == "signed-original"
    assert result[0]["page"] == 1
    h.permission.assert_awaited_once_with(h.user, resource_type="knowledge_file", resource_id=9, action="download")
    h.audit.assert_not_awaited()


@pytest.mark.parametrize("operation", ["keywords", "original_files"])
async def test_nonowner_denied_before_recall_query(harness, operation):
    h = harness
    h.user.user_id = 8
    with pytest.raises(UnAuthorizedError):
        await (h.service.keywords(h.user, 42) if operation == "keywords" else h.service.original_files(h.user, 42, ""))
    h.repo.chunks.assert_not_called()
    h.sign.assert_not_called()


@pytest.mark.parametrize(
    "change", ["message_tenant", "session_tenant", "deleted", "wrong_app", "wrong_owner", "missing"]
)
async def test_invalid_parent_denied_before_audit_or_recall(harness, change):
    h = harness
    if change == "message_tenant":
        h.message.tenant_id = 2
    elif change == "session_tenant":
        h.session.tenant_id = 2
    elif change == "deleted":
        h.session.is_delete = True
    elif change == "wrong_app":
        h.session.flow_id = "foreign"
    elif change == "wrong_owner":
        h.message.user_id = 99
    else:
        h.repo.parent.return_value = None
    with pytest.raises(HTTPException) as exc:
        await h.service.keywords(h.user, 42)
    assert exc.value.status_code == 404
    h.repo.chunks.assert_not_called()
    h.audit.assert_not_awaited()


async def test_explicit_audit_reader_keeps_access(harness):
    h = harness
    h.user.user_id = 8
    h.audit.side_effect = None
    assert await h.service.keywords(h.user, 42) == ["canary"]
    h.audit.assert_awaited_once_with(h.user, "own", session_owner_id=7, app_id="app")


@pytest.mark.parametrize("allowed", [False, True])
async def test_api_subject_does_not_inherit_operator_ownership(harness, allowed):
    h = harness
    h.session.api_subject_type = "public_v3"
    if allowed:
        h.audit.side_effect = None
        assert await h.service.keywords(h.user, 42) == ["canary"]
    else:
        with pytest.raises(UnAuthorizedError):
            await h.service.keywords(h.user, 42)
        h.repo.chunks.assert_not_called()
    h.audit.assert_awaited_once_with(h.user, "own", session_owner_id=None, app_id="app")


async def test_source_permission_denial_returns_right_false_tip(harness):
    h = harness
    h.permission.side_effect = UnAuthorizedError()
    result = await h.service.original_files(h.user, 42, "")
    assert len(result) == 1
    assert result[0]["right"] is False
    assert result[0]["original_url"] == ""
    assert result[0]["preview_url"] == ""
    assert result[0]["source"] == "private.pdf"
    h.sign.assert_not_called()


async def test_foreign_source_hidden_before_permission_shortcut(harness):
    h = harness
    h.file.tenant_id = 2
    assert await h.service.original_files(h.user, 42, "") == []
    h.permission.assert_not_awaited()
    h.sign.assert_not_called()


async def test_explicitly_visible_root_source_still_requires_current_action(harness):
    from bisheng.core.context.tenant import visible_tenant_ids

    h = harness
    h.file.tenant_id = 2
    token = visible_tenant_ids.set(frozenset({1, 2}))
    try:
        assert (await h.service.original_files(h.user, 42, ""))[0]["original_url"] == "signed-original"
        h.permission.assert_awaited_once()
    finally:
        visible_tenant_ids.reset(token)


async def test_permission_runtime_failure_never_signs(harness):
    h = harness
    h.permission.side_effect = RuntimeError("permission service unavailable")
    with pytest.raises(RuntimeError):
        await h.service.original_files(h.user, 42, "")
    h.sign.assert_not_called()


async def test_missing_context_denies_before_repository(harness):
    h = harness
    token = current_tenant_id.set(None)
    try:
        with pytest.raises(HTTPException):
            await h.service.keywords(h.user, 42)
        h.repo.parent.assert_not_called()
    finally:
        current_tenant_id.reset(token)


async def test_stale_right_false_is_not_authority_to_reveal_bbox(harness):
    h = harness
    h.chunk.meta_data = json.dumps({"right": False, "bbox": '{"secret":"hidden"}'})
    assert await h.service.original_files(h.user, 42, "") == []
    h.sign.assert_not_called()


async def test_chunk_cannot_bind_a_different_chat(harness):
    h = harness
    h.chunk.chat_id = "foreign"
    assert await h.service.original_files(h.user, 42, "") == []
    h.permission.assert_not_awaited()
    h.sign.assert_not_called()


@pytest.mark.parametrize(
    "method,path,body", [("GET", "/keyword?message_id=42", None), ("POST", "/chunk", {"message_id": 42, "keys": ""})]
)
async def test_anonymous_is_rejected_before_service(monkeypatch, method, path, body):
    from bisheng.knowledge.api.endpoints import qa
    from bisheng.knowledge.domain.services.qa_recall_service import QaRecallService

    app = FastAPI()
    app.include_router(qa.router, prefix="/api/v1")

    async def refuse():
        raise HTTPException(401, "Authentication required")

    app.dependency_overrides[UserPayload.get_login_user] = refuse
    calls = AsyncMock()
    monkeypatch.setattr(QaRecallService, "keywords", calls)
    monkeypatch.setattr(QaRecallService, "original_files", calls)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.request(method, "/api/v1/qa" + path, json=body)
    assert response.status_code == 401
    calls.assert_not_awaited()

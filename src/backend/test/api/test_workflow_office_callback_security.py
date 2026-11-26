"""Workflow callback must authenticate the document server before its key ticket."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import jwt
import pytest

from bisheng.api.v1 import workflow

SECRET = "test-only-workflow-office-key-at-least-32-bytes"


def body():
    return {"status": 2, "url": "http://office.local/cache/a.docx", "key": "abc_1700000000000"}


@pytest.fixture
def boundary(monkeypatch):
    session = AsyncMock(return_value={"workflow_id": "wf", "can_edit": True})
    fetch = AsyncMock(return_value=b"docx")
    storage = SimpleNamespace(bucket="bucket", put_object=AsyncMock())
    monkeypatch.setattr(workflow, "bisheng_settings", SimpleNamespace(get_from_db=lambda key: SECRET))
    monkeypatch.setattr(workflow.report_template, "aget_edit_session", session)
    monkeypatch.setattr(workflow, "afetch_office_document", fetch)
    monkeypatch.setattr(workflow, "get_minio_storage", AsyncMock(return_value=storage))
    return SimpleNamespace(session=session, fetch=fetch, storage=storage)


@pytest.mark.parametrize(
    "kind",
    [
        "unsigned",
        "wrong",
        "none",
        "expired",
        "editor",
        "tampered_key",
        "tampered_url",
        "tampered_status",
        "empty_secret",
    ],
)
async def test_invalid_authentication_precedes_session_and_network(boundary, monkeypatch, kind):
    data = body()
    payload = (
        {**data, "exp": 1} if kind == "expired" else {"document": {"key": data["key"]}} if kind == "editor" else data
    )
    if kind != "unsigned":
        token = jwt.encode(
            payload, "different-office-key-with-at-least32bytes" if kind == "wrong" else SECRET, algorithm="HS256"
        )
        if kind == "none":
            token = jwt.encode(payload, "", algorithm="none")
        data = {**data, "token": token}
    if kind.startswith("tampered_"):
        data[kind.removeprefix("tampered_")] = 6 if kind == "tampered_status" else "victim"
    if kind == "empty_secret":
        monkeypatch.setattr(workflow, "bisheng_settings", SimpleNamespace(get_from_db=lambda key: ""))
    assert await workflow.upload_report_file(SimpleNamespace(headers={}), data) == {"error": 1}
    boundary.session.assert_not_awaited()
    boundary.fetch.assert_not_awaited()
    boundary.storage.put_object.assert_not_awaited()


@pytest.mark.parametrize("header", [False, True])
async def test_signed_callback_preserves_document_save(boundary, header):
    data = body()
    token = jwt.encode({"payload": data} if header else data, SECRET, algorithm="HS256")
    request = SimpleNamespace(headers={"authorization": f"Bearer {token}"} if header else {})
    if not header:
        data = {**data, "token": token}
    assert await workflow.upload_report_file(request, data) == {"error": 0}
    boundary.storage.put_object.assert_awaited_once_with(
        object_name="workflow/report/abc.docx",
        file=b"docx",
        bucket_name="bucket",
        content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )


@pytest.mark.parametrize("session", [None, {"workflow_id": "wf", "can_edit": False}])
async def test_signed_callback_still_requires_editor_ticket(boundary, session):
    boundary.session.return_value = session
    data = body()
    data = {**data, "token": jwt.encode(data, SECRET, algorithm="HS256")}
    assert await workflow.upload_report_file(SimpleNamespace(headers={}), data) == {"error": 1}
    boundary.fetch.assert_not_awaited()
    boundary.storage.put_object.assert_not_awaited()

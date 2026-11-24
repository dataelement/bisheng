"""Canonical editor sources: no user-supplied URL signing bypass."""

from io import BytesIO
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from docx import Document
from fastapi import HTTPException

from bisheng.api.services import report_editor_security as security


@pytest.fixture
def source_boundary(monkeypatch):
    minio = SimpleNamespace(
        bucket="bucket",
        tmp_bucket="tmp",
        get_minio_share_host=lambda: "https://minio.local",
        put_object=AsyncMock(),
        get_share_link=AsyncMock(return_value="https://minio.local/canonical-signed"),
    )
    row = SimpleNamespace(id=5, tenant_id=2, flow_id="wf", object_name=None)
    redis = SimpleNamespace(aset=AsyncMock())
    monkeypatch.setattr(security.ReportRepository, "find_by_key", Mock(return_value=row))
    monkeypatch.setattr(security, "get_redis_client", AsyncMock(return_value=redis))
    monkeypatch.setattr(security, "check_business_action", AsyncMock(return_value=True))
    monkeypatch.setattr(security, "get_minio_storage", AsyncMock(return_value=minio))
    monkeypatch.setattr(
        security,
        "settings",
        SimpleNamespace(open_api=SimpleNamespace(public_base_url="https://portal.local/bisheng")),
        raising=False,
    )
    return SimpleNamespace(minio=minio, row=row, user=SimpleNamespace(user_id=7, tenant_id=2))


def editor(**extensions):
    return {
        "documentType": "word",
        "document": {"fileType": "docx", "key": "active", "url": ""},
        "editorConfig": {"callbackUrl": "https://untrusted.invalid/bisheng/api/v1/report/callback"},
        **extensions,
    }


def workflow_payload(payload, monkeypatch):
    flow_id = "a" * 32
    key = flow_id + "-" + "b" * 32 + "_123"
    payload["document"]["key"] = key
    payload["editorConfig"]["callbackUrl"] = "https://untrusted.invalid/bisheng/api/v1/workflow/report/callback"
    monkeypatch.setattr(
        security.report_template,
        "aget_edit_session",
        AsyncMock(return_value={"workflow_id": flow_id, "can_edit": True}),
    )
    return key


@pytest.mark.parametrize("workflow", [False, True])
async def test_empty_source_generated_and_callback_canonical(source_boundary, monkeypatch, workflow):
    payload = editor(source_kind="empty")
    if workflow:
        workflow_payload(payload, monkeypatch)
    config = await security.authorize_editor(payload, source_boundary.user)
    assert config["document"]["url"] == "https://minio.local/canonical-signed"
    route = "workflow/report/callback" if workflow else "report/callback"
    assert config["editorConfig"]["callbackUrl"] == "https://portal.local/bisheng/api/v1/" + route
    assert "source_kind" not in config
    data = source_boundary.minio.put_object.await_args.kwargs["file"]
    assert Document(BytesIO(data)).paragraphs[0].text == ""
    assert payload["document"]["url"] == ""


async def test_missing_public_base_fails_closed(source_boundary, monkeypatch):
    monkeypatch.setattr(
        security, "settings", SimpleNamespace(open_api=SimpleNamespace(public_base_url="")), raising=False
    )
    with pytest.raises(HTTPException) as error:
        await security.authorize_editor(editor(source_kind="empty"), source_boundary.user)
    assert error.value.status_code == 503
    source_boundary.minio.put_object.assert_not_awaited()


async def test_empty_cannot_smuggle_source_url(source_boundary):
    payload = editor(source_kind="empty")
    payload["document"]["url"] = "http://169.254.169.254/"
    with pytest.raises(HTTPException):
        await security.authorize_editor(payload, source_boundary.user)
    source_boundary.minio.put_object.assert_not_awaited()


@pytest.mark.parametrize("workflow", [False, True])
@pytest.mark.parametrize("reason", ["valid", "foreign", "mismatch", "fake_signature"])
async def test_import_requires_registry_binding_and_real_signature(source_boundary, monkeypatch, reason, workflow):
    from datetime import timedelta

    from minio import Minio

    from bisheng.core.context.tenant import tenant_execution_scope

    minio = source_boundary.minio
    minio.minio_config = SimpleNamespace(access_key="fixture-access", secret_key="fixture-secret-at-least-32bytes")
    client = Minio(
        "minio.local",
        access_key=minio.minio_config.access_key,
        secret_key=minio.minio_config.secret_key,
        secure=True,
        region="us-east-1",
    )
    url = client.presigned_get_object("tmp", "uploads/2/7/import.docx", expires=timedelta(minutes=5))
    payload = editor(preview_upload_ref="issued-reference")
    if workflow:
        workflow_payload(payload, monkeypatch)
    payload["document"]["url"] = url
    source = SimpleNamespace(bucket="tmp", object_name="uploads/2/7/import.docx", file_name="import.docx")
    resolve = AsyncMock(return_value=source)
    monkeypatch.setattr(security.PreviewSourceService, "resolve", resolve)
    monkeypatch.setattr(security.PreviewSourceService, "is_owned_object", AsyncMock(return_value=reason != "foreign"))
    if reason == "mismatch":
        source.object_name = "uploads/2/other.docx"
    if reason == "fake_signature":
        payload["document"]["url"] = url.replace("X-Amz-Signature=", "X-Amz-Signature=0")
    with tenant_execution_scope(2):
        if reason == "valid":
            config = await security.authorize_editor(payload, source_boundary.user)
            assert config["document"]["url"] == "https://minio.local/canonical-signed"
            assert "preview_upload_ref" not in config
            minio.get_share_link.assert_awaited_once_with(source.object_name, "tmp", clear_host=False)
        else:
            with pytest.raises(HTTPException):
                await security.authorize_editor(payload, source_boundary.user)
            minio.get_share_link.assert_not_awaited()
    assert resolve.await_args.kwargs["knowledge_id"] == 0
    assert resolve.await_args.kwargs["item"].file_path == payload["document"]["url"]


@pytest.mark.parametrize("workflow", [False, True])
async def test_existing_document_source_represigned(source_boundary, monkeypatch, workflow):
    payload = editor()
    if workflow:
        key = workflow_payload(payload, monkeypatch).split("_", 1)[0]
        object_name = f"workflow/report/{key}.docx"
    else:
        object_name = "report/stored.docx"
        source_boundary.row.object_name = object_name
    payload["document"]["url"] = f"https://minio.local/bucket/{object_name}?old-signature=preserved-source"
    config = await security.authorize_editor(payload, source_boundary.user)
    assert config["document"]["url"] == "https://minio.local/canonical-signed"
    source_boundary.minio.get_share_link.assert_awaited_once_with(object_name, "bucket", clear_host=False)
    source_boundary.minio.put_object.assert_not_awaited()


@pytest.mark.parametrize(
    "base",
    [
        "https://user@portal.local/bisheng",
        "ftp://portal.local",
        "https://portal.local/../evil",
        "https://portal.local?x=1",
    ],
)
async def test_invalid_trusted_callback_base_refused(source_boundary, monkeypatch, base):
    monkeypatch.setattr(security, "settings", SimpleNamespace(open_api=SimpleNamespace(public_base_url=base)))
    with pytest.raises(HTTPException):
        await security.authorize_editor(editor(source_kind="empty"), source_boundary.user)
    source_boundary.minio.put_object.assert_not_awaited()

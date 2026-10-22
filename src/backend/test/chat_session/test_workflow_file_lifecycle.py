"""Regressions for upload rollback, source identity, and durable cleanup."""

import json
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from fastapi import FastAPI, HTTPException
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel import Session, select
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.chat_session.domain.chat import ChatSessionService
from bisheng.chat_session.domain.models.workflow_file_manifest import WorkflowFileManifest
from bisheng.chat_session.domain.repositories import workflow_file_repository as repository_module
from bisheng.chat_session.domain.repositories.workflow_file_repository import WorkflowFileRepository, source_identity
from bisheng.chat_session.domain.services.chat_message_service import ChatMessageService
from bisheng.chat_session.domain.services.workflow_file_service import WorkflowFileService
from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.database.models.message import ChatMessage
from bisheng.database.models.session import MessageSession
from bisheng.knowledge.rag.pipeline.transformer.image_upload import ImageUploadTransformer
from bisheng.knowledge.rag.pipeline.types import ImageStorageContext
from test.chat_session.test_workflow_file_assets import database as _database_fixture
from test.chat_session.test_workflow_file_assets import not_found_response as _not_found_fixture

database = _database_fixture
not_found_response = _not_found_fixture

SOURCE = "http://storage/tmp/a.pdf?old"


@pytest.fixture
async def async_database(database, monkeypatch):
    engine = create_async_engine(str(database.url).replace("sqlite:", "sqlite+aiosqlite:"))

    @asynccontextmanager
    async def connection():
        async with AsyncSession(engine, expire_on_commit=False) as session:
            yield session

    monkeypatch.setattr(repository_module, "get_async_db_session", connection)
    monkeypatch.setattr("bisheng.database.models.session.get_async_db_session", connection)
    monkeypatch.setattr("bisheng.database.models.message.get_sync_db_session", repository_module.get_sync_db_session)
    monkeypatch.setattr("bisheng.chat_session.domain.chat.FlowDao.aget_flow_by_id", AsyncMock(return_value=None))
    monkeypatch.setattr("bisheng.chat_session.domain.chat.telemetry_service.log_event", AsyncMock())
    try:
        yield database
    finally:
        await engine.dispose()


@pytest.fixture
def storage(monkeypatch):
    objects = {}
    client = MagicMock(bucket="main", tmp_bucket="tmp")
    client.get_minio_share_host.return_value = "http://storage"
    client.put_object_sync.side_effect = lambda **kw: objects.update({kw["object_name"]: Path(kw["file"]).read_bytes()})
    client.remove_object_sync.side_effect = lambda **kw: objects.pop(kw["object_name"], None)
    client.remove_object = AsyncMock(side_effect=lambda **kw: objects.pop(kw["object_name"], None))
    client.get_share_link = AsyncMock(side_effect=lambda key: f"/main/{key}?fresh")
    client.objects = objects
    monkeypatch.setattr(
        "bisheng.chat_session.domain.services.workflow_file_service.get_minio_storage_sync", lambda: client
    )
    monkeypatch.setattr(
        "bisheng.knowledge.rag.pipeline.transformer.image_upload.get_minio_storage_sync", lambda: client
    )
    monkeypatch.setattr("bisheng.chat_session.domain.chat.get_minio_storage", AsyncMock(return_value=client))
    return client


def _context(source_url=SOURCE):
    return WorkflowFileService.image_storage(
        chat_id="c1",
        user_id=7,
        tenant_id=1,
        workflow_id="wf",
        run_id="run",
        node_id="input",
        source_url=source_url,
        file_name="a.pdf",
    )


def _upload(context, tmp_path):
    image_dir = tmp_path / "staging"
    image_dir.mkdir(parents=True, exist_ok=True)
    (image_dir / "figure.png").write_bytes(b"image-bytes")
    loader = SimpleNamespace(local_image_dir=str(image_dir), image_object_dir=context.object_dir)
    return ImageUploadTransformer(loader, "file", 0, storage=context).transform_documents([])


@pytest.mark.parametrize("with_context", [False, True])
def test_legacy_upload_failure_does_not_delete_previously_published_image(tmp_path, storage, monkeypatch, with_context):
    """AC-09: knowledge/preview uploads retain their established failure behavior."""
    prefix = "knowledge/images/42/99"
    storage.objects[f"{prefix}/one.png"] = b"published-image"
    (tmp_path / "one.png").write_bytes(b"published-image")
    (tmp_path / "two.png").write_bytes(b"second-image")
    successful_put = storage.put_object_sync.side_effect
    count = 0

    def put(**kw):
        nonlocal count
        count += 1
        if count == 2:
            raise OSError("second upload failed")
        successful_put(**kw)

    storage.put_object_sync.side_effect = put
    monkeypatch.setattr(
        "bisheng.knowledge.rag.pipeline.transformer.image_upload.os.listdir", lambda _: ["one.png", "two.png"]
    )
    loader = SimpleNamespace(local_image_dir=str(tmp_path), image_object_dir=prefix)
    context = ImageStorageContext(prefix, "main", lambda name: name) if with_context else None
    with pytest.raises(OSError, match="second upload failed"):
        ImageUploadTransformer(loader, "99", 42, storage=context).transform_documents([])
    assert storage.objects[f"{prefix}/one.png"] == b"published-image"
    storage.remove_object_sync.assert_not_called()


async def test_retry_rollback_keeps_old_ready_image_and_removes_only_new_attempt(async_database, storage, tmp_path):
    """AC-05, AC-08: a failed retry cannot invalidate an earlier historical image."""
    completed = _context()
    _upload(completed, tmp_path / "completed")
    old_key = f"{completed.object_dir}/figure.png"
    with Session(async_database) as session:
        ready = json.loads(session.exec(select(WorkflowFileManifest)).one().files)[0]["derived_assets"][0]
    retry = _context()
    assert retry.object_dir != completed.object_dir
    retry.after_upload = MagicMock(side_effect=OSError("finalize failed"))
    with pytest.raises(OSError, match="finalize failed"):
        _upload(retry, tmp_path / "retry")
    assert storage.objects == {old_key: b"image-bytes"}
    url = await ChatSessionService.resolve_attachment_url(
        "c1", ready["file_id"], SimpleNamespace(user_id=7, tenant_id=1)
    )
    assert old_key in url
    with pytest.raises(ValueError, match="cannot be reused"):
        completed.before_upload(["figure.png"])


@pytest.mark.parametrize("delete_during_upload", [False, True])
async def test_question_deletion_keeps_image_access_and_session_cleanup(
    async_database, storage, tmp_path, delete_during_upload
):
    """AC-05, AC-08: source and images remain tracked after deleting their question."""
    with Session(async_database) as session:
        question_id = session.exec(select(ChatMessage)).one().id
    context = _context()
    if delete_during_upload:
        register = context.before_upload

        def register_then_delete(names):
            register(names)
            ChatMessageService.delete_message(7, str(question_id))

        context.before_upload = register_then_delete
    _upload(context, tmp_path)
    if not delete_during_upload:
        ChatMessageService.delete_message(7, str(question_id))
    messages = await WorkflowFileRepository.attachment_messages("c1")
    assert len(messages) == 1 and isinstance(messages[0], WorkflowFileManifest)
    attachment = json.loads(messages[0].files)[0]
    image = attachment["derived_assets"][0]
    owner = SimpleNamespace(user_id=7, tenant_id=1)
    assert image["object_name"] in await ChatSessionService.resolve_attachment_url("c1", image["file_id"], owner)
    storage.objects[attachment["object_name"]] = b"retained-original"
    await ChatSessionService.delete_session("c1", owner, "127.0.0.1")
    assert storage.objects == {}
    removed = {c.kwargs["object_name"] for c in storage.remove_object.await_args_list}
    assert removed == {image["object_name"], attachment["object_name"]}
    with pytest.raises(HTTPException) as exc:
        await ChatSessionService.resolve_attachment_url("c1", image["file_id"], owner)
    assert exc.value.status_code == 404


@pytest.mark.parametrize("deleted", [False, True])
@pytest.mark.parametrize(
    "user_id,tenant_id,subject", [(99, 1, None), (7, 2, None), (7, 1, "service_account"), (7, 1, "public_v3")]
)
async def test_first_and_repeat_delete_refuse_nonowners_before_any_side_effect(
    monkeypatch, deleted, user_id, tenant_id, subject
):
    """AC-07: initial deletion and retries apply the same natural-person boundary."""
    session = SimpleNamespace(user_id=7, tenant_id=1, api_subject_type=subject, is_delete=deleted)
    monkeypatch.setattr(
        "bisheng.chat_session.domain.chat.MessageSessionDao.async_get_one", AsyncMock(return_value=session)
    )
    remove = AsyncMock()
    delete = AsyncMock()
    audit = AsyncMock()
    monkeypatch.setattr(ChatSessionService, "_remove_attachments", remove)
    monkeypatch.setattr(WorkflowFileRepository, "soft_delete_owned_session", delete)
    monkeypatch.setattr("bisheng.chat_session.domain.chat.AuditLogService.delete_chat_workflow", audit)
    with pytest.raises(HTTPException) as exc:
        await ChatSessionService.delete_session(
            "c1", SimpleNamespace(user_id=user_id, tenant_id=tenant_id), "127.0.0.1"
        )
    assert exc.value.status_code == 404
    remove.assert_not_awaited()
    delete.assert_not_awaited()
    audit.assert_not_awaited()


@pytest.mark.parametrize("deleted", [False, True])
async def test_owner_can_delete_and_repeat_failed_physical_cleanup(async_database, storage, deleted):
    """AC-08: a failed object removal stays discoverable for a repeated deletion."""
    context = _context()
    context.before_upload(["figure.png"])
    with Session(async_database) as session:
        row = session.exec(select(MessageSession)).one()
        row.is_delete = deleted
        session.add(row)
        session.commit()
    storage.remove_object.side_effect = OSError("storage unavailable")
    owner = SimpleNamespace(user_id=7, tenant_id=1)
    await ChatSessionService.delete_session("c1", owner, "127.0.0.1")
    with Session(async_database) as session:
        assert session.exec(select(MessageSession)).one().is_delete is True
    storage.remove_object.reset_mock(side_effect=True)
    await ChatSessionService.delete_session("c1", owner, "127.0.0.1")
    assert {c.kwargs["object_name"] for c in storage.remove_object.await_args_list} == {
        "chat/7/original.pdf",
        f"{context.object_dir}/figure.png",
    }


@pytest.mark.parametrize(
    "user_id,tenant_id,subject,deleted",
    [
        (99, 1, None, False),
        (7, 2, None, False),
        (7, 1, "service_account", False),
        (7, 1, None, True),
    ],
)
async def test_bulk_delete_predicate_binds_user_tenant_and_subject(
    async_database, user_id, tenant_id, subject, deleted
):
    """AC-07: bulk UPDATE remains scoped even when SELECT tenant filtering is bypassed."""
    with Session(async_database) as session:
        row = session.exec(select(MessageSession)).one()
        row.api_subject_type = subject
        session.add(row)
        session.commit()
    await WorkflowFileRepository.soft_delete_owned_session("c1", user_id=user_id, tenant_id=tenant_id)
    with Session(async_database) as session:
        assert session.exec(select(MessageSession)).one().is_delete is deleted


@pytest.mark.parametrize(
    "first,second",
    [
        ("https://first.example/reports/a.pdf", "https://second.example/reports/a.pdf"),
        ("https://files.example/download?id=1", "https://files.example/download?id=2"),
        ("https://files.example/a%2Fb.pdf", "https://files.example/a/b.pdf"),
        ("https://Alice:Pass@files.example/a.pdf", "https://alice:pass@files.example/a.pdf"),
    ],
)
def test_external_source_identity_preserves_origin_and_business_parameters(first, second):
    """AC-07: unrelated HTTP resources must not normalize to the same identity."""
    assert source_identity(first) != source_identity(second)


def test_own_minio_signatures_normalize_without_discarding_business_parameters():
    """AC-05, AC-07: signed absolute/relative links identify the same stored object."""

    def normalize(url):
        return source_identity(url, storage_host="http://storage", buckets=("main", "tmp"))

    first = normalize("http://storage/tmp/a.pdf?X-Amz-Date=first&X-Amz-Signature=one&id=1")
    assert first == normalize("/tmp/a.pdf?X-Amz-Date=second&X-Amz-Signature=two&id=1")
    assert first != normalize("http://other/tmp/a.pdf?X-Amz-Date=first&X-Amz-Signature=one&id=1")
    assert first != normalize("http://storage/tmp/a.pdf?id=2")
    assert normalize("/tmp/a%3Fb%3D") != normalize("/tmp/a?b=")


@pytest.mark.parametrize(
    "urls",
    [
        ["https://first.example/a.pdf", "https://second.example/a.pdf"],
        ["https://files.example/download?id=1", "https://files.example/download?id=2"],
    ],
)
def test_manifest_matches_the_correct_external_attachment(database, storage, monkeypatch, urls):
    """AC-07: both object identity and source-attachment matching retain the origin."""
    monkeypatch.setattr(
        "bisheng.chat_session.domain.services.workflow_file_service.uuid4", lambda: SimpleNamespace(hex="fixed")
    )
    with Session(database) as session:
        row = session.exec(select(ChatMessage)).one()
        row.files = json.dumps(
            [{"file_id": str(i), "file_url": url, "object_name": f"chat/7/source{i}.pdf"} for i, url in enumerate(urls)]
        )
        session.add(row)
        session.commit()
    contexts = [_context(url) for url in urls]
    assert contexts[0].object_dir != contexts[1].object_dir
    contexts[1].before_upload(["figure.png"])
    with Session(database) as session:
        files = json.loads(session.exec(select(ChatMessage)).one().files)
    assert "derived_assets" not in files[0]
    assert files[1]["derived_assets"][0]["object_name"].startswith(contexts[1].object_dir)


async def test_http_image_access_and_delete_use_real_ownership_and_cleanup(async_database, storage, tmp_path):
    """AC-05, AC-07, AC-08: HTTP authorization reaches the real services and SQL."""
    from bisheng.chat_session.api.endpoints.chat import router as chat_router
    from bisheng.chat_session.api.endpoints.workflow_files import router as file_router

    context = _context()
    _upload(context, tmp_path)
    with Session(async_database) as session:
        attachment = json.loads(session.exec(select(WorkflowFileManifest)).one().files)[0]
    image = attachment["derived_assets"][0]
    app = FastAPI()
    app.include_router(chat_router, prefix="/api/v1")
    app.include_router(file_router, prefix="/api/v1")
    app.dependency_overrides[UserPayload.get_login_user] = lambda: SimpleNamespace(user_id=99, tenant_id=1)
    transport = httpx.ASGITransport(app=app)
    image_path = context.url_builder("figure.png")
    async with httpx.AsyncClient(transport=transport, base_url="http://test", follow_redirects=False) as client:
        response = await client.get(image_path)
        assert response.status_code == 404 and "location" not in response.headers
        assert (await client.delete("/api/v1/chat/c1")).status_code == 404
        assert image["object_name"] in storage.objects
        storage.remove_object.assert_not_awaited()
        app.dependency_overrides[UserPayload.get_login_user] = lambda: SimpleNamespace(user_id=7, tenant_id=1)
        response = await client.get(image_path)
        assert response.status_code == 307 and image["object_name"] in response.headers["location"]
        response = await client.delete("/api/v1/chat/c1")
        assert response.status_code == 200 and response.json()["status_code"] == 200
        assert storage.objects == {}
        response = await client.get(image_path)
        assert response.status_code == 404 and "location" not in response.headers


def test_independent_manifest_model_is_discovered_for_schema_bootstrap():
    """AC-08, AC-09: online upgrades discover the new standalone table."""
    from bisheng.core.database.model_discovery import discover_sqlmodel_module_names

    assert "bisheng.chat_session.domain.models.workflow_file_manifest" in discover_sqlmodel_module_names()


async def test_manifest_keyset_scan_includes_all_pages_after_questions_are_deleted(async_database):
    """AC-08: independent manifests cannot be stranded beyond the first 500 rows."""
    with Session(async_database) as session:
        for index in range(1001):
            session.add(WorkflowFileManifest(id=f"{index:064x}", tenant_id=1, user_id=7, chat_id="c1", files="[]"))
        question_id = session.exec(select(ChatMessage)).one().id
        session.commit()
    ChatMessageService.delete_message(7, str(question_id))
    rows = await WorkflowFileRepository.attachment_messages("c1")
    assert [row.id for row in rows] == [f"{index:064x}" for index in range(1001)]

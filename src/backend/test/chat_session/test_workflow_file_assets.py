"""Parsed images use owned, durable manifests and expiring access links."""

import copy
import hashlib
import json
from contextlib import asynccontextmanager, contextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel import Session, create_engine, select
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.chat_session.domain.chat import ChatSessionService
from bisheng.chat_session.domain.models.workflow_file_manifest import WorkflowFileManifest
from bisheng.chat_session.domain.repositories import workflow_file_repository as repository_module
from bisheng.chat_session.domain.repositories.workflow_file_repository import WorkflowFileRepository
from bisheng.chat_session.domain.services.workflow_file_service import WorkflowFileService
from bisheng.core.context.tenant import bypass_tenant_filter
from bisheng.database.models.message import ChatMessage
from bisheng.database.models.session import MessageSession


@pytest.fixture(autouse=True)
def not_found_response(monkeypatch):
    monkeypatch.setattr(
        "bisheng.chat_session.domain.chat.NotFoundError",
        SimpleNamespace(
            http_exception=lambda: HTTPException(status_code=404),
        ),
    )


def _asset(identity="source", tenant_id=1, user_id=7, state="ready"):
    return {
        "file_id": hashlib.sha256(f"{identity}/figure.png".encode()).hexdigest(),
        "object_name": f"chat/{tenant_id}/{user_id}/workflow/{identity}/images/figure.png",
        "state": state,
        "bucket": "main",
    }


@pytest.fixture
def database(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'assets.db'}")
    MessageSession.__table__.create(engine)
    ChatMessage.__table__.create(engine)
    WorkflowFileManifest.__table__.create(engine)

    @contextmanager
    def connection():
        with Session(engine) as session:
            yield session

    monkeypatch.setattr(repository_module, "get_sync_db_session", connection)
    with bypass_tenant_filter(), connection() as session:
        session.add(MessageSession(chat_id="c1", user_id=7, tenant_id=1, flow_id="wf", flow_type=10, name="test"))
        session.add(
            ChatMessage(
                chat_id="c1",
                user_id=7,
                tenant_id=1,
                flow_id="wf",
                is_bot=False,
                category="question",
                type="over",
                files=json.dumps(
                    [
                        {
                            "file_id": "original",
                            "file_url": "http://storage/tmp/a.pdf?old",
                            "object_name": "chat/7/original.pdf",
                            "filename": "a.pdf",
                        }
                    ]
                ),
            )
        )
        session.commit()
    with bypass_tenant_filter():
        yield engine
    engine.dispose()


def test_repository_keeps_original_and_idempotently_updates_manifest(database):
    """AC-05, AC-08: a retry updates the existing image and never copies the source again."""
    promote = MagicMock()
    for state in ["pending", "ready", "pending", "ready"]:
        WorkflowFileRepository.save_assets(
            chat_id="c1",
            user_id=7,
            workflow_id="wf",
            source={"file_url": "http://storage/tmp/a.pdf?old"},
            assets=[_asset(state=state)],
            promote_source=promote,
        )
    with Session(database) as session:
        attachment = json.loads(session.exec(select(ChatMessage)).one().files)[0]
    assert attachment["object_name"] == "chat/7/original.pdf"
    assert attachment["file_id"] == "original"
    assert attachment["derived_assets"] == [_asset()]
    promote.assert_not_called()


@pytest.mark.parametrize("user_id,workflow_id", [(99, "wf"), (7, "different-workflow")])
def test_repository_refuses_a_different_owner_or_workflow(database, user_id, workflow_id):
    """AC-07: trusted runtime context still cannot attach assets to an unrelated conversation."""
    with pytest.raises(ValueError, match="unavailable"):
        WorkflowFileRepository.save_assets(
            chat_id="c1",
            user_id=user_id,
            workflow_id=workflow_id,
            source={"file_url": "/tmp/a.pdf"},
            assets=[_asset()],
        )


def test_deleted_conversation_refuses_completion(database):
    """AC-08: an upload that races deletion cannot be marked ready."""
    with Session(database) as session:
        owner = session.exec(select(MessageSession)).one()
        owner.is_delete = True
        session.add(owner)
        session.commit()
    with pytest.raises(ValueError, match="unavailable"):
        WorkflowFileRepository.save_assets(
            chat_id="c1",
            user_id=7,
            workflow_id="wf",
            source={"file_url": "/tmp/a.pdf"},
            assets=[_asset()],
        )


def test_context_registers_before_upload_and_uses_session_tenant(monkeypatch):
    """AC-05, AC-07: object attribution follows the message tenant, not the shared workflow tenant."""
    storage = SimpleNamespace(bucket="main", tmp_bucket="temp")
    monkeypatch.setattr(
        "bisheng.chat_session.domain.services.workflow_file_service.get_minio_storage_sync", lambda: storage
    )
    monkeypatch.setattr(WorkflowFileRepository, "conversation_tenant", lambda *args: 42)
    writes = []
    monkeypatch.setattr(WorkflowFileRepository, "save_assets", lambda **kw: writes.append(copy.deepcopy(kw["assets"])))
    kwargs = {
        "chat_id": "c1",
        "user_id": 7,
        "tenant_id": 1,
        "workflow_id": "wf",
        "run_id": "run",
        "node_id": "input",
        "source_url": "http://storage/temp/a.pdf",
        "file_name": "a.pdf",
    }
    context = WorkflowFileService.image_storage(**kwargs)
    context.before_upload(["figure.png"])
    context.after_upload()
    assert context.bucket_name == "main"
    assert context.object_dir.startswith("chat/42/7/")
    assert writes[0][0]["state"] == "pending" and writes[1][0]["state"] == "ready"
    assert context.url_builder("figure.png").endswith(f"/{writes[1][0]['file_id']}/content")
    assert WorkflowFileService.image_storage(**kwargs).object_dir != context.object_dir
    assert WorkflowFileService.image_storage(**{**kwargs, "run_id": "other"}).object_dir != context.object_dir


def test_debug_images_stay_in_temp_without_persistent_manifest(monkeypatch):
    """AC-06: debug bytes expire and do not create permanent conversation records."""
    storage = MagicMock(bucket="main", tmp_bucket="temp")
    storage.get_share_link_sync.return_value = "/temp/image?signature=expiring"
    monkeypatch.setattr(
        "bisheng.chat_session.domain.services.workflow_file_service.get_minio_storage_sync", lambda: storage
    )
    save = MagicMock()
    monkeypatch.setattr(WorkflowFileRepository, "save_assets", save)
    context = WorkflowFileService.image_storage(
        chat_id=None,
        user_id=7,
        tenant_id=1,
        workflow_id="wf",
        run_id="debug",
        node_id="input",
        source_url="/temp/a.pdf",
        file_name="a.pdf",
    )
    context.before_upload(["figure.png"])
    context.after_upload()
    assert context.bucket_name == "temp"
    assert "signature=expiring" in context.url_builder("figure.png")
    assert storage.get_share_link_sync.call_args.kwargs["bucket"] == "temp"
    save.assert_not_called()


@pytest.mark.parametrize(
    "tenant_id,user_id,state,allowed",
    [(1, 7, "ready", True), (2, 7, "ready", False), (1, 9, "ready", False), (1, 7, "pending", False)],
)
async def test_resolve_derived_image_checks_namespace_and_readiness(monkeypatch, tenant_id, user_id, state, allowed):
    """AC-05, AC-07: a fresh link only signs a ready image in the owner's namespace."""
    owner = SimpleNamespace(tenant_id=1, user_id=7)
    asset = _asset(tenant_id=tenant_id, user_id=user_id, state=state)
    message = SimpleNamespace(files=json.dumps([{"file_id": "original", "derived_assets": [asset]}]))
    monkeypatch.setattr(ChatSessionService, "_own_conversation_or_raise", AsyncMock(return_value=owner))
    monkeypatch.setattr(WorkflowFileRepository, "attachment_messages", AsyncMock(return_value=[message]))
    storage = MagicMock(get_share_link=AsyncMock(return_value="/main/fresh?signature=new"))
    monkeypatch.setattr("bisheng.chat_session.domain.chat.get_minio_storage", AsyncMock(return_value=storage))
    if allowed:
        assert "signature=new" in await ChatSessionService.resolve_attachment_url("c1", asset["file_id"], None)
        storage.get_share_link.assert_awaited_once_with(asset["object_name"])
    else:
        with pytest.raises(HTTPException) as exc:
            await ChatSessionService.resolve_attachment_url("c1", asset["file_id"], None)
        assert exc.value.status_code == 404
        storage.get_share_link.assert_not_awaited()


async def test_session_cleanup_removes_original_and_pending_images(monkeypatch):
    """AC-08: pending uploads are also reachable by cleanup, including a retry after failure."""
    image = _asset(state="pending")
    message = SimpleNamespace(files=json.dumps([{"object_name": "chat/7/original.pdf", "derived_assets": [image]}]))
    monkeypatch.setattr(WorkflowFileRepository, "attachment_messages", AsyncMock(return_value=[message]))
    monkeypatch.setattr(
        "bisheng.chat_session.domain.chat.MessageSessionDao.async_get_one",
        AsyncMock(
            return_value=SimpleNamespace(tenant_id=1, user_id=7),
        ),
    )
    storage = MagicMock(remove_object=AsyncMock(side_effect=[OSError("storage down"), None, None, None]))
    monkeypatch.setattr("bisheng.chat_session.domain.chat.get_minio_storage", AsyncMock(return_value=storage))
    await ChatSessionService._remove_attachments("c1")
    await ChatSessionService._remove_attachments("c1")
    removed = [call.kwargs["object_name"] for call in storage.remove_object.await_args_list]
    assert removed.count(image["object_name"]) == 2
    assert removed.count("chat/7/original.pdf") == 2


async def test_attachment_manifest_scan_includes_more_than_1000_messages(database, monkeypatch):
    """AC-08: keyset traversal cannot strand images in old conversation turns."""
    with Session(database) as session:
        session.add_all(
            [
                ChatMessage(
                    chat_id="c1",
                    user_id=7,
                    tenant_id=1,
                    flow_id="wf",
                    is_bot=False,
                    category="question",
                    type="over",
                    files="[]",
                )
                for _ in range(1001)
            ]
        )
        session.commit()
    engine = create_async_engine(str(database.url).replace("sqlite:", "sqlite+aiosqlite:"))

    @asynccontextmanager
    async def connection():
        async with AsyncSession(engine, expire_on_commit=False) as session:
            yield session

    monkeypatch.setattr(repository_module, "get_async_db_session", connection)
    try:
        messages = await WorkflowFileRepository.attachment_messages("c1")
        assert len(messages) == 1002
        assert [m.id for m in messages] == sorted({m.id for m in messages})
        assert "original.pdf" in messages[0].files
    finally:
        await engine.dispose()

"""AC-23/24/25: native HTTP/SQL registration and real Redis snapshot races.

Run only against a disposable Redis using TEST_UPLOAD_REDIS_URL. Parsing/object
storage/queue and permission transports are isolated; SQLite and Redis are real.
"""

import asyncio
import json
import os
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI
from redis.asyncio import Redis

from bisheng.api.v1.schemas import FileChunk
from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.knowledge import KnowledgeOperationPlanChangedError
from bisheng.knowledge.api.endpoints import knowledge_space, upload_preview
from bisheng.knowledge.application import upload_registration
from bisheng.knowledge.domain.repositories import upload_preview_repository as repo_module
from bisheng.knowledge.domain.schemas.knowledge_space_schema import FileCreateReq
from bisheng.knowledge.domain.schemas.upload_preview import UploadContextItem
from bisheng.knowledge.domain.services import upload_preview_service as service_module
from test.knowledge_unification import test_kn_upload as fixtures

store = fixtures.store
tenant = fixtures.tenant
business = fixtures.business
admission = fixtures.admission
processing = fixtures.processing
application = fixtures.application
files = fixtures.files
legacy = fixtures.legacy
upload = fixtures.upload


@pytest.fixture
async def receipts(monkeypatch):
    url = os.environ.get("TEST_UPLOAD_REDIS_URL")
    if not url:
        pytest.skip("TEST_UPLOAD_REDIS_URL must point to a disposable Redis")
    client = Redis.from_url(url)
    await client.ping()
    monkeypatch.setattr(
        repo_module, "get_redis_client", AsyncMock(return_value=SimpleNamespace(async_connection=client))
    )
    repo = repo_module.UploadPreviewRepository()
    prefix = f"e2e-upload-preview-{uuid4().hex}"
    repo.key = lambda uid: f"{prefix}:{uid}"
    owned = []
    original_create = repo.create

    async def create(value):
        receipt = await original_create(value)
        owned.append(repo.key(receipt["upload_id"]))
        return receipt

    repo.create = create
    try:
        yield SimpleNamespace(repo=repo, client=client, owned=owned)
    finally:
        # Delete only keys created by this fixture, including its frozen snapshots.
        for key in owned:
            raw = await client.get(key)
            if raw:
                frozen = json.loads(raw).get("frozen_cache_key")
                if frozen:
                    await client.delete(frozen)
            await client.delete(key)
        await client.aclose()


@pytest.fixture
async def prepared(upload, receipts, monkeypatch):
    service = service_module.UploadPreviewService(upload.service, receipts.repo)
    monkeypatch.setattr(service_module, "get_async_db_session", upload.context.sessions)
    monkeypatch.setattr(upload_registration, "UploadPreviewService", lambda svc: service)
    monkeypatch.setattr(upload_preview, "UploadPreviewService", lambda svc: service)
    receipt = await receipts.repo.create(
        {
            "space_id": 40,
            "parent_id": None,
            "tenant_id": 101,
            "actor_user_id": 7,
            "file_path": "opaque-document",
            "file_name": "test.md",
            "state": "OPEN",
            "preview": None,
        }
    )
    return SimpleNamespace(service=service, receipt=receipt, uid=receipt["upload_id"])


async def test_http_preview_edit_freeze_and_committed_replay_use_one_native_registration(
    upload, receipts, prepared, monkeypatch
):
    """AC-23/24: an upload-only actor previews, edits and registers the same rule."""
    parser = AsyncMock(
        return_value=("local", "/preview/test.md", [FileChunk(text="original", metadata={"chunk_index": 0})], {})
    )
    monkeypatch.setattr(service_module.KnowledgeService, "parse_staged_file", parser)
    app = FastAPI()
    app.include_router(upload_preview.router, prefix="/api/v1/knowledge/space")
    app.include_router(knowledge_space.router, prefix="/api/v1")
    app.dependency_overrides[upload_preview.get_knowledge_space_service] = lambda: upload.service
    app.dependency_overrides[UserPayload.get_login_user] = lambda: upload.context.user
    base = f"/api/v1/knowledge/space/40/uploads/{prepared.uid}"
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://local") as client:
        started = await client.post(f"{base}/previews", json={"overrides": {"document": {"chunk_size": 321}}})
        assert started.status_code == 200 and started.json()["status_code"] == 200
        pid = started.json()["data"]["preview_id"]
        value = (await client.get(f"{base}/previews/{pid}")).json()["data"]
        assert value["status"] == "completed" and value["revision"] == 0
        edited = await client.put(
            f"{base}/previews/{pid}/chunks/0", json={"text": "confirmed edit", "expected_revision": 0}
        )
        assert edited.json()["data"]["revision"] == 1
        body = {
            "file_path": ["opaque-document"],
            "upload_context": {
                "mode": "previewed",
                "items": [
                    {
                        "upload_id": prepared.uid,
                        "file_path": "opaque-document",
                        "overrides": {"document": {"chunk_size": 321}},
                        "preview_id": pid,
                        "expected_revision": 1,
                    }
                ],
            },
        }
        accepted = await client.post("/api/v1/knowledge/space/40/files", json=body)
        assert accepted.status_code == 200 and accepted.json()["status_code"] == 200
        replay = await client.post("/api/v1/knowledge/space/40/files", json=body)
        assert replay.json()["data"][0]["id"] == accepted.json()["data"][0]["id"]
        status = (await client.get(base)).json()["data"]
        assert status["state"] == "COMMITTED" and len(status["rows"]) == 1
    upload.publish.assert_called_once()
    assert all(call.args[-1] == "upload_file" for call in upload.service._require_action.await_args_list)
    assert parser.call_args.args[1].chunk_size == 321
    key = upload.publish.call_args.kwargs["preview_cache_key"]
    assert key.startswith("space_upload_frozen:")
    assert json.loads(await receipts.client.hget(key, "0"))["text"] == "confirmed edit"
    assert await receipts.client.ttl(key) > 6 * 86400
    assert json.loads(accepted.json()["data"][0]["split_rule"])["chunk_size"] == 321


async def test_real_watch_rejects_one_of_two_edits_with_same_revision(receipts, prepared):
    _, _, pid = await prepared.service.start(40, prepared.uid, {})

    def completed(value):
        value["preview"].update(
            status="completed",
            data={
                "chunks": [
                    {"text": "old", "metadata": {"chunk_index": 0}},
                    {"text": "second", "metadata": {"chunk_index": 1}},
                ]
            },
        )

    await receipts.repo.mutate(prepared.uid, completed)
    results = await asyncio.gather(
        *[
            prepared.service.edit(40, prepared.uid, pid, 0, 0, SimpleNamespace(text=text, bbox=""))
            for text in ["first edit", "second edit"]
        ],
        return_exceptions=True,
    )
    assert sum(isinstance(result, KnowledgeOperationPlanChangedError) for result in results) == 1
    stored = await receipts.repo.get(prepared.uid)
    assert stored["preview"]["revision"] == 1


async def test_stale_receipt_scope_and_request_path_never_enter_registration(upload, prepared):
    from bisheng.common.errcode.knowledge import KnowledgeProcessingJobNotFoundError

    request = FileCreateReq(
        file_path=["forged"],
        upload_context={
            "mode": "direct",
            "items": [
                {
                    "upload_id": prepared.uid,
                    "file_path": "forged",
                    "overrides": {},
                }
            ],
        },
    )
    with pytest.raises(KnowledgeProcessingJobNotFoundError):
        await upload_registration.register_owned_upload(upload.service, 40, request)
    upload.publish.assert_not_called()


async def test_lost_dispatch_ack_keeps_committing_and_prevents_second_dispatch(upload, receipts, prepared):
    from bisheng.common.errcode.knowledge import KnowledgeOperationPlanConflictError

    upload.publish.side_effect = RuntimeError("lost acknowledgement")
    request = FileCreateReq(
        file_path=["opaque-document"],
        upload_context={
            "mode": "direct",
            "items": [
                {
                    "upload_id": prepared.uid,
                    "file_path": "opaque-document",
                    "overrides": {},
                }
            ],
        },
    )
    with pytest.raises(RuntimeError, match="lost acknowledgement"):
        await upload_registration.register_owned_upload(upload.service, 40, request)
    assert (await receipts.repo.get(prepared.uid))["state"] == "COMMITTING"
    with pytest.raises(KnowledgeOperationPlanConflictError):
        await upload_registration.register_owned_upload(upload.service, 40, request)
    upload.publish.assert_called_once()


async def test_freeze_cannot_race_past_a_changed_revision(receipts, prepared):
    _, _, pid = await prepared.service.start(40, prepared.uid, {})

    def completed(value):
        value["preview"].update(status="completed", data={"chunks": [{"text": "old", "metadata": {"chunk_index": 0}}]})

    await receipts.repo.mutate(prepared.uid, completed)
    await prepared.service.edit(40, prepared.uid, pid, 0, 0, SimpleNamespace(text="new", bbox=""))
    item = UploadContextItem(
        upload_id=prepared.uid, file_path="opaque-document", overrides={}, preview_id=pid, expected_revision=0
    )
    with pytest.raises(KnowledgeOperationPlanChangedError):
        await prepared.service.freeze(prepared.receipt, item, "previewed", "request")
    assert (await receipts.repo.get(prepared.uid))["state"] == "OPEN"


async def test_stage_http_binds_actual_uploader_and_closes_file(upload, receipts, prepared, monkeypatch):
    from bisheng.role.domain.services.quota_service import QuotaService

    monkeypatch.setattr(QuotaService, "check_quota", AsyncMock())
    monkeypatch.setattr(service_module, "validate_knowledge_upload_file_size", lambda name, size: None)
    monkeypatch.setattr(
        service_module.KnowledgeService, "save_upload_file_original_name", AsyncMock(return_value="unique.md")
    )
    saved = AsyncMock(return_value="tmp/unique.md")
    monkeypatch.setattr(service_module, "save_uploaded_file", saved)
    app = FastAPI()
    app.include_router(upload_preview.router, prefix="/api/v1/knowledge/space")
    app.dependency_overrides[upload_preview.get_knowledge_space_service] = lambda: upload.service
    app.dependency_overrides[UserPayload.get_login_user] = lambda: upload.context.user
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://local") as client:
        response = await client.post(
            "/api/v1/knowledge/space/40/uploads", files={"file": ("input.md", b"test", "text/markdown")}
        )
    assert response.status_code == 200 and response.json()["status_code"] == 200
    receipt = await receipts.repo.get(response.json()["data"]["upload_id"])
    assert (receipt["actor_user_id"], receipt["tenant_id"], receipt["space_id"], receipt["parent_id"]) == (
        7,
        101,
        40,
        None,
    )
    assert receipt["file_path"] == "tmp/unique.md" and receipt["state"] == "OPEN"
    assert saved.call_args.args[0].file.closed
    upload.publish.assert_not_called()


async def test_per_file_rules_and_direct_cache_isolation_reach_native_batch(
    upload, receipts, prepared, monkeypatch, tmp_path
):
    globals_ = upload.legacy.cls.process_one_file.__func__.__globals__
    original_download = globals_["file_download"]
    source = tmp_path / "second.csv"
    source.write_text("header\ndifferent content\n", encoding="utf-8")
    monkeypatch.setitem(
        globals_,
        "file_download",
        lambda path: (str(source), "sheet.csv") if path == "opaque-table" else original_download(path),
    )
    table = await receipts.repo.create({**prepared.receipt, "file_path": "opaque-table", "file_name": "sheet.csv"})
    request = FileCreateReq(
        file_path=["opaque-document", "opaque-table"],
        upload_context={
            "mode": "direct",
            "items": [
                {
                    "upload_id": prepared.uid,
                    "file_path": "opaque-document",
                    "overrides": {"document": {"chunk_size": 321}},
                },
                {
                    "upload_id": table["upload_id"],
                    "file_path": "opaque-table",
                    "overrides": {"table": {"slice_length": 22, "append_header": 0}},
                },
            ],
        },
    )
    rows = await upload_registration.register_owned_upload(upload.service, 40, request)
    rules = {
        json.loads(row.split_rule)["_effective_processing"]["file_kind"]: json.loads(row.split_rule) for row in rows
    }
    assert rules["document"]["chunk_size"] == 321
    assert rules["table"]["excel_rule"]["slice_length"] == 22
    assert rules["table"]["excel_rule"]["append_header"] == 0
    assert all(call.kwargs["preview_cache_key"] == "" for call in upload.publish.call_args_list)
    for receipt in (prepared.receipt, table):
        state = await receipts.repo.get(receipt["upload_id"])
        assert state["state"] == "COMMITTED" and len(state["rows"]) == 1


async def test_space_default_change_after_freeze_cannot_change_confirmed_rule(upload, receipts, prepared, monkeypatch):
    from bisheng.knowledge.domain.models.knowledge import Knowledge
    from bisheng.knowledge.domain.schemas.processing_settings import ProcessingOverrides

    overrides = ProcessingOverrides(document={"chunk_size": 321})
    confirmed = await prepared.service.rule(prepared.receipt, overrides)
    original_add = upload.service.add_file

    async def changing_settings(*args, **kwargs):
        async with upload.context.sessions() as session:
            root = await session.get(Knowledge, 40)
            defaults = json.loads(json.dumps(root.processing_defaults))
            defaults["document"]["chunk_overlap"] = 99
            root.processing_defaults = defaults
            root.processing_config_version += 1
            await session.commit()
        return await original_add(*args, **kwargs)

    monkeypatch.setattr(upload.service, "add_file", changing_settings)
    request = FileCreateReq(
        file_path=["opaque-document"],
        upload_context={
            "mode": "direct",
            "items": [
                {
                    "upload_id": prepared.uid,
                    "file_path": "opaque-document",
                    "overrides": overrides.model_dump(mode="json"),
                }
            ],
        },
    )
    rows = await upload_registration.register_owned_upload(upload.service, 40, request)
    actual = json.loads(rows[0].split_rule)
    assert actual["chunk_overlap"] == confirmed.chunk_overlap != 99
    assert actual["chunk_size"] == 321


async def test_legacy_preview_still_requires_original_write_permission(upload, monkeypatch):
    from bisheng.api.v1.schemas import KnowledgeFileOne, KnowledgeFileProcess
    from bisheng.common.errcode.permission import PermissionDeniedError

    cls = upload.legacy.cls
    namespace = cls.get_preview_file_chunk.__func__.__globals__
    monkeypatch.setattr(
        namespace["KnowledgeDao"], "aquery_by_id", AsyncMock(return_value=SimpleNamespace(id=40, user_id=7))
    )
    gate = AsyncMock(side_effect=PermissionDeniedError())
    monkeypatch.setattr(cls.permission_service, "ensure_knowledge_write_async", gate)
    parser = AsyncMock(return_value=("local", "/preview", [], {}))
    monkeypatch.setattr(cls, "parse_staged_file", parser)
    request = KnowledgeFileProcess(knowledge_id=40, file_list=[KnowledgeFileOne(file_path="opaque-document")])
    with pytest.raises(PermissionDeniedError):
        await cls.get_preview_file_chunk(None, upload.context.user, request)
    parser.assert_not_called()
    gate.side_effect = None
    await cls.get_preview_file_chunk(None, upload.context.user, request)
    parser.assert_awaited_once_with(upload.context.user, request)

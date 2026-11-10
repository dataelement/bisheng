"""Legacy overwrite is a live SPACE file action, not a lossy ordinary retry."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bisheng.common.errcode.knowledge import KnowledgeOperationPlanConflictError, KnowledgeProcessingConflictError
from bisheng.common.errcode.knowledge_space import SpacePermissionDeniedError
from bisheng.core.storage.minio import minio_manager
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile
from test.knowledge_unification import test_kn_upload as native

store, tenant, business, admission = native.store, native.tenant, native.business, native.admission
processing, application, files, legacy, upload = (
    native.processing,
    native.application,
    native.files,
    native.legacy,
    native.upload,
)


@pytest.fixture
async def retry(upload, monkeypatch):
    context = upload.context
    # Root conftest uses a placeholder parent. Bind the actual original helper,
    # as the upload fixture already does for the real preparation implementation.
    upload.service.process_retry_files = upload.legacy.cls.process_retry_files
    upload.service._require_read_permission = AsyncMock()
    upload.service._require_resource_action = AsyncMock()
    storage = SimpleNamespace(tmp_bucket="temporary", bucket="saved", copy_object=AsyncMock())
    monkeypatch.setattr(minio_manager, "get_minio_storage", AsyncMock(return_value=storage))

    options = {}

    def build():
        from bisheng.knowledge.application import legacy_retry

        monkeypatch.setattr(
            legacy_retry,
            "batch_check_business_actions",
            AsyncMock(
                side_effect=lambda identity, **kwargs: {str(i): frozenset({"rename"}) for i in kwargs["resource_ids"]}
            ),
        )
        monkeypatch.setattr(legacy_retry, "require_business_action", AsyncMock())
        monkeypatch.setattr(legacy_retry, "get_minio_storage", AsyncMock(return_value=storage))
        monkeypatch.setattr(legacy_retry, "KnowledgeUtils", upload.legacy.cls)
        return legacy_retry.LegacyRetryApplication(session_factory=context.sessions, commands=options.get("commands"))

    upload.service.legacy_retry_factory = build
    async with context.sessions() as session:
        row = await session.get(KnowledgeFile, 81)
        row.file_level_path = ""
        row.similar_status, row.simhash = 1, "old-content"
        await session.commit()
        raw = row.model_dump()
    raw.update(
        object_name="tmp/81.txt", status=3, remark=json.dumps({"new_name": "replacement.txt"}), file_level_path=""
    )
    return SimpleNamespace(upload=upload, storage=storage, raw=raw, options=options)


async def run(context, **changes):
    return await context.upload.service.retry_space_files(40, {"file_objs": [{**context.raw, **changes}]})


async def test_file_rename_authority_can_overwrite_without_root_visible(retry):
    retry.upload.service._require_read_permission.side_effect = SpacePermissionDeniedError()
    await run(retry)
    async with retry.upload.context.sessions() as session:
        row = await session.get(KnowledgeFile, 81)
        assert (row.file_name, row.status, row.object_name) == ("replacement.txt", 5, "original/81.txt")
        assert row.split_rule == retry.raw["split_rule"] and row.simhash is None and row.similar_status == 0
    retry.upload.legacy.publish.assert_called_once()
    retry.storage.copy_object.assert_awaited_once()


async def test_overwrite_cannot_change_the_actual_parent_path(retry):
    with pytest.raises(KnowledgeOperationPlanConflictError):
        await run(retry, file_level_path="/999")
    retry.storage.copy_object.assert_not_awaited()
    retry.upload.legacy.publish.assert_not_called()
    async with retry.upload.context.sessions() as session:
        assert (await session.get(KnowledgeFile, 81)).file_level_path == ""


async def test_overwrite_refuses_processing_before_copy_or_dispatch(retry):
    async with retry.upload.context.sessions() as session:
        row = await session.get(KnowledgeFile, 81)
        row.status = 1
        await session.commit()
    with pytest.raises(KnowledgeProcessingConflictError):
        await run(retry)
    retry.storage.copy_object.assert_not_awaited()
    retry.upload.legacy.publish.assert_not_called()


async def snapshot(context):
    from sqlmodel import select

    from bisheng.knowledge.domain.models.knowledge_document import KnowledgeDocument
    from bisheng.knowledge.domain.models.knowledge_document_version import KnowledgeDocumentVersion

    async with context.upload.context.sessions() as session:
        return {
            model.__tablename__: [
                row.model_dump(mode="json") for row in (await session.exec(select(model).order_by(model.id))).all()
            ]
            for model in (KnowledgeFile, KnowledgeDocument, KnowledgeDocumentVersion)
        }


def second(context):
    return {**context.raw, "id": 82, "object_name": "tmp/82.txt", "remark": json.dumps({"new_name": "second.txt"})}


async def batch(context, items, **extra):
    return await context.upload.service.retry_space_files(40, {"file_objs": items, **extra})


async def test_complete_batch_preserves_versions_and_original_retry_worker_arguments(retry):
    before = await snapshot(retry)
    await batch(retry, [retry.raw, second(retry)])
    after = await snapshot(retry)
    assert before["knowledge_document"] == after["knowledge_document"]
    assert before["knowledge_document_version"] == after["knowledge_document_version"]
    assert [row["status"] for row in after["knowledgefile"]] == [5, 5]
    assert retry.storage.copy_object.await_count == 2
    actual = [call.args for call in retry.upload.legacy.publish.call_args_list]
    assert [call[0] for call in actual] == [81, 82]
    stored = {row["id"]: row for row in before["knowledgefile"]}
    for call in actual:
        payload = json.loads(stored[call[0]]["split_rule"]) if stored[call[0]]["split_rule"] else {}
        expected = retry.upload.legacy.cls.preview_cache_key_for_split_rule(40, "", payload)
        assert call[1:] == (expected, None)
    retry.upload.publish.assert_not_called()  # ordinary upload scheduler is not the retry entry


async def test_later_invalid_item_has_no_earlier_copy_update_or_dispatch(retry):
    before = await snapshot(retry)
    with pytest.raises(KnowledgeOperationPlanConflictError):
        await batch(retry, [retry.raw, {**second(retry), "file_level_path": "/999"}])
    assert await snapshot(retry) == before
    retry.storage.copy_object.assert_not_awaited()
    retry.upload.legacy.publish.assert_not_called()


async def test_native_late_sql_failure_rolls_back_the_whole_status_batch(retry):
    import sqlalchemy as sa

    before = await snapshot(retry)
    with retry.upload.context.sync.begin() as connection:
        connection.exec_driver_sql(
            "CREATE TRIGGER reject_retry BEFORE UPDATE ON knowledgefile WHEN NEW.id = 82 BEGIN SELECT RAISE(ABORT, 'late retry SQL failure'); END"
        )
    with pytest.raises(sa.exc.IntegrityError, match="late retry SQL failure"):
        await batch(retry, [retry.raw, second(retry)])
    assert await snapshot(retry) == before
    retry.upload.legacy.publish.assert_not_called()


async def test_unknown_broker_ack_is_not_success_and_keeps_real_waiting_rows(retry):
    retry.upload.legacy.publish.side_effect = [None, OSError("broker acknowledgement unknown")]
    with pytest.raises(KnowledgeProcessingConflictError) as caught:
        await batch(retry, [retry.raw, second(retry)])
    assert caught.value.kwargs["reason"] == "legacy_retry_pending_dispatch"
    after = await snapshot(retry)
    assert [row["status"] for row in after["knowledgefile"]] == [5, 5]
    assert retry.upload.legacy.publish.call_count == 2


@pytest.mark.parametrize(
    "object_name", ["original/82.txt", "tmp/82.txt", "tmp/81/../../other.txt", "https://untrusted.invalid/file"]
)
async def test_body_cannot_select_another_original_or_temporary_object(retry, object_name):
    with pytest.raises(KnowledgeOperationPlanConflictError):
        await run(retry, object_name=object_name)
    retry.storage.copy_object.assert_not_awaited()
    retry.upload.legacy.publish.assert_not_called()


async def test_ordinary_failed_retry_keeps_the_exact_stored_json_without_copy(retry):
    async with retry.upload.context.sessions() as session:
        row = await session.get(KnowledgeFile, 81)
        row.status = 3
        original = row.object_name
        await session.commit()
    await batch(retry, [{"id": 81}])
    async with retry.upload.context.sessions() as session:
        row = await session.get(KnowledgeFile, 81)
        assert row.status == 5 and row.split_rule == retry.raw["split_rule"] and row.object_name == original
    retry.storage.copy_object.assert_not_awaited()
    retry.upload.legacy.publish.assert_called_once()


async def test_actual_cross_folder_duplicate_keeps_original_doc_parent_and_old_rule_provenance(retry):
    from bisheng.knowledge.domain.models.knowledge import Knowledge
    from bisheng.knowledge.domain.models.knowledge_document import KnowledgeDocument

    async with retry.upload.context.sessions() as session:
        session.add_all(
            [
                KnowledgeFile(
                    id=90, tenant_id=101, knowledge_id=40, file_type=0, file_name="New", file_level_path="", level=0
                ),
                KnowledgeFile(
                    id=92, tenant_id=101, knowledge_id=40, file_type=0, file_name="Old", file_level_path="", level=0
                ),
            ]
        )
        for ident in (81, 82):
            file = await session.get(KnowledgeFile, ident)
            file.file_level_path, file.level = "/92", 1
        file = await session.get(KnowledgeFile, 81)
        file.md5 = "digest"
        doc = await session.get(KnowledgeDocument, 80)
        doc.file_level_path, doc.level = "/92", 1
        await session.commit()
    before = await snapshot(retry)
    [duplicate] = await retry.upload.service.add_file(40, ["opaque-document"], parent_id=90)
    assert duplicate.status == 3 and duplicate.id == 81
    assert duplicate.file_level_path == "/92" and duplicate.old_file_level_path == "/Old"
    raw = duplicate.model_dump()
    assert json.loads(raw["split_rule"])["_effective_processing"]["space_config_version"] == 3
    async with retry.upload.context.sessions() as session:
        root = await session.get(Knowledge, 40)
        root.processing_config_version = 4
        root.processing_defaults = {
            **root.processing_defaults,
            "document": {**root.processing_defaults["document"], "chunk_size": 900},
        }
        await session.commit()
    await batch(retry, [raw])
    after = await snapshot(retry)
    assert before["knowledge_document"] == after["knowledge_document"]
    assert before["knowledge_document_version"] == after["knowledge_document_version"]
    async with retry.upload.context.sessions() as session:
        file = await session.get(KnowledgeFile, 81)
        assert file.file_level_path == "/92" and file.split_rule == raw["split_rule"]
        assert json.loads(file.split_rule)["chunk_size"] == 800
    retry.upload.legacy.publish.assert_called_once()


async def test_forged_effective_marker_does_not_override_the_original_legacy_normalization(retry):
    from bisheng.knowledge.application.file_processing_adapter import (
        resolve_file_processing_snapshot,
        system_processing_defaults,
    )

    payload = json.loads(retry.raw["split_rule"])
    marker = resolve_file_processing_snapshot(
        file_name="replacement.txt",
        file_source="upload",
        system_defaults=system_processing_defaults(40),
        space_defaults=None,
        space_config_version=3,
        legacy_split_rule=payload,
    ).model_dump(mode="json")
    marker["effective_rule"]["chunk_size"] = 9999
    payload["_effective_processing"] = marker
    with pytest.raises(KnowledgeOperationPlanConflictError):
        await run(retry, split_rule=json.dumps(payload))
    retry.storage.copy_object.assert_not_awaited()
    retry.upload.legacy.publish.assert_not_called()


async def test_original_source_rule_change_requires_the_existing_confirmation(retry):
    from bisheng.common.errcode.knowledge import KnowledgeOperationConfirmationRequiredError

    payload = json.loads(retry.raw["split_rule"])
    payload["chunk_size"] = 222
    with pytest.raises(KnowledgeOperationConfirmationRequiredError):
        await batch(retry, [{"id": 81, "split_rule": json.dumps(payload)}])
    retry.storage.copy_object.assert_not_awaited()
    retry.upload.legacy.publish.assert_not_called()


async def test_advanced_uses_actual_existing_plan_and_replays_same_job(retry, application):
    from sqlmodel import select

    from bisheng.knowledge.application.knowledge_processing_commands import KnowledgeProcessingCommands
    from bisheng.knowledge.domain.models.knowledge_processing_item import KnowledgeProcessingItem
    from bisheng.knowledge.domain.models.knowledge_processing_job import KnowledgeProcessingJob
    from bisheng.knowledge.domain.schemas.processing_job import JobAccepted, ProcessingPrecheckRequest
    from bisheng.knowledge.domain.services.processing_job_service import ProcessingJobService

    commands = KnowledgeProcessingCommands(
        session_factory=retry.upload.context.sessions,
        service=ProcessingJobService(owner=application.owner, available_kinds={"file_resplit", "file_reprocess"}),
    )
    retry.options["commands"] = commands
    plan = await commands.aprecheck(
        40,
        ProcessingPrecheckRequest(
            kind="file_resplit",
            targets=[{"file_id": 81, "version_id": 181}],
            parameters={"overrides": {"document": {"chunk_size": 222}}},
        ),
        identity=retry.upload.context.user,
    )
    payload = json.loads(retry.raw["split_rule"])
    payload["chunk_size"] = 222
    confirmation = {
        "confirmation_id": plan.confirmation_id,
        "plan_digest": plan.plan_digest,
        "idempotency_key": "actual-advanced-retry",
    }
    accepted = await batch(retry, [{"id": 81, "split_rule": json.dumps(payload)}], **confirmation)
    assert isinstance(accepted, JobAccepted) and accepted.state == "accepted"
    replay = await batch(retry, [{"id": 81, "split_rule": json.dumps(payload)}], **confirmation)
    assert replay.job_id == accepted.job_id and replay.reused
    async with retry.upload.context.sessions() as session:
        assert len((await session.exec(select(KnowledgeProcessingJob))).all()) == 1
        [item] = (await session.exec(select(KnowledgeProcessingItem))).all()
        assert (item.file_id, item.document_id, item.version_id) == (81, 80, 181)
        assert item.processing_snapshot["effective_processing"]["effective_rule"]["chunk_size"] == 222
        # The original confirmed advanced kernel owns this intentional change.
        assert json.loads((await session.get(KnowledgeFile, 81)).split_rule)["chunk_size"] == 222
    retry.storage.copy_object.assert_not_awaited()
    retry.upload.legacy.publish.assert_not_called()


async def test_old_knowledge_retry_http_is_composed_without_a_library_edit_gate(retry, monkeypatch):
    from unittest.mock import Mock

    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient

    from bisheng.common.dependencies.user_deps import UserPayload
    from bisheng.knowledge.api.endpoints import knowledge as api
    from bisheng.knowledge.application.legacy_retry import get_legacy_retry_application

    monkeypatch.setattr(api, "KnowledgeService", retry.upload.legacy.cls)
    retry.upload.legacy.cls.upload_knowledge_file_hook = Mock()
    server = FastAPI()
    server.include_router(api.router, prefix="/api/v1")
    server.dependency_overrides[UserPayload.get_login_user] = lambda: retry.upload.context.user
    server.dependency_overrides[get_legacy_retry_application] = retry.upload.service.legacy_retry_factory
    async with AsyncClient(transport=ASGITransport(app=server), base_url="http://native") as client:
        result = await client.post("/api/v1/knowledge/retry", json={"file_objs": [retry.raw]})
    assert result.status_code == 200 and result.json()["status_code"] == 200
    retry.upload.legacy.auth.ensure_knowledge_write_async.assert_not_awaited()
    retry.upload.legacy.cls.upload_knowledge_file_hook.assert_called_once()
    retry.upload.legacy.publish.assert_called_once()


@pytest.mark.parametrize("change", ["rebuilding", "transition", "wrong_root", "missing_doc", "alias_version"])
async def test_actual_current_scope_failures_precede_all_external_copy(retry, change):
    from bisheng.common.errcode.knowledge_space import SpaceFileNotFoundError
    from bisheng.knowledge.domain.models.knowledge import Knowledge
    from bisheng.knowledge.domain.models.knowledge_document import KnowledgeDocument
    from bisheng.knowledge.domain.models.knowledge_document_version import KnowledgeDocumentVersion

    async with retry.upload.context.sessions() as session:
        if change == "rebuilding":
            (await session.get(Knowledge, 40)).state = 3
        elif change == "transition":
            (await session.get(Knowledge, 40)).model_transition = {"operation_id": "current-rebuild"}
        elif change == "wrong_root":
            (await session.get(KnowledgeFile, 81)).knowledge_id = 999
        elif change == "missing_doc":
            await session.delete(await session.get(KnowledgeDocument, 80))
        else:
            session.add(KnowledgeDocumentVersion(id=199, knowledge_file_id=81, document_id=80, version_no=3))
        await session.commit()
    with pytest.raises((KnowledgeOperationPlanConflictError, KnowledgeProcessingConflictError, SpaceFileNotFoundError)):
        await run(retry)
    retry.storage.copy_object.assert_not_awaited()
    retry.upload.legacy.publish.assert_not_called()


async def test_permission_revocation_after_copy_still_precedes_all_sql_updates(retry):
    before = await snapshot(retry)
    app = retry.upload.service.legacy_retry_factory()
    from bisheng.knowledge.application import legacy_retry

    calls = 0

    async def authorize(_identity, **kwargs):
        nonlocal calls
        calls += 1
        return {str(ident): frozenset({"rename"}) if calls == 1 else frozenset() for ident in kwargs["resource_ids"]}

    legacy_retry.batch_check_business_actions.side_effect = authorize
    with pytest.raises(SpacePermissionDeniedError):
        await app.aretry(
            request=None, identity=retry.upload.context.user, space_id=40, req_data={"file_objs": [retry.raw]}
        )
    assert await snapshot(retry) == before
    retry.storage.copy_object.assert_awaited_once()
    retry.upload.legacy.publish.assert_not_called()


async def test_actual_index_revision_change_after_copy_rejects_stale_retry(retry):
    from bisheng.knowledge.domain.models.knowledge import Knowledge

    before = await snapshot(retry)

    async def change(**_kwargs):
        async with retry.upload.context.sessions() as session:
            root = await session.get(Knowledge, 40)
            root.model_config_revision += 1
            await session.commit()

    retry.storage.copy_object.side_effect = change
    with pytest.raises(KnowledgeOperationPlanConflictError):
        await run(retry)
    assert await snapshot(retry) == before
    retry.upload.legacy.publish.assert_not_called()


async def test_actual_space_http_uses_the_same_retry_factory(retry):
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient

    from bisheng.knowledge.api.dependencies import get_knowledge_space_service
    from bisheng.knowledge.api.endpoints.knowledge_space import router

    server = FastAPI()
    server.include_router(router, prefix="/api/v1")
    server.dependency_overrides[get_knowledge_space_service] = lambda: retry.upload.service
    retry.upload.service._require_read_permission.side_effect = SpacePermissionDeniedError()
    async with AsyncClient(transport=ASGITransport(app=server), base_url="http://native") as client:
        response = await client.post("/api/v1/knowledge/space/40/files/retry", json={"file_objs": [retry.raw]})
    assert response.status_code == 200 and response.json()["status_code"] == 200
    retry.upload.legacy.publish.assert_called_once()


@pytest.mark.parametrize("kind", [0, 1])
async def test_original_normal_and_qa_retry_keep_the_existing_writer(retry, monkeypatch, kind):
    from unittest.mock import Mock

    from bisheng.knowledge.domain.models.knowledge import Knowledge

    async with retry.upload.context.sessions() as session:
        (await session.get(Knowledge, 40)).type = kind
        await session.commit()
    original = retry.upload.legacy.cls
    monkeypatch.setattr(original, "upload_knowledge_file_hook", Mock())
    application = SimpleNamespace(aretry=AsyncMock(side_effect=AssertionError("ordinary branch changed")))
    result = await original.retry_files(
        None, retry.upload.context.user, {"file_objs": [retry.raw]}, retry_application=application
    )
    assert result == []
    application.aretry.assert_not_awaited()
    retry.upload.legacy.auth.ensure_knowledge_write_async.assert_awaited_once()
    original.upload_knowledge_file_hook.assert_called_once()
    retry.upload.legacy.publish.assert_called_once()


async def test_advanced_plan_must_cover_exactly_the_complete_selected_batch(retry, application):
    from sqlmodel import select

    from bisheng.knowledge.application.knowledge_processing_commands import KnowledgeProcessingCommands
    from bisheng.knowledge.domain.models.knowledge_processing_job import KnowledgeProcessingJob
    from bisheng.knowledge.domain.schemas.processing_job import ProcessingPrecheckRequest
    from bisheng.knowledge.domain.services.processing_job_service import ProcessingJobService

    commands = KnowledgeProcessingCommands(
        session_factory=retry.upload.context.sessions,
        service=ProcessingJobService(owner=application.owner, available_kinds={"file_resplit"}),
    )
    retry.options["commands"] = commands
    plan = await commands.aprecheck(
        40,
        ProcessingPrecheckRequest(
            kind="file_resplit",
            targets=[{"file_id": 81, "version_id": 181}],
            parameters={"overrides": {"document": {"chunk_size": 222}}},
        ),
        identity=retry.upload.context.user,
    )
    changed = json.dumps({**json.loads(retry.raw["split_rule"]), "chunk_size": 222})
    before = await snapshot(retry)
    with pytest.raises(KnowledgeOperationPlanConflictError):
        await batch(
            retry,
            [{"id": 81, "split_rule": changed}, {"id": 82, "split_rule": changed}],
            confirmation_id=plan.confirmation_id,
            plan_digest=plan.plan_digest,
            idempotency_key="wrong-scope",
        )
    assert await snapshot(retry) == before
    async with retry.upload.context.sessions() as session:
        assert not (await session.exec(select(KnowledgeProcessingJob))).all()
    retry.storage.copy_object.assert_not_awaited()
    retry.upload.legacy.publish.assert_not_called()

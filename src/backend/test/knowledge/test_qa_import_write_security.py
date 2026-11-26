"""QA import source capabilities and exact record-set authorization regressions."""

import inspect
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pandas as pd
import pytest
from fastapi import BackgroundTasks, HTTPException

from bisheng.common.errcode.http_error import NotFoundError, UnAuthorizedError
from bisheng.knowledge.api.endpoints import knowledge as endpoint
from bisheng.knowledge.domain.models.knowledge_file import QAKnowledgeUpsert


def _route(path):
    return next(route.endpoint for route in endpoint.router.routes if route.path == path)


async def _invoke(call, **kwargs):
    result = call(**kwargs)
    return await result if inspect.isawaitable(result) else result


@pytest.fixture
def actor(tenant_context):
    tenant_context(3)
    return SimpleNamespace(user_id=7, user_name="writer", tenant_id=3)


@pytest.mark.parametrize("path", ["http://127.0.0.1/private.xlsx", "/tmp/private.xlsx", "file:///tmp/private.xlsx"])
async def test_raw_preview_path_rejected_before_pandas(monkeypatch, actor, path):
    read = Mock(return_value=pd.DataFrame({"Question": ["q"], "Answer": ["a"]}))
    monkeypatch.setattr(endpoint.pd, "read_excel", read)
    monkeypatch.setattr(endpoint.KnowledgeService, "ajudge_qa_knowledge_write", AsyncMock())
    with pytest.raises((HTTPException, NotFoundError, UnAuthorizedError, ValueError)):
        await _invoke(
            _route("/knowledge/qa/preview/{qa_knowledge_id}"),
            qa_knowledge_id=11,
            file_url=path,
            size=0,
            offset=0,
            login_user=actor,
        )
    read.assert_not_called()


def test_edit_foreign_parent_rejected_before_writer(monkeypatch, actor):
    monkeypatch.setattr(
        endpoint.KnowledgeService, "judge_qa_knowledge_write", Mock(return_value=SimpleNamespace(id=11, tenant_id=3))
    )
    monkeypatch.setattr(
        endpoint.QAKnoweldgeDao,
        "select_list",
        Mock(return_value=[SimpleNamespace(id=202, knowledge_id=22, tenant_id=3)]),
    )
    monkeypatch.setattr(endpoint.QAKnoweldgeDao, "get_qa_knowledge_by_name", Mock(return_value=None))
    write = Mock()
    monkeypatch.setattr(endpoint, "add_qa", write)
    monkeypatch.setattr(endpoint, "_audit_qa", Mock())
    with pytest.raises((HTTPException, NotFoundError, UnAuthorizedError, ValueError)):
        endpoint.qa_add(
            QACreate=QAKnowledgeUpsert(id=202, knowledge_id=11, questions=["q"], answers=["a"]), login_user=actor
        )
    write.assert_not_called()


@pytest.mark.parametrize("operation", ["qa_delete", "qa_append"])
@pytest.mark.parametrize(
    "rows",
    [
        [SimpleNamespace(id=101, knowledge_id=11, tenant_id=3, questions=[])],
        [
            SimpleNamespace(id=101, knowledge_id=11, tenant_id=3, questions=[]),
            SimpleNamespace(id=202, knowledge_id=22, tenant_id=3, questions=[]),
        ],
    ],
)
def test_mixed_batch_rejects_before_any_side_effect(monkeypatch, actor, operation, rows):
    monkeypatch.setattr(endpoint.QAKnoweldgeDao, "select_list", Mock(return_value=rows))
    monkeypatch.setattr(
        endpoint.KnowledgeService, "judge_qa_knowledge_write", Mock(return_value=SimpleNamespace(id=11, tenant_id=3))
    )
    delete = Mock()
    vector = Mock()
    append = Mock()
    monkeypatch.setattr(endpoint.QAKnoweldgeDao, "delete_batch", delete)
    monkeypatch.setattr(endpoint.knowledge_imp, "delete_vector_data", vector)
    monkeypatch.setattr(endpoint.knowledge_imp, "add_qa", append)
    monkeypatch.setattr(endpoint, "_audit_qa", Mock())
    monkeypatch.setattr(endpoint.telemetry_service, "log_event_sync", Mock())
    kwargs = {"ids": [101, 202], "login_user": actor}
    if operation == "qa_append":
        kwargs["question"] = "new"
    with pytest.raises((HTTPException, NotFoundError, UnAuthorizedError, ValueError)):
        getattr(endpoint, operation)(**kwargs)
    delete.assert_not_called()
    vector.assert_not_called()
    append.assert_not_called()


async def test_authorized_preview_reads_only_storage_bytes(monkeypatch, actor):
    from io import BytesIO

    from bisheng.knowledge.domain.services import preview_source_service as preview
    from bisheng.knowledge.domain.services import qa_import_service as service

    workbook = BytesIO()
    pd.DataFrame({"Question": ["q"], "Answer": ["a"]}).to_excel(workbook, index=False)
    raw = workbook.getvalue()
    response = SimpleNamespace(read=lambda size: raw[:size], close=Mock(), release_conn=Mock())
    storage = SimpleNamespace(tmp_bucket="temporary", download_object_sync=Mock(return_value=response))
    monkeypatch.setattr(service, "get_minio_storage", AsyncMock(return_value=storage))
    monkeypatch.setattr(preview, "get_minio_storage", AsyncMock(return_value=storage))
    record = {
        "user_id": 7,
        "tenant_id": 3,
        "knowledge_id": 0,
        "file_path": "opaque-upload-path",
        "object_name": "uploads/3/7/qa.xlsx",
        "file_name": "qa.xlsx",
    }
    monkeypatch.setattr(
        preview, "get_redis_client", AsyncMock(return_value=SimpleNamespace(aget=AsyncMock(return_value=record)))
    )
    authorize = AsyncMock()
    monkeypatch.setattr(endpoint.KnowledgeService, "ajudge_qa_knowledge_write", authorize)
    result = await endpoint.preview_qa_import_file(
        qa_knowledge_id=11,
        file_url="opaque-upload-path",
        preview_upload_ref="owned-ref",
        size=0,
        offset=0,
        login_user=actor,
    )
    assert result.data["result"][0].questions == ["q"]
    assert result.data["result"][0].answers == '["a"]'
    authorize.assert_awaited_once_with(actor, 11)
    storage.download_object_sync.assert_called_once_with(bucket_name="temporary", object_name="uploads/3/7/qa.xlsx")
    response.close.assert_called_once()
    response.release_conn.assert_called_once()


@pytest.mark.parametrize("mutation", [{"user_id": 8}, {"tenant_id": 8}, {"knowledge_id": 99}, {"file_path": "other"}])
async def test_foreign_upload_ref_never_reaches_storage_or_parser(monkeypatch, actor, mutation):
    from bisheng.knowledge.domain.services import preview_source_service as preview
    from bisheng.knowledge.domain.services import qa_import_service as service

    record = {
        "user_id": 7,
        "tenant_id": 3,
        "knowledge_id": 0,
        "file_path": "upload-path",
        "object_name": "qa.xlsx",
        "file_name": "qa.xlsx",
    } | mutation
    read = Mock()
    storage = SimpleNamespace(tmp_bucket="temporary", download_object_sync=read)
    monkeypatch.setattr(service, "get_minio_storage", AsyncMock(return_value=storage))
    monkeypatch.setattr(preview, "get_minio_storage", AsyncMock(return_value=storage))
    monkeypatch.setattr(
        preview, "get_redis_client", AsyncMock(return_value=SimpleNamespace(aget=AsyncMock(return_value=record)))
    )
    monkeypatch.setattr(endpoint.KnowledgeService, "ajudge_qa_knowledge_write", AsyncMock())
    with pytest.raises(HTTPException):
        await endpoint.preview_qa_import_file(
            qa_knowledge_id=11,
            file_url="upload-path",
            preview_upload_ref="foreign-ref",
            size=0,
            offset=0,
            login_user=actor,
        )
    read.assert_not_called()


async def test_import_resolves_all_refs_before_first_parse_or_write(monkeypatch, actor):
    monkeypatch.setattr(endpoint.KnowledgeService, "ajudge_qa_knowledge_write", AsyncMock())
    monkeypatch.setattr(endpoint.QAImportService, "source", AsyncMock(side_effect=[object(), NotFoundError()]))
    parser = AsyncMock()
    writer = Mock()
    monkeypatch.setattr(endpoint.QAImportService, "dataframe", parser)
    monkeypatch.setattr(endpoint.QAKnoweldgeDao, "batch_insert_qa", writer)
    with pytest.raises(NotFoundError):
        await endpoint.post_import_file(
            qa_knowledge_id=11,
            file_list=["one", "two"],
            preview_upload_refs=["ref1", "ref2"],
            background_tasks=BackgroundTasks(),
            login_user=actor,
        )
    parser.assert_not_awaited()
    writer.assert_not_called()


def test_valid_batch_deletion_uses_exact_ids_and_explicit_scope(monkeypatch, actor):
    rows = [
        SimpleNamespace(id=101, knowledge_id=11, tenant_id=3),
        SimpleNamespace(id=102, knowledge_id=11, tenant_id=3),
    ]
    monkeypatch.setattr(endpoint.QAKnoweldgeDao, "select_list", Mock(return_value=rows))
    knowledge = SimpleNamespace(id=11, tenant_id=3)
    monkeypatch.setattr(endpoint.KnowledgeService, "judge_qa_knowledge_write", Mock(return_value=knowledge))
    delete = Mock()
    monkeypatch.setattr(endpoint.QAKnoweldgeDao, "delete_batch", delete)
    monkeypatch.setattr(endpoint.knowledge_imp, "delete_vector_data", Mock())
    monkeypatch.setattr(endpoint, "_audit_qa", Mock())
    monkeypatch.setattr(endpoint.telemetry_service, "log_event_sync", Mock())
    endpoint.qa_delete(ids=[101, 102, 101], login_user=actor)
    delete.assert_called_once_with([101, 102], knowledge_id=11, tenant_id=3)


def test_root_add_qa_rejects_foreign_parent(monkeypatch, actor):
    monkeypatch.setattr(
        endpoint.QAKnoweldgeDao,
        "get_qa_knowledge_by_primary_id",
        Mock(return_value=SimpleNamespace(id=202, knowledge_id=22, tenant_id=3)),
    )
    write = Mock()
    monkeypatch.setattr(endpoint.QAKnoweldgeDao, "update", write)
    with pytest.raises(NotFoundError):
        endpoint.knowledge_imp.add_qa(
            SimpleNamespace(id=11, tenant_id=3, type=1),
            QAKnowledgeUpsert(id=202, knowledge_id=11, questions=["q"], answers=["a"]),
        )
    write.assert_not_called()


async def test_preview_permission_denied_before_ref_lookup(monkeypatch, actor):
    authorize = AsyncMock(side_effect=UnAuthorizedError())
    lookup = AsyncMock()
    monkeypatch.setattr(endpoint.KnowledgeService, "ajudge_qa_knowledge_write", authorize)
    monkeypatch.setattr(endpoint.QAImportService, "source", lookup)
    with pytest.raises(UnAuthorizedError):
        await endpoint.preview_qa_import_file(
            qa_knowledge_id=11, file_url="upload", preview_upload_ref="ref", size=0, offset=0, login_user=actor
        )
    lookup.assert_not_awaited()


def test_scoped_qa_delete_sql_does_not_delete_foreign_rows(monkeypatch, actor):
    from contextlib import contextmanager

    from sqlalchemy.pool import StaticPool
    from sqlmodel import Session, create_engine, select

    from bisheng.core.context.tenant import bypass_tenant_filter
    from bisheng.knowledge.domain.models import knowledge_file as models

    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    models.QAKnowledge.__table__.create(engine)
    with Session(engine) as session:
        session.add_all(
            [
                models.QAKnowledge(id=101, tenant_id=3, knowledge_id=11, questions=["q"], answers='["a"]'),
                models.QAKnowledge(id=202, tenant_id=8, knowledge_id=22, questions=["foreign"], answers='["a"]'),
                models.QAKnowledge(id=203, tenant_id=3, knowledge_id=22, questions=["other-parent"], answers='["a"]'),
            ]
        )
        session.commit()

    @contextmanager
    def database():
        with Session(engine) as session:
            yield session

    monkeypatch.setattr(models, "get_sync_db_session", database)
    models.QAKnoweldgeDao.delete_batch([101, 202, 203], knowledge_id=11, tenant_id=3)
    # Assert physical preservation across all tenants, not the caller-visible
    # SELECT projection (other suites may have registered the tenant listener).
    with bypass_tenant_filter(), Session(engine) as session:
        assert set(session.exec(select(models.QAKnowledge.id)).all()) == {202, 203}
    engine.dispose()


async def test_authorized_import_creates_only_target_parent_and_dispatches(monkeypatch, actor):
    monkeypatch.setattr(endpoint.KnowledgeService, "ajudge_qa_knowledge_write", AsyncMock())
    monkeypatch.setattr(endpoint.QAImportService, "source", AsyncMock(return_value=object()))
    monkeypatch.setattr(
        endpoint.QAImportService,
        "dataframe",
        AsyncMock(return_value=pd.DataFrame({"Question": ["q"], "Answer": ["a"]})),
    )
    monkeypatch.setattr(endpoint.QAKnoweldgeDao, "get_qa_knowledge_by_name", Mock(return_value=None))
    inserted = []

    def insert(rows):
        inserted.extend(rows)
        return [SimpleNamespace(id=101)]

    monkeypatch.setattr(endpoint.QAKnoweldgeDao, "batch_insert_qa", insert)
    dispatch = Mock()
    monkeypatch.setattr(endpoint.insert_qa_celery, "delay", dispatch)
    monkeypatch.setattr(endpoint.telemetry_service, "log_event_sync", Mock())
    monkeypatch.setattr(endpoint, "_audit_qa", Mock())
    await endpoint.post_import_file(
        qa_knowledge_id=11,
        file_list=["uploaded"],
        preview_upload_refs=["ref"],
        background_tasks=BackgroundTasks(),
        login_user=actor,
    )
    assert len(inserted) == 1
    assert inserted[0].knowledge_id == 11
    assert inserted[0].user_id == actor.user_id
    dispatch.assert_called_once_with(101)


async def test_raw_import_paths_rejected_before_source_parser(monkeypatch, actor):
    monkeypatch.setattr(endpoint.KnowledgeService, "ajudge_qa_knowledge_write", AsyncMock())
    parser = AsyncMock()
    monkeypatch.setattr(endpoint.QAImportService, "dataframe", parser)
    with pytest.raises(NotFoundError):
        await endpoint.post_import_file(
            qa_knowledge_id=11,
            file_list=["/tmp/private.xlsx"],
            preview_upload_refs=None,
            background_tasks=BackgroundTasks(),
            login_user=actor,
        )
    parser.assert_not_awaited()

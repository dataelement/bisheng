"""Rebuild commands use current business models and atomic SQL/R2 completion.

覆盖 AC: AC-54, AC-68, AC-71, AC-74, AC-79, AC-86, AC-87, AC-88, AC-89, AC-91, AC-92, AC-93.
Real Core/Model Owners, SQLite and Celery lifecycle issuance are exercised;
provider, vectorstore and file DAO transports are explicit isolated doubles.
"""

from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import sqlalchemy as sa
from sqlmodel import Session

from bisheng.common.errcode.knowledge import (
    KnowledgeOperationPlanConflictError,
    ReferenceCoverageNotReadyError,
    ResourceReferenceInvalidError,
)
from bisheng.knowledge.application import model_reference_read as read_module
from bisheng.knowledge.application.model_reference import KnowledgeModelReferenceApplication as App
from bisheng.knowledge.domain.knowledge_rag import KnowledgeRag
from bisheng.knowledge.domain.models.knowledge import Knowledge
from bisheng.llm.domain.models.llm_server import LLMModel
from bisheng.permission.application.identity import reset_current_permission_actor, set_current_permission_actor
from bisheng.resource_reference.domain.models.business_reference_set import BusinessReferenceSet
from bisheng.resource_reference.domain.models.resource_reference_tombstone import ResourceReferenceTombstone
from bisheng.worker import tenant_context as workers
from bisheng.worker.knowledge import qa
from bisheng.worker.knowledge import rebuild_knowledge_worker as document
from test.knowledge_unification import test_kn_model_bindings as business_fixtures
from test.knowledge_unification import test_kn_model_source as read_fixtures

store = read_fixtures.store
tenant = read_fixtures.tenant
business = read_fixtures.business
admission = read_fixtures.admission


@pytest.fixture
async def rebuild(admission, monkeypatch):
    context, runtime, _, _ = admission
    with Session(context.sync) as session, session.begin():
        session.execute(
            sa.update(Knowledge)
            .where(Knowledge.id == 40, Knowledge.tenant_id == 101)
            .values(index_name="idx40", collection_name="col40")
        )
    async with context.sessions() as session:
        change = await App.aprepare_model_change(session, 40, 12, login_user=context.user, operation_id="build-1")
        await App.aapply_model_change(session, change)
        await session.commit()

    @contextmanager
    def sessions():
        with Session(context.sync, expire_on_commit=False) as session:
            yield session

    # Also isolate legacy DAO access before the red worker has been replaced.
    def load(knowledge_id):
        with sessions() as session:
            return App.repository.get(session, knowledge_id)

    def save(row):
        with sessions() as session:
            session.merge(row)
            session.commit()

    monkeypatch.setattr(read_module, "_runtime", runtime)
    monkeypatch.setattr(
        KnowledgeRag, "_get_knowledge_sync", lambda knowledge=None, knowledge_id=None: knowledge or load(knowledge_id)
    )
    monkeypatch.setattr(document.KnowledgeDao, "query_by_id", load)
    monkeypatch.setattr(document.KnowledgeDao, "update_one", save)
    monkeypatch.setattr(read_module, "get_sync_db_session", sessions)
    for module in (document, qa):
        # New worker imports use the same original external Session factory.
        monkeypatch.setattr(module, "get_sync_db_session", sessions, raising=False)
        monkeypatch.setattr(module, "get_knowledge_model_read_runtime_sync", lambda: runtime, raising=False)

    events = []
    files = [SimpleNamespace(id=701, status=2, remark=None), SimpleNamespace(id=702, status=2, remark=None)]
    file_dao = Mock()
    file_dao.get_files_by_multiple_status.side_effect = lambda *args: (events.append("files"), files)[1]
    file_dao.update_status_bulk.side_effect = lambda *args: events.append("file_status")
    monkeypatch.setattr(document, "KnowledgeFileDao", file_dao)
    qa_dao = Mock()
    qa_dao.batch_update_status_by_ids.side_effect = lambda **kwargs: events.append("qa_status")
    monkeypatch.setattr(qa, "QAKnoweldgeDao", qa_dao)

    es = SimpleNamespace(client=Mock())
    es.client.indices.exists.return_value = True
    es.client.delete_by_query.return_value = {"deleted": 1}

    def search(*args, **kwargs):
        events.append("search")
        if kwargs.get("filter_path") == ["hits.total.value"]:
            return {"hits": {"total": {"value": 1}}}
        return {"hits": {"hits": [{"_source": {"text": "actual text", "metadata": {"file_id": 701}}}]}}

    es.client.search.side_effect = search

    def es_transport(*args, **kwargs):
        events.append("es")
        return es

    vector = SimpleNamespace(col=SimpleNamespace(drop=Mock()), add_texts=Mock())

    def vector_transport(*args, **kwargs):
        events.append("milvus")
        return vector

    embedding = Mock()
    embedding.embed_query.return_value = [0.1]

    def provider(*args, **kwargs):
        events.append(("provider", kwargs["model_id"], kwargs.get("invoke_user_id")))
        return embedding

    monkeypatch.setattr(KnowledgeRag, "init_es_vectorstore_sync", es_transport)
    monkeypatch.setattr(KnowledgeRag, "init_milvus_vectorstore", vector_transport)
    monkeypatch.setattr(document.LLMService, "get_bisheng_knowledge_embedding_sync", Mock(side_effect=provider))
    monkeypatch.setattr(document, "_process_single_file", Mock(return_value=True))
    sender = SimpleNamespace(
        name="bisheng.worker.knowledge.rebuild_knowledge_worker.rebuild_knowledge_celery",
        request=SimpleNamespace(id="actual-command", headers={"tenant_id": 101}, called_directly=False),
    )
    monkeypatch.setattr(workers, "current_task", SimpleNamespace(_get_current_object=lambda: sender))
    actor = set_current_permission_actor(None)
    workers.restore_tenant_context(sender=sender)
    before = business_fixtures.state(context)
    row = next(item for item in before["knowledge"] if item["id"] == 40)
    arguments = {
        "operation_id": "build-1",
        "expected_model_config_revision": row["model_config_revision"],
        "expected_index_generation": row["index_generation"],
    }
    try:
        yield SimpleNamespace(
            context=context,
            runtime=runtime,
            sessions=sessions,
            events=events,
            files=files,
            file_dao=file_dao,
            qa_dao=qa_dao,
            es=es,
            vector=vector,
            sender=sender,
            before=before,
            arguments=arguments,
        )
    finally:
        workers.reset_tenant_context(sender=sender)
        reset_current_permission_actor(actor)


def execute(rebuild, kind, *, hint=None, arguments=None):
    task = document.rebuild_knowledge_celery if kind == "document" else qa.rebuild_qa_knowledge_celery
    return task.run(40, hint, 987, **(rebuild.arguments if arguments is None else arguments))


def assert_stage_preserved(rebuild):
    assert business_fixtures.state(rebuild.context) == rebuild.before


def assert_finalized(rebuild):
    state = business_fixtures.state(rebuild.context)
    row = next(item for item in state["knowledge"] if item["id"] == 40)
    assert row["model"] == "12" and row["model_transition"] is None and row["state"] == 1
    assert row["model_config_revision"] == rebuild.arguments["expected_model_config_revision"] + 1
    assert row["index_generation"] == rebuild.arguments["expected_index_generation"]
    assert [(item["slot_key"], item["target_id"]) for item in state["business_resource_reference"]] == [("model", "12")]


@pytest.mark.parametrize("kind", ["document", "qa"])
def test_legacy_message_without_expectations_is_rejected_before_any_io(rebuild, kind):
    with pytest.raises(KnowledgeOperationPlanConflictError):
        execute(rebuild, kind, hint=12, arguments={})
    assert rebuild.events == []
    assert_stage_preserved(rebuild)


@pytest.mark.parametrize("kind", ["document", "qa"])
def test_real_pending_model_is_selected_and_business_and_references_finalize_together(rebuild, kind):
    execute(rebuild, kind)
    assert ("provider", 12, 987) in rebuild.events
    assert_finalized(rebuild)


@pytest.mark.parametrize("kind", ["document", "qa"])
@pytest.mark.parametrize("field", ["operation_id", "expected_model_config_revision", "expected_index_generation"])
def test_missing_or_obsolete_expectation_cannot_be_filled_from_current_resource(rebuild, kind, field):
    for invalid in (None, "old" if field != "expected_model_config_revision" else 99):
        with pytest.raises(KnowledgeOperationPlanConflictError):
            execute(rebuild, kind, arguments={**rebuild.arguments, field: invalid})
    assert rebuild.events == []
    assert_stage_preserved(rebuild)


@pytest.mark.parametrize("kind", ["document", "qa"])
def test_legacy_model_hint_cannot_select_a_different_provider(rebuild, kind):
    with pytest.raises(KnowledgeOperationPlanConflictError):
        execute(rebuild, kind, hint=11)
    assert rebuild.events == []
    assert_stage_preserved(rebuild)


@pytest.mark.parametrize("kind", ["document", "qa"])
def test_numeric_tenant_without_actual_celery_lifecycle_is_not_a_worker_permit(rebuild, kind):
    workers.reset_tenant_context(sender=rebuild.sender)
    # A legitimate tenant scope alone must not become a background identity.
    from bisheng.core.context.tenant import tenant_execution_scope

    with tenant_execution_scope(101), pytest.raises(ResourceReferenceInvalidError):
        execute(rebuild, kind)
    assert rebuild.events == []
    assert_stage_preserved(rebuild)


@pytest.mark.parametrize("kind", ["document", "qa"])
@pytest.mark.parametrize("damage", ["missing_index", "deleted_current", "no_stage", "drift"])
def test_full_source_or_stage_failure_precedes_files_vectors_and_provider(rebuild, kind, damage):
    with rebuild.sessions() as session, session.begin():
        if damage == "missing_index":
            session.execute(
                sa.delete(BusinessReferenceSet).where(
                    BusinessReferenceSet.source_type == "knowledge",
                    BusinessReferenceSet.record_kind == "source",
                    BusinessReferenceSet.source_id == "40",
                    BusinessReferenceSet.tenant_id == 101,
                )
            )
        elif damage == "deleted_current":
            session.execute(sa.delete(LLMModel).where(LLMModel.id == 11, LLMModel.tenant_id == 101))
            session.add(
                ResourceReferenceTombstone(
                    target_type="model", target_id="11", tenant_id=101, operation_id="delete-a", stage="deleted"
                )
            )
        elif damage == "no_stage":
            session.execute(
                sa.update(Knowledge).where(Knowledge.id == 40, Knowledge.tenant_id == 101).values(model_transition=None)
            )
        else:
            session.execute(
                sa.update(Knowledge).where(Knowledge.id == 40, Knowledge.tenant_id == 101).values(model="12")
            )
    before = business_fixtures.state(rebuild.context)
    error = (
        KnowledgeOperationPlanConflictError
        if damage == "no_stage"
        else ResourceReferenceInvalidError
        if damage == "deleted_current"
        else ReferenceCoverageNotReadyError
    )
    with pytest.raises(error):
        execute(rebuild, kind)
    assert rebuild.events == []
    assert business_fixtures.state(rebuild.context) == before


@pytest.mark.parametrize("kind", ["document", "qa"])
def test_global_provider_failure_preserves_unfinished_stage_and_does_not_finalize(rebuild, kind, monkeypatch):
    monkeypatch.setattr(
        document.LLMService,
        "get_bisheng_knowledge_embedding_sync",
        Mock(side_effect=RuntimeError("provider unavailable")),
    )
    with pytest.raises(RuntimeError, match="provider unavailable"):
        execute(rebuild, kind)
    assert_stage_preserved(rebuild)


@pytest.mark.parametrize("kind", ["document", "qa"])
def test_finalize_r2_failure_rolls_back_model_stage_state_and_references(rebuild, kind, monkeypatch):
    original = App.apply_finalization

    def fail_after_apply(session, prepared):
        original(session, prepared)
        raise RuntimeError("finalization transaction failed")

    monkeypatch.setattr(App, "apply_finalization", fail_after_apply)
    with pytest.raises(RuntimeError, match="finalization transaction failed"):
        execute(rebuild, kind)
    assert_stage_preserved(rebuild)


def test_guard_error_inside_document_rag_is_not_laundered_into_controlled_file_failure(rebuild, monkeypatch):
    monkeypatch.setattr(
        KnowledgeRag,
        "init_knowledge_es_vectorstore_sync",
        Mock(side_effect=ReferenceCoverageNotReadyError(reason="changed")),
    )
    with pytest.raises(ReferenceCoverageNotReadyError):
        execute(rebuild, "document")
    assert_stage_preserved(rebuild)


def test_controlled_document_partial_failure_keeps_item_diagnostic_and_completes_transition(rebuild, monkeypatch):
    monkeypatch.setattr(document, "_process_single_file", Mock(side_effect=[True, RuntimeError("bad file")]))
    execute(rebuild, "document")
    assert rebuild.files[1].status == 3 and rebuild.files[1].remark
    assert_finalized(rebuild)


def test_controlled_qa_batch_failure_keeps_item_diagnostic_and_completes_transition(rebuild):
    rebuild.vector.add_texts.side_effect = RuntimeError("bad QA batch")
    execute(rebuild, "qa")
    failed = [
        call.kwargs
        for call in rebuild.qa_dao.batch_update_status_by_ids.call_args_list
        if call.kwargs["status"] == qa.QAStatus.FAILED
    ]
    assert failed and failed[0]["qa_ids"] == [701] and failed[0]["remark"]
    assert_finalized(rebuild)


@pytest.mark.parametrize("kind", ["document", "qa"])
def test_empty_resource_still_atomically_completes_current_business_transition(rebuild, kind):
    rebuild.file_dao.get_files_by_multiple_status.return_value = []
    rebuild.file_dao.get_files_by_multiple_status.side_effect = lambda *args: []
    if kind == "qa":
        rebuild.es.client.search.side_effect = lambda **kwargs: {"hits": {"total": {"value": 0}}}
    execute(rebuild, kind)
    assert_finalized(rebuild)


def test_obsolete_after_processing_cannot_publish_or_release_current_stage(rebuild, monkeypatch):
    def changed(*args):
        with rebuild.sessions() as session, session.begin():
            row = App.repository.get(session, 40)
            row.model_transition = {**row.model_transition, "operation_id": "new-build"}
        return True

    monkeypatch.setattr(document, "_process_single_file", changed)
    with pytest.raises(KnowledgeOperationPlanConflictError):
        execute(rebuild, "document")
    state = business_fixtures.state(rebuild.context)
    row = next(item for item in state["knowledge"] if item["id"] == 40)
    assert row["model"] == "11" and row["state"] == 3
    assert row["model_transition"]["operation_id"] == "new-build"
    assert state["business_resource_reference"] == rebuild.before["business_resource_reference"]

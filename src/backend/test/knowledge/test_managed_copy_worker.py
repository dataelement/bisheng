"""F009 AC-34/35: observed child failure never publishes a partial copy."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from bisheng.core.context.tenant import bypass_tenant_filter, tenant_execution_scope
from bisheng.knowledge.domain.models.knowledge import Knowledge, KnowledgeTypeEnum
from bisheng.knowledge.domain.repositories.copy_repository import CopyRepository
from bisheng.worker.tenant_context import reset_tenant_context, restore_tenant_context
from test.fixtures.managed_tenant import managed_db as managed_db
from test.knowledge.test_managed_tenant_copy import copy_db as copy_db


def invoke(task, name, *args, **kwargs):
    sender = SimpleNamespace(name=name, request=SimpleNamespace(headers={"tenant_id": 2}))
    with tenant_execution_scope(1):
        restore_tenant_context(sender=sender)
        try:
            return task.run(*args, **kwargs)
        finally:
            reset_tenant_context(sender=sender)


async def test_document_failure_stops_publication_and_duplicate_replay(copy_db, monkeypatch):
    from bisheng.knowledge.application import copy_execution
    from bisheng.worker.knowledge import file_worker

    db, source = copy_db
    target = await CopyRepository.reserve(source, Knowledge(name="target", tenant_id=2, user_id=7))
    monkeypatch.setattr(copy_execution, "assert_copy_actor", Mock())
    monkeypatch.setattr(file_worker.KnowledgeFileDao, "get_file_by_condition", Mock(return_value=[]))
    monkeypatch.setattr(
        file_worker.KnowledgeFileDao,
        "get_file_by_filters",
        Mock(return_value=[SimpleNamespace(id=101, file_name="broken")]),
    )
    copy = Mock(side_effect=RuntimeError("external copy failed"))
    monkeypatch.setattr(file_worker, "copy_normal", copy)
    args = {"source_knowledge_id": 10, "target_id": target.id, "login_user_id": 7, "tenant_id": 2}
    name = "bisheng.worker.knowledge.file_worker.file_copy_celery"
    with pytest.raises(RuntimeError, match="external copy failed"):
        invoke(file_worker.file_copy_celery, name, args)
    assert invoke(file_worker.file_copy_celery, name, args) == "duplicate copy ignored"
    assert copy.call_count == 1
    with bypass_tenant_filter(), db.sync_sessions() as session:
        assert session.get(Knowledge, target.id).state == 4
        assert session.get(Knowledge, 10).copy_target_id == target.id


async def test_qa_batch_failure_stops_publication(copy_db, monkeypatch):
    from bisheng.knowledge.application import copy_execution
    from bisheng.knowledge.domain.models.knowledge_file import QAKnowledge
    from bisheng.worker.knowledge import qa

    db, source = copy_db
    with bypass_tenant_filter(), db.sync_sessions() as session:
        source = session.get(Knowledge, 10)
        source.type = KnowledgeTypeEnum.QA.value
        session.add(source)
        session.commit()
    target = await CopyRepository.reserve(
        source, Knowledge(name="qa target", type=KnowledgeTypeEnum.QA.value, tenant_id=2, user_id=7)
    )
    monkeypatch.setattr(copy_execution, "assert_copy_actor", Mock())
    monkeypatch.setattr(qa.QAKnoweldgeDao, "count_by_id", Mock(return_value=1))
    monkeypatch.setattr(
        qa.QAKnoweldgeDao,
        "get_qa_knowledge_by_knowledge_id",
        Mock(return_value=[QAKnowledge(id=101, knowledge_id=10, user_id=8, tenant_id=2, questions=["q"], answers="a")]),
    )
    monkeypatch.setattr(
        qa.KnowledgeRag,
        "init_knowledge_milvus_vectorstore_sync",
        Mock(
            return_value=SimpleNamespace(
                col=SimpleNamespace(schema="schema"), alias="default", consistency_level="Session"
            )
        ),
    )
    monkeypatch.setattr(qa, "Collection", Mock())
    monkeypatch.setattr(qa.QAKnoweldgeDao, "batch_insert_qa", Mock(side_effect=RuntimeError("QA SQL failed")))
    monkeypatch.setattr(qa.QAKnoweldgeDao, "batch_update_status_by_ids", Mock())
    with pytest.raises(RuntimeError, match="QA SQL failed"):
        invoke(
            qa.copy_qa_knowledge_celery,
            "bisheng.worker.knowledge.qa.copy_qa_knowledge_celery",
            10,
            target.id,
            7,
            tenant_id=2,
        )
    with bypass_tenant_filter(), db.sync_sessions() as session:
        assert session.get(Knowledge, target.id).state == 4
        assert session.get(Knowledge, 10).copy_target_id == target.id

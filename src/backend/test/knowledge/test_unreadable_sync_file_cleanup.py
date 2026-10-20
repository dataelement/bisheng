from contextlib import contextmanager
from unittest.mock import MagicMock

import pytest
from sqlalchemy import create_engine
from sqlmodel import Session, select

from bisheng.common.errcode.base import BaseErrorCode
from bisheng.knowledge.domain.models.knowledge import Knowledge
from bisheng.knowledge.domain.models.knowledge_background_job import KnowledgeBackgroundJob
from bisheng.knowledge.domain.models.knowledge_document import KnowledgeDocument
from bisheng.knowledge.domain.models.knowledge_document_version import KnowledgeDocumentVersion
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile
from bisheng.knowledge.domain.models.knowledge_fulltext_outbox import KnowledgeFulltextOutbox
from bisheng.knowledge.domain.services.knowledge_fulltext_parse_hook import persist_parse_result_with_fulltext_intent


def failed_file(**overrides):
    import json

    return KnowledgeFile(
        **{
            "id": 7,
            "tenant_id": 1,
            "knowledge_id": 9,
            "file_name": "broken.pdf",
            "object_name": "original/broken.pdf",
            "md5": "original-hash",
            "status": 3,
            "user_metadata": {"filelib_sync_endpoint": "sync", "developer_token_id": 12, "external_file_id": "ext7"},
            "remark": json.dumps({"status_code": 10958, "data": {"reason": "damaged"}}),
            **overrides,
        }
    )


def detached_failure(engine, **overrides):
    with Session(engine) as session:
        file = session.get(KnowledgeFile, 7)
        values = {"status": 3, "remark": failed_file().remark, **overrides}
        for key, value in values.items():
            setattr(file, key, value)
        session.expunge(file)
        return file


@pytest.fixture
def database(monkeypatch):
    from bisheng.approval.domain.models.approval_instance import ApprovalInstance
    from bisheng.database.models.review_tags import ReviewTagLink
    from bisheng.database.models.tag import TagLink
    from bisheng.knowledge.domain.models.department_file_view_grant import DepartmentFileViewGrant
    from bisheng.knowledge.domain.models.knowledge_file_correction import KnowledgeFileCorrection
    from bisheng.knowledge.domain.models.knowledge_file_pdf_artifact import KnowledgeFilePdfArtifact
    from bisheng.knowledge.domain.models.knowledge_file_similarity_candidate import KnowledgeFileSimilarityCandidate
    from bisheng.knowledge.domain.models.portal_recommendation_file_projection import PortalRecommendationFileProjection
    from bisheng.knowledge.domain.services import knowledge_fulltext_after_commit_service

    engine = create_engine("sqlite://")
    models = [
        Knowledge,
        KnowledgeFile,
        KnowledgeDocument,
        KnowledgeDocumentVersion,
        KnowledgeBackgroundJob,
        KnowledgeFulltextOutbox,
        ApprovalInstance,
        TagLink,
        ReviewTagLink,
        DepartmentFileViewGrant,
        KnowledgeFileCorrection,
        KnowledgeFilePdfArtifact,
        KnowledgeFileSimilarityCandidate,
        PortalRecommendationFileProjection,
    ]
    for model in models:
        model.__table__.create(engine)
    monkeypatch.setattr(knowledge_fulltext_after_commit_service, "_publish_ref", MagicMock())
    with Session(engine) as session:
        session.add(Knowledge(id=9, tenant_id=1, name="sync", type=3, user_id=1))
        session.add(failed_file(status=1, remark=""))
        session.add(KnowledgeDocument(id=20, tenant_id=1, knowledge_id=9, primary_version_id=30))
        session.add(KnowledgeDocumentVersion(id=30, document_id=20, knowledge_file_id=7, version_no=1, is_primary=True))
        session.commit()

    @contextmanager
    def factory():
        with Session(engine) as session:
            yield session

    yield engine, factory
    engine.dispose()


def test_interface_pipeline_identifies_unreadable_original_before_parser(tmp_path, monkeypatch):
    from bisheng.knowledge.rag import knowledge_file_pipeline as module

    path = tmp_path / "broken.pdf"
    path.write_bytes(b"not a readable PDF")
    monkeypatch.setattr(module, "download_minio_file", lambda **kwargs: (str(path), None))
    pipeline = object.__new__(module.KnowledgeFilePipeline)
    pipeline.db_file = failed_file()
    pipeline.tmp_dir = str(tmp_path)
    with pytest.raises(BaseErrorCode) as caught:
        pipeline.prepare_local_file()
    assert caught.value.code == 10958
    assert caught.value.kwargs["reason"] == "damaged"
    assert path.exists()


def test_parse_failure_atomically_deletes_only_failed_record_and_records_cleanup(database):
    from bisheng.database.models.review_tags import ReviewTagLink
    from bisheng.database.models.tag import TagLink
    from bisheng.knowledge.domain.models.knowledge_file_pdf_artifact import KnowledgeFilePdfArtifact

    engine, factory = database
    with Session(engine) as session:
        session.add(TagLink(id=1, tenant_id=1, tag_id=1, resource_id="7", resource_type=8))
        session.add(TagLink(id=2, tenant_id=1, tag_id=1, resource_id="8", resource_type=8))
        session.add(ReviewTagLink(id=1, tenant_id=1, tag_id=1, resource_id="7", resource_type=8))
        session.add(
            KnowledgeFilePdfArtifact(
                id=1,
                tenant_id=1,
                knowledge_file_id=7,
                source_object_name="original/broken.pdf",
                object_name="generated/7.pdf",
            )
        )
        session.commit()
    persist_parse_result_with_fulltext_intent(
        detached_failure(engine), session_factory=factory, multi_tenant_enabled=False
    )
    with Session(engine) as session:
        assert session.get(KnowledgeFile, 7) is None
        assert session.get(KnowledgeDocument, 20) is None
        assert session.get(KnowledgeDocumentVersion, 30) is None
        job = session.exec(select(KnowledgeBackgroundJob)).one()
        assert job.kind == "delete_file"
        assert job.payload["cleanup_permissions"] is True
        assert job.payload["file"]["user_metadata"]["external_file_id"] == "ext7"
        assert job.payload["file"]["remark"] == failed_file().remark
        assert job.payload["artifacts"][0]["object_name"] == "generated/7.pdf"
        assert session.get(TagLink, 1) is None
        assert session.get(TagLink, 2) is not None
        assert session.get(ReviewTagLink, 1) is None
        assert session.get(KnowledgeFilePdfArtifact, 1) is None
        assert session.exec(select(KnowledgeFulltextOutbox)).one().desired_action == "delete_current"


@pytest.mark.parametrize(
    "overrides",
    [
        {"user_metadata": {}},
        {"remark": "timeout"},
        {"status": 6},
        {"remark": '{"status_code":10953,"data":{"exception":"encrypted file"}}'},
        {"entry_type": "manager", "reference_document_id": 20},
        {"approval_instance_id": 50},
        {"simhash": "aaaaaaaaaaaaaaaa"},
    ],
)
def test_other_failures_and_protected_files_are_retained(database, overrides):
    engine, factory = database
    persist_parse_result_with_fulltext_intent(
        detached_failure(engine, **overrides), session_factory=factory, multi_tenant_enabled=False
    )
    with Session(engine) as session:
        assert session.get(KnowledgeFile, 7) is not None
        assert session.exec(select(KnowledgeBackgroundJob)).all() == []


@pytest.mark.parametrize("relationship", ["history", "share", "favorite", "correction", "approval"])
def test_business_references_block_cleanup(database, relationship):
    from bisheng.approval.domain.models.approval_instance import ApprovalInstance
    from bisheng.knowledge.domain.models.knowledge_file_correction import KnowledgeFileCorrection

    engine, factory = database
    with Session(engine) as session:
        if relationship == "history":
            session.add(KnowledgeDocumentVersion(id=31, document_id=20, knowledge_file_id=8, version_no=2))
        elif relationship == "share":
            session.add(KnowledgeFile(id=8, tenant_id=1, knowledge_id=9, file_name="share", share_source_file_id=7))
        elif relationship == "favorite":
            session.add(
                KnowledgeFile(
                    id=8,
                    tenant_id=1,
                    knowledge_id=9,
                    file_name="favorite",
                    file_source="favorite_reference",
                    user_metadata={"favorite_reference": {"source_file_id": 7}},
                )
            )
        elif relationship == "correction":
            session.add(
                KnowledgeFileCorrection(
                    id=1,
                    tenant_id=1,
                    file_id=7,
                    knowledge_id=9,
                    applicant_user_id=1,
                    uploader_user_id=1,
                    content="retain",
                )
            )
        else:
            session.add(
                ApprovalInstance(
                    id=50,
                    tenant_id=1,
                    scenario_code="test",
                    scenario_name="test",
                    handler_key="test",
                    business_key="file:7",
                    business_resource_type="knowledge_file",
                    business_resource_id="7",
                    business_name="test",
                    applicant_user_id=1,
                    applicant_user_name="u",
                    status="pending",
                )
            )
        session.commit()
    persist_parse_result_with_fulltext_intent(
        detached_failure(engine), session_factory=factory, multi_tenant_enabled=False
    )
    with Session(engine) as session:
        assert session.get(KnowledgeFile, 7).status == 3
        assert session.get(KnowledgeDocumentVersion, 30) is not None
        assert session.exec(select(KnowledgeBackgroundJob)).all() == []


def test_cleanup_and_outbox_rollback_together(database, monkeypatch):
    from bisheng.knowledge.domain.repositories.implementations.knowledge_fulltext_outbox_sync_repository_impl import (
        KnowledgeFulltextOutboxSyncRepositoryImpl,
    )

    engine, factory = database
    monkeypatch.setattr(
        KnowledgeFulltextOutboxSyncRepositoryImpl,
        "request_file_sync",
        MagicMock(side_effect=RuntimeError("outbox unavailable")),
    )
    with pytest.raises(RuntimeError, match="outbox unavailable"):
        persist_parse_result_with_fulltext_intent(
            detached_failure(engine), session_factory=factory, multi_tenant_enabled=False
        )
    with Session(engine) as session:
        assert session.get(KnowledgeFile, 7).status == 1
        assert session.get(KnowledgeDocumentVersion, 30) is not None
        assert session.exec(select(KnowledgeBackgroundJob)).all() == []


def test_repeated_parse_result_does_not_resurrect_deleted_file(database):
    engine, factory = database
    file = detached_failure(engine)
    for _ in range(2):
        persist_parse_result_with_fulltext_intent(file, session_factory=factory, multi_tenant_enabled=False)
    with Session(engine) as session:
        assert session.get(KnowledgeFile, 7) is None
        assert len(session.exec(select(KnowledgeBackgroundJob)).all()) == 1
        assert session.exec(select(KnowledgeFulltextOutbox)).one().desired_revision == 1


def test_other_file_using_same_original_keeps_storage_reference(database):
    from bisheng.knowledge.domain.repositories.implementations.knowledge_background_repository_impl import (
        KnowledgeBackgroundRepositoryImpl,
    )

    engine, factory = database
    with Session(engine) as session:
        session.add(
            KnowledgeFile(id=8, tenant_id=1, knowledge_id=9, file_name="other.pdf", object_name="original/broken.pdf")
        )
        session.commit()
    persist_parse_result_with_fulltext_intent(
        detached_failure(engine), session_factory=factory, multi_tenant_enabled=False
    )
    with Session(engine) as session:
        assert session.get(KnowledgeFile, 7) is None
        assert session.get(KnowledgeFile, 8) is not None
        assert KnowledgeBackgroundRepositoryImpl(session).object_is_referenced("original/broken.pdf")


@pytest.mark.parametrize(
    "changes",
    [
        {"object_name": "new-original.pdf"},
        {"status": 2},
        {"tenant_id": 2},
        {"user_metadata": {}},
    ],
)
def test_stale_failure_does_not_overwrite_current_file(database, changes):
    engine, factory = database
    file = detached_failure(engine)
    with Session(engine) as session:
        current = session.get(KnowledgeFile, 7)
        for key, value in changes.items():
            setattr(current, key, value)
        session.add(current)
        session.commit()
    persist_parse_result_with_fulltext_intent(file, session_factory=factory, multi_tenant_enabled=False)
    with Session(engine) as session:
        current = session.get(KnowledgeFile, 7)
        assert all(getattr(current, key) == value for key, value in changes.items())
        assert session.exec(select(KnowledgeBackgroundJob)).all() == []


@pytest.mark.parametrize("routed", [False, True], ids=["legacy", "shared"])
def test_formal_parse_failure_contract_deletes_unreadable_source(database, tmp_path, monkeypatch, routed):
    from types import SimpleNamespace

    from bisheng.api.services import knowledge_imp
    from bisheng.core.config.settings import KnowledgeConf
    from bisheng.knowledge.rag import base_file_pipeline, knowledge_file_pipeline, shared_space_storage

    engine, factory = database
    monkeypatch.setattr(base_file_pipeline, "settings", SimpleNamespace(get_knowledge=lambda: KnowledgeConf()))
    path = tmp_path / "broken.pdf"
    path.write_bytes(b"not a PDF")
    with Session(engine) as session:
        file = session.get(KnowledgeFile, 7)
        knowledge = session.get(Knowledge, 9)
        session.expunge_all()
    monkeypatch.setattr(knowledge_imp.KnowledgeDao, "query_by_id", lambda _: knowledge)
    monkeypatch.setattr(
        knowledge_imp,
        "persist_parse_result_with_fulltext_intent",
        lambda row: persist_parse_result_with_fulltext_intent(row, session_factory=factory, multi_tenant_enabled=False),
    )
    monkeypatch.setattr(
        shared_space_storage, "resolve_space_shared_routing", lambda **kwargs: SimpleNamespace() if routed else None
    )
    monkeypatch.setattr(knowledge_file_pipeline, "download_minio_file", lambda **kwargs: (str(path), None))
    monkeypatch.setattr(knowledge_imp.KnowledgeRag, "init_knowledge_milvus_vectorstore_sync", MagicMock())
    monkeypatch.setattr(knowledge_imp.KnowledgeRag, "init_knowledge_es_vectorstore_sync", MagicMock())
    monkeypatch.setattr(knowledge_imp.KnowledgeUtils, "ensure_milvus_schema_ready", MagicMock())
    monkeypatch.setattr(knowledge_imp.telemetry_service, "log_event_sync", MagicMock())
    knowledge_imp.addEmbedding(9, [file])
    with Session(engine) as session:
        assert session.get(KnowledgeFile, 7) is None
        assert session.exec(select(KnowledgeBackgroundJob)).one().payload["cleanup_permissions"]

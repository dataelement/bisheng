"""delete_version: remove a historical (non-primary) version."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
import sqlalchemy as sa
from fastapi import HTTPException
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.errcode.knowledge import KnowledgeOperationPlanConflictError
from bisheng.common.errcode.permission import PermissionProjectionFailedError
from bisheng.knowledge.application.model_reference import KnowledgeModelReferenceApplication
from bisheng.knowledge.domain.models.knowledge import Knowledge
from bisheng.knowledge.domain.models.knowledge_document import KnowledgeDocument
from bisheng.knowledge.domain.models.knowledge_document_version import KnowledgeDocumentVersion
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile
from bisheng.knowledge.domain.models.knowledge_operation_plan import KnowledgeOperationPlan
from bisheng.knowledge.domain.models.knowledge_space_delete_job import KnowledgeSpaceDeleteJob
from bisheng.knowledge.domain.repositories.implementations.knowledge_document_repository_impl import (
    KnowledgeDocumentRepositoryImpl,
)
from bisheng.knowledge.domain.repositories.implementations.knowledge_document_version_repository_impl import (
    KnowledgeDocumentVersionRepositoryImpl,
)
from bisheng.knowledge.domain.repositories.implementations.knowledge_file_repository_impl import (
    KnowledgeFileRepositoryImpl,
)
from bisheng.knowledge.domain.schemas.processing_job import ProcessingCreateRequest
from bisheng.knowledge.domain.services.knowledge_version_service import KnowledgeVersionService
from bisheng.permission.domain.models import ResourcePermissionMode
from test.knowledge_unification import test_kn_space_reference_lifecycle as native


@pytest.fixture
def enable_switch(monkeypatch):
    from bisheng.knowledge.domain.services import knowledge_version_service as kvs_mod

    mock_settings = MagicMock()
    conf = MagicMock()
    conf.version_management.enabled = True
    mock_settings.async_get_knowledge = AsyncMock(return_value=conf)
    monkeypatch.setattr(kvs_mod, "bisheng_settings", mock_settings)


async def _seed_two_version_doc(session):
    session.add(Knowledge(id=1, name="space1", type=3, user_id=1))
    session.add(KnowledgeFile(id=100, knowledge_id=1, file_name="v1.pdf", file_type=1, status=2))
    session.add(KnowledgeFile(id=101, knowledge_id=1, file_name="v2.pdf", file_type=1, status=2))
    await session.commit()
    doc = KnowledgeDocument(knowledge_id=1)
    session.add(doc)
    await session.commit()
    await session.refresh(doc)
    v1 = KnowledgeDocumentVersion(document_id=doc.id, knowledge_file_id=100, version_no=1, is_primary=False)
    v2 = KnowledgeDocumentVersion(document_id=doc.id, knowledge_file_id=101, version_no=2, is_primary=True)
    session.add_all([v1, v2])
    await session.commit()
    await session.refresh(v1)
    await session.refresh(v2)
    doc.primary_version_id = v2.id
    session.add(doc)
    await session.commit()
    return doc, v1, v2


def _build_svc(session):
    return KnowledgeVersionService(
        request=MagicMock(),
        login_user=MagicMock(),
        doc_repo=KnowledgeDocumentRepositoryImpl(session),
        version_repo=KnowledgeDocumentVersionRepositoryImpl(session),
        knowledge_file_repo=KnowledgeFileRepositoryImpl(session),
    )


@pytest.mark.asyncio
async def test_delete_history_removes_version_and_file(deletion_case):
    case = deletion_case
    row = await case.seed(
        file_id=100, version_id=1, document_id=1, primary_file_id=101, primary_version_id=2, space_id=1
    )
    result = await case.service.delete_version(version_id=row.version_id)
    assert result.deleted_version_no == 1 and result.document_id == row.document_id
    await assert_history_only_removed(case, row)


@pytest.mark.asyncio
async def test_delete_primary_is_rejected(enable_switch, async_db_session, monkeypatch):
    _doc, _v1, v2 = await _seed_two_version_doc(async_db_session)
    monkeypatch.setattr(
        "bisheng.knowledge.domain.services.knowledge_audit_telemetry_service."
        "KnowledgeAuditTelemetryService.audit_delete_file_version",
        MagicMock(return_value=None),
    )
    svc = _build_svc(async_db_session)
    with pytest.raises(HTTPException) as ctx:
        await svc.delete_version(version_id=v2.id)
    assert ctx.value.status_code == 409


@pytest.mark.asyncio
async def test_delete_404_when_version_not_found(enable_switch, async_db_session):
    svc = _build_svc(async_db_session)
    with pytest.raises(HTTPException) as ctx:
        await svc.delete_version(version_id=9999)
    assert ctx.value.status_code == 404


@pytest.mark.asyncio
async def test_delete_rejected_when_switch_off(async_db_session, monkeypatch):
    from bisheng.knowledge.domain.services import knowledge_version_service as kvs_mod

    mock_settings = MagicMock()
    conf = MagicMock()
    conf.version_management.enabled = False
    mock_settings.async_get_knowledge = AsyncMock(return_value=conf)
    monkeypatch.setattr(kvs_mod, "bisheng_settings", mock_settings)
    svc = _build_svc(async_db_session)
    with pytest.raises(HTTPException) as ctx:
        await svc.delete_version(version_id=1)
    assert ctx.value.status_code == 403


# Real deletion application, SQL cutover/Plan/TargetOwner and F048 journals;
# only external object/vector transports and authentication/Coverage are isolated.


store, tenant, business = native.store, native.tenant, native.business
consumer, deletion_consumer = native.consumer, native.deletion_consumer


@pytest.fixture
async def deletion_case(deletion_consumer, enable_switch, monkeypatch):
    context, _space_service, _adapter = deletion_consumer
    case = SimpleNamespace(context=context, app=context.deletion, fail=None, io=[], primary_id=None)
    # The old repository constructors take a concrete native Session. Keep
    # it alive only for their public pre-read; it never owns deletion writes.
    session = AsyncSession(context.engine, expire_on_commit=False)
    svc = KnowledgeVersionService(
        request=None,
        login_user=context.user,
        doc_repo=KnowledgeDocumentRepositoryImpl(session),
        version_repo=KnowledgeDocumentVersionRepositoryImpl(session),
        knowledge_file_repo=KnowledgeFileRepositoryImpl(session),
    )
    svc.deletion_application_factory = lambda: case.app
    case.service = svc
    monkeypatch.setattr(
        "bisheng.knowledge.domain.services.knowledge_audit_telemetry_service.KnowledgeAuditTelemetryService.audit_delete_file_version",
        MagicMock(),
    )

    async def seed(
        *,
        file_id,
        version_id,
        document_id,
        version_no=1,
        space_id=5,
        primary_file_id=None,
        primary_version_id=None,
        root_exists=True,
    ):
        primary_file_id = primary_file_id or file_id + 1000
        primary_version_id = primary_version_id or version_id + 1000
        async with context.sessions() as db, db.begin():
            if root_exists:
                await KnowledgeModelReferenceApplication.acreate(
                    db,
                    Knowledge(
                        id=space_id,
                        tenant_id=101,
                        user_id=7,
                        name="history space",
                        type=3,
                        state=4,
                        model="11",
                        index_name="idx-history",
                        collection_name="col-history",
                    ),
                    login_user=context.user,
                    project_created=AsyncMock(),
                )
            db.add_all(
                [
                    KnowledgeFile(
                        id=file_id,
                        tenant_id=101,
                        knowledge_id=space_id,
                        file_name="history.pdf",
                        file_type=1,
                        status=2,
                        object_name=f"original/{file_id}.txt",
                        preview_file_object_name=f"preview/{file_id}.txt",
                    ),
                    KnowledgeFile(
                        id=primary_file_id,
                        tenant_id=101,
                        knowledge_id=space_id,
                        file_name="primary.pdf",
                        file_type=1,
                        status=2,
                    ),
                    KnowledgeDocument(id=document_id, knowledge_id=space_id, primary_version_id=primary_version_id),
                    KnowledgeDocumentVersion(
                        id=version_id,
                        document_id=document_id,
                        knowledge_file_id=file_id,
                        version_no=version_no,
                        is_primary=False,
                    ),
                    KnowledgeDocumentVersion(
                        id=primary_version_id,
                        document_id=document_id,
                        knowledge_file_id=primary_file_id,
                        version_no=version_no + 1,
                        is_primary=True,
                    ),
                    ResourcePermissionMode(
                        id=10,
                        tenant_id=101,
                        resource_type="knowledge_file",
                        resource_id=str(file_id),
                        mode="INHERIT",
                        parent_type="knowledge_space",
                        parent_id=str(space_id),
                        version=1,
                        projection_state="CURRENT",
                    ),
                ]
            )
        case.primary_id = primary_file_id
        context.transport.present.update(
            (subject, "permission_enabled", f"knowledge_file:{file_id}") for subject in native.TECHNICAL_MARKER_SUBJECTS
        )
        context.objects.clear()
        context.objects.update({f"original/{file_id}.txt", f"preview/{file_id}.txt"})
        context.vectors.es_ids = {file_id, primary_file_id}
        context.vectors.milvus_ids = {file_id, primary_file_id}
        return SimpleNamespace(
            file_id=file_id,
            version_id=version_id,
            document_id=document_id,
            version_no=version_no,
            space_id=space_id,
            primary_file_id=primary_file_id,
            primary_version_id=primary_version_id,
        )

    case.seed = seed
    # Native purge_step is retained. Its external transports model only the
    # selected file IDs, so the current primary's index entries cannot disappear.
    from bisheng.core.storage.minio import minio_manager
    from bisheng.knowledge.domain import knowledge_rag

    async def remove(*, bucket_name, object_name):
        case.io.append(("minio", object_name))
        if case.fail == "minio":
            raise OSError("MinIO unavailable")
        context.objects.discard(object_name)

    storage = SimpleNamespace(
        bucket="bisheng",
        remove_object=remove,
        object_exists=AsyncMock(side_effect=lambda **kw: kw["object_name"] in context.objects),
    )
    monkeypatch.setattr(minio_manager, "get_minio_storage", AsyncMock(return_value=storage))

    class Indices:
        def exists(self, **kw):
            return True

        def refresh(self, **kw):
            return None

    class Client:
        indices = Indices()

        def delete_by_query(self, **kw):
            case.io.append(("es", tuple(kw["query"]["terms"]["metadata.document_id"])))
            if case.fail == "es":
                raise RuntimeError("ES unavailable")
            context.vectors.es_ids.difference_update(kw["query"]["terms"]["metadata.document_id"])
            return {"failures": []}

        def count(self, **kw):
            return {"count": len(context.vectors.es_ids & set(kw["body"]["query"]["terms"]["metadata.document_id"]))}

    class Collection:
        def delete(self, expr, **kw):
            import ast

            ids = ast.literal_eval(expr.split(" in ", 1)[1])
            case.io.append(("milvus", tuple(ids)))
            context.vectors.milvus_ids.difference_update(ids)

        def flush(self, **kw):
            return None

        def query(self, expr, **kw):
            import ast

            ids = ast.literal_eval(expr.split(" in ", 1)[1])
            return [{"count(*)": len(context.vectors.milvus_ids & set(ids))}]

    monkeypatch.setattr(
        knowledge_rag.ElasticsearchFactory,
        "init_vectorstore_sync",
        MagicMock(return_value=SimpleNamespace(client=Client())),
    )
    monkeypatch.setattr(
        knowledge_rag.MilvusFactory,
        "init_vectorstore",
        MagicMock(return_value=SimpleNamespace(col=Collection(), alias="test")),
    )
    try:
        yield case
    finally:
        await session.close()


async def pending(case):
    async with case.context.sessions() as session:
        job = (await session.execute(sa.select(KnowledgeSpaceDeleteJob))).scalar_one()
        plan = await session.get(KnowledgeOperationPlan, job.id)
        return job, ProcessingCreateRequest(
            confirmation_id=plan.id, plan_digest=plan.plan_digest, idempotency_key=f"delete:{plan.id}"
        )


async def assert_history_only_removed(case, row):
    async with case.context.sessions() as session:
        assert await session.get(KnowledgeFile, row.file_id) is None
        assert await session.get(KnowledgeDocumentVersion, row.version_id) is None
        assert (await session.get(KnowledgeDocument, row.document_id)).primary_version_id == row.primary_version_id
        assert (
            await session.get(KnowledgeDocumentVersion, row.primary_version_id)
        ).knowledge_file_id == row.primary_file_id
        assert await session.get(KnowledgeFile, row.primary_file_id) is not None
    assert case.context.vectors.es_ids == case.context.vectors.milvus_ids == {row.primary_file_id}
    assert not case.context.objects


@pytest.mark.asyncio
async def test_delete_version_calls_vector_and_minio_cleanup(deletion_case):
    case = deletion_case
    row = await case.seed(file_id=10, version_id=42, document_id=7, version_no=2)
    result = await case.service.delete_version(version_id=42)
    assert result.deleted_version_no == 2 and result.document_id == 7
    await assert_history_only_removed(case, row)
    assert [step for kind, step in case.context.order if kind == "purge"] == ["minio", "es", "milvus"]
    assert any(kind == "fga" for kind, _ in case.context.order)
    assert case.context.order[0][0] == "fga"
    assert case.context.projected_snapshots
    assert any(x["id"] == 10 for x in case.context.projected_snapshots[0]["knowledgefile"])


@pytest.mark.asyncio
async def test_delete_version_vector_failure_still_succeeds_and_calls_minio(deletion_case):
    # Frozen R3 semantics: SQL may already be finalized; failed external cleanup
    # remains durable pending, then the SAME Plan/job resumes to actual success.
    case = deletion_case
    row = await case.seed(file_id=11, version_id=43, document_id=8, version_no=3)
    case.fail = "es"
    with pytest.raises(RuntimeError, match="ES unavailable"):
        await case.service.delete_version(version_id=43)
    job, command = await pending(case)
    assert job.state == "PENDING" and job.business_phase == "finalized"
    assert job.completed_steps == ["fga", "minio"] and not case.context.objects
    minio_calls = [x for x in case.io if x[0] == "minio"]
    case.fail = None
    assert (await case.app.aconfirm(identity=case.context.user, space_id=5, request=command))["state"] == "succeeded"
    assert [x for x in case.io if x[0] == "minio"] == minio_calls
    await assert_history_only_removed(case, row)


@pytest.mark.asyncio
async def test_delete_version_minio_failure_still_succeeds(deletion_case):
    case = deletion_case
    row = await case.seed(file_id=12, version_id=44, document_id=9, version_no=4)
    case.fail = "minio"
    with pytest.raises(OSError, match="MinIO unavailable"):
        await case.service.delete_version(version_id=44)
    job, command = await pending(case)
    assert job.state == "PENDING" and job.business_phase == "finalized"
    assert job.completed_steps == ["fga"] and case.context.objects
    assert not any(kind in {"es", "milvus"} for kind, _ in case.io)
    case.fail = None
    assert (await case.app.aconfirm(identity=case.context.user, space_id=5, request=command))["state"] == "succeeded"
    await assert_history_only_removed(case, row)


@pytest.mark.asyncio
async def test_delete_version_knowledge_none_skips_vector_but_runs_minio(deletion_case):
    # Missing Root is a blocker; this protocol is not orphan garbage collection.
    case = deletion_case
    row = await case.seed(file_id=13, version_id=45, document_id=10, version_no=5, space_id=99, root_exists=False)
    before = native.state(case.context)
    with pytest.raises(KnowledgeOperationPlanConflictError):
        await case.service.delete_version(version_id=45)
    assert native.state(case.context) == before and not case.io and not case.context.order
    async with case.context.sessions() as session:
        assert await session.get(KnowledgeFile, row.file_id) is not None
        assert await session.get(KnowledgeDocumentVersion, row.version_id) is not None
        assert not (await session.execute(sa.select(KnowledgeSpaceDeleteJob))).scalars().all()


@pytest.mark.asyncio
async def test_projection_failure_keeps_original_history_and_remains_fail_closed(deletion_case):
    case = deletion_case
    row = await case.seed(file_id=14, version_id=46, document_id=11)
    case.context.transport.fail = True
    with pytest.raises(PermissionProjectionFailedError):
        await case.service.delete_version(version_id=46)
    job, command = await pending(case)
    assert job.business_phase != "finalized" and not case.io
    async with case.context.sessions() as session:
        assert await session.get(KnowledgeFile, row.file_id) is not None
        assert await session.get(KnowledgeDocumentVersion, row.version_id) is not None
    case.context.transport.fail = False
    # A healthy transport alone cannot clear the existing FAILED_CLOSED journal.
    with pytest.raises(PermissionProjectionFailedError, match="fail closed"):
        await case.app.aconfirm(identity=case.context.user, space_id=5, request=command)
    async with case.context.sessions() as session:
        assert await session.get(KnowledgeFile, row.file_id) is not None
        assert await session.get(KnowledgeDocumentVersion, row.version_id) is not None
    assert not case.io

"""Native composition reused by the original move behavior matrix."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
import sqlalchemy as sa

from bisheng.common.errcode.knowledge_space import SpacePermissionDeniedError
from bisheng.core.context.tenant import bypass_tenant_filter
from bisheng.knowledge.application import move_application, move_processing_admission
from bisheng.knowledge.domain.models.knowledge import Knowledge
from bisheng.knowledge.domain.models.knowledge_document import KnowledgeDocument
from bisheng.knowledge.domain.models.knowledge_document_version import KnowledgeDocumentVersion
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile
from bisheng.knowledge.domain.services.knowledge_space_service import KnowledgeSpaceService
from bisheng.permission.domain.models import ResourcePermissionMode
from bisheng.permission.domain.schemas import VerifiedPermissionTarget
from bisheng.permission.domain.services.projection_service import projection_state_expectations
from bisheng.permission.domain.services.resource_lifecycle_policy import build_move_plan
from bisheng.resource_reference.domain.models.business_reference_set import BusinessReferenceSet
from bisheng.resource_reference.domain.models.business_resource_reference import BusinessResourceReference
from test.knowledge_unification import test_move_processing_admission as admission
from test.knowledge_unification import test_move_processing_owner as base
from test.knowledge_unification.test_processing_identity import request_context

store, tenant, moving, accepted, application = base.store, base.tenant, base.moving, base.accepted, base.application


@pytest.fixture
async def legacy_move(application, monkeypatch):
    app = application
    await admission.reset_to_before(app)
    async with app.built.sessions() as session, session.begin():
        for model in (
            BusinessResourceReference,
            BusinessReferenceSet,
            KnowledgeDocumentVersion,
            KnowledgeDocument,
            KnowledgeFile,
            ResourcePermissionMode,
        ):
            await session.execute(sa.delete(model.__table__))
    context = SimpleNamespace(app=app, service=None)
    app.owner.chat_rehome = lambda **kwargs: context.service._dispatch_knowledge_chat_rehome(**kwargs)

    async def actions(identity, *, resource_type, resource_ids, actions):
        return {
            str(ident): frozenset(await context.service._get_effective_actions(resource_type, ident))
            for ident in resource_ids
        }

    async def require(identity, *, resource_type, resource_id, action, **kwargs):
        codes = await context.service._get_effective_actions(resource_type, int(resource_id))
        if action not in codes:
            raise SpacePermissionDeniedError()

    monkeypatch.setattr(move_application, "batch_check_business_actions", actions)
    monkeypatch.setattr(move_processing_admission, "require_business_action", require)
    with request_context(app.actor):
        yield context


def service(context):
    app = context.app
    result = KnowledgeSpaceService(None, app.current)
    result._get_effective_actions = AsyncMock(return_value={"move", "visible", "upload_file"})
    result._require_read_permission = AsyncMock()
    result._replace_resource_parent_tuple = AsyncMock()
    result._dispatch_knowledge_chat_rehome = MagicMock(return_value=1)
    outer = move_application.KnowledgeMoveApplication(owner=app.owner, max_folder_level=9)

    async def factory():
        return outer

    result.move_application_factory = factory
    context.service = result
    return result


async def add_mode(session, row, context):
    kind = "folder" if row.file_type == 0 else "knowledge_file"
    path = tuple(int(value) for value in (row.file_level_path or "").split("/") if value)
    parent = ("folder", str(path[-1])) if path else ("knowledge_space", str(row.knowledge_id))
    mode = ResourcePermissionMode(
        id=row.id,
        tenant_id=101,
        resource_type=kind,
        resource_id=str(row.id),
        mode="INHERIT",
        version=4,
        parent_type=parent[0],
        parent_id=parent[1],
        projection_state="CURRENT",
    )
    session.add(mode)
    await session.commit()
    target = VerifiedPermissionTarget.from_business_service(
        tenant_id=101,
        resource_type=kind,
        resource_id=str(row.id),
        resource_version=4,
        context_version="original-move-fixture",
        parent_type=parent[0],
        parent_id=parent[1],
    )
    plan = build_move_plan(
        target,
        old_parent=parent,
        new_parent=("knowledge_space", "9999"),
        mode="INHERIT",
        store_id="actual-store",
        model_id="actual-model",
        operator_id=7,
        idempotency_key=f"original-move-fixture:{kind}:{row.id}",
    )
    transport = context.app.built.bridge.components.projection._fga
    transport.present.update(
        key for key, present in projection_state_expectations(plan.deltas, after=False).items() if present
    )


def confirmation(review):
    from bisheng.knowledge.domain.schemas.processing_job import ProcessingCreateRequest

    values = review if isinstance(review, dict) else review.model_dump()
    return ProcessingCreateRequest(
        confirmation_id=values["confirmation_id"],
        plan_digest=values["plan_digest"],
        idempotency_key=values["confirmation_id"],
    )


def install_empty_index_transports(context, monkeypatch):
    """Legacy ownership fixtures have no index rows; still run the actual adapter."""
    from bisheng.worker.knowledge import move_worker
    from test.knowledge_unification.test_move_worker import NativeCollection, NativeES, NativeIterator, response

    class Collection(NativeCollection):
        def query_iterator(self, *, batch_size, limit, expr, output_fields):
            assert batch_size == 1000 and limit == -1 and expr.startswith("document_id == ")
            assert output_fields == [field.name for field in self.schema.fields]
            return NativeIterator([], self.events)

        def delete(self, expr):
            assert expr.startswith("document_id == ")
            return SimpleNamespace(delete_count=0)

    class ES(NativeES):
        async def search(self, *, index, body=None, query=None, **kwargs):
            assert set((body or {"query": query})["query"]["term"]) == {"metadata.document_id"}
            return response(
                {
                    "hits": {"hits": [], "total": {"value": 0, "relation": "eq"}},
                    "_shards": {"failed": 0},
                    "timed_out": False,
                }
            )

        async def delete_by_query(self, *, index, body=None, query=None, refresh):
            assert refresh and set((body or {"query": query})["query"]["term"]) == {"metadata.document_id"}
            return response({"total": 0, "deleted": 0, "version_conflicts": 0, "timed_out": False, "failures": []})

    source_es, target_es = ES("source", [], []), ES("target", [], [])
    source_mv, target_mv = Collection([]), Collection([])

    async def vector(user_id, *, knowledge, **kwargs):
        assert user_id == 7 and not any(session.in_transaction() for session in context.app.sessions_seen)
        return SimpleNamespace(col=source_mv if knowledge.id == 1 else target_mv, embedding_func=SimpleNamespace())

    async def elasticsearch(*, knowledge, **kwargs):
        assert not any(session.in_transaction() for session in context.app.sessions_seen)
        return source_es if knowledge.id == 1 else target_es

    monkeypatch.setattr(move_worker.KnowledgeRag, "init_knowledge_milvus_vectorstore", vector)
    monkeypatch.setattr(move_worker.KnowledgeRag, "init_knowledge_es_vectorstore", elasticsearch)


async def run_accepted(context, accepted, monkeypatch):
    from bisheng.core.context.background_execution import get_current_background_task
    from bisheng.knowledge.domain.models.knowledge_processing_job import KnowledgeProcessingJob
    from bisheng.worker.knowledge.move_jobs import execute_move_job

    install_empty_index_transports(context, monkeypatch)
    async with context.app.built.sessions() as session:
        revision = (await session.get(KnowledgeProcessingJob, accepted.job_id)).revision
    result = await execute_move_job(
        accepted.job_id,
        revision,
        owner=context.app.owner,
        proof=get_current_background_task(),
    )
    assert result == {"job_id": accepted.job_id, "state": "succeeded"}
    return result


@pytest.fixture
async def busy_move(legacy_move):
    context = legacy_move
    async with context.app.built.sessions() as session:
        with bypass_tenant_filter():
            await session.execute(sa.delete(Knowledge).where(Knowledge.id == 20))
        session.add_all(
            [
                Knowledge(id=19, tenant_id=101, user_id=7, name="busy", type=3, state=3),
                Knowledge(id=20, tenant_id=101, user_id=7, name="idle", type=3, state=1),
                KnowledgeFile(
                    id=150,
                    tenant_id=101,
                    knowledge_id=19,
                    user_id=7,
                    file_name="folder",
                    file_type=0,
                    file_level_path="",
                    level=0,
                ),
            ]
        )
        for file_id, space_id in ((101, 19), (201, 20)):
            session.add(
                KnowledgeFile(
                    id=file_id,
                    tenant_id=101,
                    knowledge_id=space_id,
                    user_id=7,
                    file_name=str(file_id),
                    file_type=1,
                    status=2,
                    file_level_path="",
                    level=0,
                )
            )
            session.add(
                KnowledgeDocument(
                    id=file_id + 1000,
                    knowledge_id=space_id,
                    primary_version_id=file_id + 2000,
                    file_level_path="",
                    level=0,
                )
            )
            session.add(
                KnowledgeDocumentVersion(
                    id=file_id + 2000,
                    document_id=file_id + 1000,
                    knowledge_file_id=file_id,
                    version_no=1,
                    is_primary=True,
                )
            )
        await session.commit()
    context.service = service(context)
    context.mutations = []

    def mutated(connection, cursor, statement, params, execution, many):
        if execution.isinsert or execution.isupdate or execution.isdelete:
            # A non-executable review may freeze its Plan, but it must never
            # create a Job, project permissions or mutate business ownership.
            if "knowledge_operation_plan" not in statement:
                context.mutations.append(statement)

    async with context.app.built.sessions() as session:
        engine = session.bind.sync_engine
    sa.event.listen(engine, "before_cursor_execute", mutated)
    try:
        yield context
    finally:
        sa.event.remove(engine, "before_cursor_execute", mutated)

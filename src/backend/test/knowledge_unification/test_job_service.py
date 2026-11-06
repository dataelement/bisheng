"""T063: actual processing acceptance/confirmation, queries and recovery.

Real Owner, SourceRead, Model/R2, scope, plans and job repositories are used.
The execution-capability set is an assembly boundary (dispatcher tests cover
its actual handler); only FGA transports are replaced in this use-case test.
"""

from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlmodel import select

from bisheng.common.errcode.http_error import UnAuthorizedError
from bisheng.common.errcode.knowledge import (
    KnowledgeIdempotencyConflictError,
    KnowledgeOperationPlanChangedError,
    KnowledgeOperationPlanConflictError,
    KnowledgeProcessingConflictError,
    KnowledgeProcessingJobNotFoundError,
    KnowledgeProcessingObsoleteError,
    ResourceReferenceInvalidError,
)
from bisheng.core.database import tenant_filter
from bisheng.knowledge.domain.models.knowledge_document import KnowledgeDocument
from bisheng.knowledge.domain.models.knowledge_document_version import KnowledgeDocumentVersion
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile
from bisheng.knowledge.domain.models.knowledge_operation_plan import KnowledgeOperationPlan
from bisheng.knowledge.domain.models.knowledge_processing_item import KnowledgeProcessingItem
from bisheng.knowledge.domain.models.knowledge_processing_job import KnowledgeProcessingJob
from bisheng.knowledge.domain.models.knowledge_processing_retry import KnowledgeProcessingRetryReceipt
from bisheng.knowledge.domain.schemas.processing_job import (
    ProcessingCreateRequest,
    ProcessingPrecheckRequest,
    ProcessingRetryRequest,
)
from bisheng.knowledge.domain.services import processing_job_service as module
from bisheng.knowledge.domain.services.processing_job_service import ProcessingJobService
from test.knowledge_unification import test_processing_owner as fixtures
from test.knowledge_unification.test_kn_model_bindings import state as business_state

store = fixtures.store
tenant = fixtures.tenant
business = fixtures.business
admission = fixtures.admission
processing = fixtures.processing


@pytest.fixture
async def application(processing, monkeypatch):
    context, owner = processing
    for model in (
        KnowledgeFile,
        KnowledgeDocument,
        KnowledgeDocumentVersion,
        KnowledgeProcessingJob,
        KnowledgeProcessingItem,
        KnowledgeProcessingRetryReceipt,
        KnowledgeOperationPlan,
    ):
        model.__table__.create(context.sync, checkfirst=True)
    names = tenant_filter._tenant_aware_tables | {
        "knowledgefile",
        "knowledge_processing_job",
        "knowledge_processing_item",
        "knowledge_processing_retry_receipt",
        "knowledge_operation_plan",
    }
    monkeypatch.setattr(tenant_filter, "_tenant_aware_tables", names)
    context.user._runtime_credential_reference = {
        "kind": "web_session",
        "user_id": 7,
        "tenant_id": 101,
        "token_version": 0,
        "expires_at": (datetime.now() + timedelta(hours=1)).isoformat(),
    }
    async with context.sessions() as session:
        session.add_all(
            [
                KnowledgeFile(
                    id=81, tenant_id=101, knowledge_id=40, file_name="visible", split_rule='{"original":"kept"}'
                ),
                KnowledgeFile(id=82, tenant_id=101, knowledge_id=40, file_name="hidden secret"),
                KnowledgeDocument(id=80, knowledge_id=40, primary_version_id=181),
                KnowledgeDocumentVersion(id=181, document_id=80, knowledge_file_id=81, version_no=1, is_primary=True),
                KnowledgeDocumentVersion(id=182, document_id=80, knowledge_file_id=82, version_no=2, is_primary=False),
            ]
        )
        await session.commit()
    auth = AsyncMock()
    visibility = SimpleNamespace(ids={81})

    async def visible(identity, *, resource_ids, **kwargs):
        return {
            str(value): frozenset({"visible"}) if int(value) in visibility.ids else frozenset()
            for value in resource_ids
        }

    monkeypatch.setattr(module, "require_business_action", auth)
    monkeypatch.setattr(module, "batch_check_business_actions", AsyncMock(side_effect=visible))
    app = ProcessingJobService(owner=owner, available_kinds=frozenset({"embedding_rebuild"}))
    return SimpleNamespace(context=context, owner=owner, app=app, auth=auth, visibility=visibility)


def request(model=None):
    return ProcessingPrecheckRequest(
        kind="embedding_rebuild", parameters={} if model is None else {"embedding_model_id": model}
    )


async def precheck(app, session, change=None):
    return await app.app.aprecheck(session, 40, change or request(), identity=app.context.user, entry_kind="web")


async def create(app, session, plan, key="one"):
    command = ProcessingCreateRequest(
        idempotency_key=key, confirmation_id=plan.confirmation_id, plan_digest=plan.plan_digest
    )
    return await app.app.acreate(session, 40, command, identity=app.context.user, entry_kind="web")


async def test_precheck_changes_only_plan_and_never_exposes_hidden_file_identity(application):
    app = application
    before = business_state(app.context)
    async with app.context.sessions() as session:
        plan = await precheck(app, session)
        assert plan.can_execute and plan.check_complete
        assert all(item.id != 82 for item in plan.valid_items)
        assert "hidden secret" not in plan.model_dump_json()
        assert not (await session.exec(select(KnowledgeProcessingJob))).all()
        await session.commit()
    assert business_state(app.context) == before


async def test_actual_acceptance_is_atomic_with_owner_plan_items_and_dispatch_intent(application):
    app = application
    before = business_state(app.context)
    async with app.context.sessions() as session:
        plan = await precheck(app, session)
        result = await create(app, session, plan)
        assert result.state == "accepted" and result.accepted and not result.reused
        job = await app.owner.jobs.aget(session, result.job_id)
        assert job.pending_dispatch and job.pending_count == job.total_count == 2
        assert job.accepted_model_config_revision == 1 and job.expected_model_config_revision == 1
        stored = await session.get(KnowledgeOperationPlan, plan.confirmation_id)
        assert stored.operation_id == job.id
        assert len((await session.exec(select(KnowledgeProcessingItem))).all()) == 2
        await session.rollback()
    assert business_state(app.context) == before


async def test_same_request_replays_original_job_without_replanning_or_duplicate_items(application):
    app = application
    async with app.context.sessions() as session:
        plan = await precheck(app, session)
        first = await create(app, session, plan)
        await session.commit()
    app.auth.reset_mock()
    async with app.context.sessions() as session:
        again = await create(app, session, plan)
        assert again.job_id == first.job_id and again.reused
        assert len((await session.exec(select(KnowledgeProcessingItem))).all()) == 2
        with pytest.raises(KnowledgeIdempotencyConflictError):
            await create(app, session, plan, key="other")
    app.auth.assert_awaited()
    app.auth.side_effect = UnAuthorizedError()
    async with app.context.sessions() as session:
        with pytest.raises(UnAuthorizedError):
            await create(app, session, plan)


async def test_same_key_different_frozen_plan_is_idempotency_error_before_active_operation_error(application):
    app = application
    async with app.context.sessions() as session:
        first = await precheck(app, session)
        second = await precheck(app, session, request(12))
        await create(app, session, first)
        await session.commit()
    async with app.context.sessions() as session:
        with pytest.raises(KnowledgeIdempotencyConflictError):
            await create(app, session, second)


async def test_scope_drift_after_confirmation_rolls_back_all_new_model_and_job_writes(application):
    app = application
    async with app.context.sessions() as session:
        plan = await precheck(app, session)
        await session.commit()
    async with app.context.sessions() as session:
        physical = await session.get(KnowledgeFile, 81)
        physical.file_name = "changed after confirmation"
        await session.commit()
    before = business_state(app.context)
    async with app.context.sessions() as session:
        with pytest.raises((KnowledgeOperationPlanChangedError, KnowledgeOperationPlanConflictError)):
            await create(app, session, plan)
        await session.rollback()
    assert business_state(app.context) == before


async def test_query_filters_current_file_scope_before_pagination_and_summary_hides_it(application):
    app = application
    async with app.context.sessions() as session:
        plan = await precheck(app, session)
        created = await create(app, session, plan)
        detail = await app.app.aget(session, 40, created.job_id, identity=app.context.user)
        assert detail.hidden_item_count == 1 and detail.total_count == 2
        items = await app.app.alist_items(session, 40, created.job_id, identity=app.context.user, page=1, page_size=1)
        assert items.total == 1 and items.data[0].file_id == 81
        app.visibility.ids = set()
        assert (
            await app.app.alist_items(session, 40, created.job_id, identity=app.context.user, page=1, page_size=10)
        ).total == 0
        assert (await app.app.aget(session, 40, created.job_id, identity=app.context.user)).hidden_item_count == 2
        with pytest.raises(KnowledgeProcessingJobNotFoundError):
            await app.app.aget(session, 10, created.job_id, identity=app.context.user)


async def test_retry_persists_obsolete_without_raising_and_losing_state(application):
    app = application
    async with app.context.sessions() as session:
        plan = await precheck(app, session)
        created = await create(app, session, plan)
        job = await app.owner.jobs.aget(session, created.job_id)
        # Model Owner accepted R=1. A job expecting an older R is a stored old
        # command; the current business source remains real and valid.
        job.expected_model_config_revision = 0
        job.state = "failed"
        await session.flush()
        result = await app.app.aretry(
            session,
            40,
            job.id,
            ProcessingRetryRequest(idempotency_key="retry", expected_job_revision=job.revision),
            identity=app.context.user,
            entry_kind="web",
        )
        assert result.data is None and isinstance(result.error, KnowledgeProcessingObsoleteError)
        await session.commit()
    async with app.context.sessions() as session:
        assert (await app.owner.jobs.aget(session, created.job_id)).state == "obsolete"


async def test_unassembled_kind_is_never_accepted_and_invalid_model_has_no_fallback(application):
    app = application
    unavailable = ProcessingJobService(owner=app.owner)
    async with app.context.sessions() as session:
        with pytest.raises(KnowledgeProcessingConflictError):
            await unavailable.aprecheck(session, 40, request(), identity=app.context.user, entry_kind="web")
        with pytest.raises(ResourceReferenceInvalidError):
            await precheck(app, session, request(999))
        assert not (await session.exec(select(KnowledgeProcessingJob))).all()

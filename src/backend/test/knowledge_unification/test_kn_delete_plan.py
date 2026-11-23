"""Local deletion business wiring; only external auth/catalog/purge IO is isolated."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from bisheng.common.errcode.knowledge import (
    KnowledgeOperationPlanConflictError,
    ResourceReferenceInvalidError,
)
from bisheng.knowledge.application import knowledge_deletion as module
from bisheng.knowledge.application import processing_identity
from bisheng.knowledge.domain.models.knowledge import Knowledge
from bisheng.knowledge.domain.models.knowledge_operation_plan import KnowledgeOperationPlan
from bisheng.knowledge.domain.models.knowledge_processing_item import KnowledgeProcessingItem
from bisheng.knowledge.domain.models.knowledge_processing_job import KnowledgeProcessingJob
from bisheng.knowledge.domain.models.knowledge_space_delete_job import KnowledgeSpaceDeleteJob
from bisheng.knowledge.domain.schemas.processing_job import ProcessingCreateRequest
from bisheng.permission.domain.models import AuthorizationModelRelease, PermissionCatalogRelease
from test.knowledge_unification import test_kn_refs as native

deletion_tenant, db, context, service = native.deletion_tenant, native.db, native.context, native.service


@pytest.fixture
async def application(context, service, monkeypatch):
    from bisheng.knowledge.domain.models.knowledge_processing_fence import (
        KnowledgeProcessingArtifact,
        KnowledgeProcessingFence,
    )

    tables = (
        KnowledgeProcessingFence,
        KnowledgeProcessingArtifact,
        KnowledgeOperationPlan,
        KnowledgeProcessingJob,
        KnowledgeProcessingItem,
        AuthorizationModelRelease,
        PermissionCatalogRelease,
    )
    async with context.db.engine.begin() as connection:
        await connection.run_sync(
            lambda conn: Knowledge.metadata.create_all(conn, tables=[row.__table__ for row in tables])
        )
    async with context.db.sessions() as session, session.begin():
        session.add(
            AuthorizationModelRelease(
                id=1,
                environment="test",
                store_id="store",
                model_version="v1",
                model_id="model",
                model_checksum="a" * 64,
                required_relations_checksum="b" * 64,
                openfga_version="1",
                status="ACTIVE",
            )
        )
        session.add(
            PermissionCatalogRelease(
                id=1,
                release_key="catalog",
                version=1,
                status="CURRENT",
                required_authorization_model_release_id=1,
                draft_owner_id=7,
                idempotency_key="catalog",
                checksum="c" * 64,
            )
        )
    service.user._runtime_credential_reference = {
        "kind": "web_session",
        "user_id": 7,
        "tenant_id": 101,
        "token_version": service.user.token_version,
        "expires_at": (datetime.now(UTC) + timedelta(days=1)).isoformat(),
    }
    monkeypatch.setattr(processing_identity, "resolve_web_runtime_identity", AsyncMock(return_value=service.user))
    pin = SimpleNamespace(
        release_id=1,
        release_key="catalog",
        checksum="c" * 64,
        store_id="store",
        model_id="model",
        model_checksum="a" * 64,
    )
    runtime = SimpleNamespace(
        current_catalog=AsyncMock(return_value=pin),
        project_delete=AsyncMock(side_effect=AssertionError("empty clear must not project fake content")),
    )
    monkeypatch.setattr(module, "get_f048_runtime", AsyncMock(return_value=runtime))
    monkeypatch.setattr(module, "require_business_action", AsyncMock())
    monkeypatch.setattr(module.admission, "batch_check_business_actions", native.module.batch_check_business_actions)
    app = module.KnowledgeDeletionApplication(
        session_factory=context.db.sessions,
        coverage_factory=context.factory,
        runtime=service.runtime,
        reference_service=service,
        purge_step=AsyncMock(),
    )

    async def actions(*args, **kwargs):
        return await module.admission.batch_check_business_actions(*args, **kwargs)

    monkeypatch.setattr(module, "batch_check_business_actions", actions)
    app.user, app.permission_runtime = service.user, runtime
    app.permission_cleanup = AsyncMock()
    return app


async def test_empty_clear_completes_original_plan_job_and_preserves_space_and_model(application, context):
    plan = await application.aprecheck(identity=application.user, space_id=2, operation="knowledge_space_clear")
    assert plan.can_execute
    request = ProcessingCreateRequest(
        confirmation_id=plan.confirmation_id, plan_digest=plan.plan_digest, idempotency_key="same-clear"
    )
    result = await application.aconfirm(identity=application.user, space_id=2, request=request)
    assert result["state"] == "succeeded" and not result["accepted"]
    async with context.db.sessions() as session:
        root = await session.get(Knowledge, 2)
        job = await session.get(KnowledgeSpaceDeleteJob, plan.confirmation_id)
        assert root.model == "old-model" and root.type == 3
        assert job.business_phase == "finalized" and job.completed_steps == ["fga", "minio", "es", "milvus"]
    application.permission_runtime.project_delete.assert_not_awaited()


async def test_cleanup_failure_retries_same_committed_business_job_with_current_credential(application, context):
    calls, failed = [], False

    async def purge(step, job):
        nonlocal failed
        calls.append(step)
        if step == "es" and not failed:
            failed = True
            raise RuntimeError("external transport unavailable")

    application.purge_step = purge
    plan = await application.aprecheck(identity=application.user, space_id=2, operation="knowledge_space_clear")
    request = ProcessingCreateRequest(
        confirmation_id=plan.confirmation_id, plan_digest=plan.plan_digest, idempotency_key="same-after-failure"
    )
    with pytest.raises(RuntimeError, match="external transport unavailable"):
        await application.aconfirm(identity=application.user, space_id=2, request=request)
    async with context.db.sessions() as session:
        job = await session.get(KnowledgeSpaceDeleteJob, plan.confirmation_id)
        assert job.state == "PENDING" and job.business_phase == "finalized"
        assert job.completed_steps == ["fga", "minio"]
    application.user._runtime_credential_reference["expires_at"] = (datetime.now(UTC) + timedelta(days=2)).isoformat()
    assert (await application.aconfirm(identity=application.user, space_id=2, request=request))["state"] == "succeeded"
    assert calls.count("minio") == 1 and calls.count("es") == 2
    async with context.db.sessions() as session:
        assert len((await session.execute(select(KnowledgeSpaceDeleteJob))).scalars().all()) == 1


async def test_known_direct_reference_is_advisory_in_the_business_plan(application, context):
    await native.native.seed(context, (31, 101, "assistant", "configured", "current", "file"))
    plan = await application.aprecheck(
        identity=application.user, space_id=1, selections=native.native.selections(("knowledge_file", 31))
    )
    assert plan.can_execute
    async with context.db.sessions() as session:
        stored = await session.get(KnowledgeOperationPlan, plan.confirmation_id)
        assert stored.source_revisions.keys() == {"root"}
    with pytest.raises(ResourceReferenceInvalidError):
        await application.aprecheck(
            identity=application.user,
            space_id=1,
            selections=native.native.selections(("knowledge_file", 31)),
            force=True,
        )


async def test_mixed_permissions_hide_denied_dependency_and_require_fresh_consent_after_change(
    application, context, monkeypatch
):
    await native.native.seed(context, (31, 101, "assistant", "not-disclosed", "current", "file"))
    permitted = {40}

    async def actions(identity, *, resource_type, resource_ids, actions):
        return {str(ident): frozenset(actions) if ident in permitted else frozenset() for ident in resource_ids}

    monkeypatch.setattr(module.admission, "batch_check_business_actions", actions)
    selections = native.native.selections(("knowledge_file", 31), ("knowledge_file", 40))
    review = await application.aprecheck(identity=application.user, space_id=1, selections=selections)
    assert review.can_execute and review.requires_skip_confirmation
    assert [row.id for row in review.valid_items] == [40]
    assert [(row.id, row.reason, row.name) for row in review.invalid_items] == [(31, "no_permission", None)]
    assert not any(review.impact["source_counts"].values())
    assert not review.impact["source_page"]["data"]
    permitted.add(31)
    with pytest.raises(KnowledgeOperationPlanConflictError):
        await application.aconfirm(
            identity=application.user,
            space_id=1,
            request=ProcessingCreateRequest(
                confirmation_id=review.confirmation_id,
                plan_digest=review.plan_digest,
                idempotency_key="permission-change",
            ),
        )
    async with context.db.sessions() as session:
        assert not (await session.execute(select(KnowledgeSpaceDeleteJob))).scalars().all()


async def test_no_authorized_selection_is_non_executable_without_reading_dependency_facts(application, monkeypatch):
    async def deny(identity, *, resource_type, resource_ids, actions):
        return {str(ident): frozenset() for ident in resource_ids}

    monkeypatch.setattr(module.admission, "batch_check_business_actions", deny)
    inspection = AsyncMock(side_effect=AssertionError("denied selections must not disclose reference facts"))
    monkeypatch.setattr(application.references, "ainspect", inspection)
    selections = native.native.selections(("knowledge_file", 31))
    probe = await application.ainspect_selections(identity=application.user, space_id=1, selections=selections)
    assert probe == {"permitted_selection_count": 0}
    review = await application.aprecheck(identity=application.user, space_id=1, selections=selections)
    assert not review.can_execute and not review.valid_items
    assert review.invalid_items[0].reason == "no_permission" and review.invalid_items[0].name is None
    inspection.assert_not_awaited()


@pytest.mark.parametrize("status", [1, 5])
async def test_processing_file_executable_and_parse_progress_keeps_consent(application, context, status):
    from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile

    async with context.db.sessions() as session, session.begin():
        row = await session.get(KnowledgeFile, 40)
        row.status = status
    plan = await application.aprecheck(
        identity=application.user, space_id=1, selections=native.native.selections(("knowledge_file", 40))
    )
    assert plan.can_execute and not plan.invalid_items
    async with context.db.sessions() as session, session.begin():
        row = await session.get(KnowledgeFile, 40)
        row.status, row.thumbnails = 2, "new-thumbnail"
    async with context.db.sessions() as session, session.begin():
        saved = await application.execution.apeek_plan(session, plan.confirmation_id)
        await application._locked(session, saved)


async def test_rebuild_allows_space_delete_but_copy_stays_protected(application, context):
    from bisheng.common.errcode.knowledge import KnowledgeProcessingConflictError

    async with context.db.sessions() as session, session.begin():
        root = await session.get(Knowledge, 2)
        root.state = 3
        root.model_transition = {"operation_id": "obsolete-rebuild", "pending_model_id": "old-model"}
    plan = await application.aprecheck(identity=application.user, space_id=2, operation="knowledge_space_delete")
    assert plan.can_execute
    async with context.db.sessions() as session, session.begin():
        root = await session.get(Knowledge, 2)
        root.state, root.model_transition = 2, None
    with pytest.raises(KnowledgeProcessingConflictError):
        await application.aprecheck(identity=application.user, space_id=2, operation="knowledge_space_delete")


async def test_delete_confirmation_cancels_rebuild_and_dispatches_durable_cleanup(application, context, monkeypatch):
    from bisheng.knowledge.domain.services import knowledge_space_direct_delete_service as cleanup

    async with context.db.sessions() as session, session.begin():
        root = await session.get(Knowledge, 2)
        root.state = 3
        root.model_transition = {"operation_id": "rebuild", "pending_model_id": "old-model"}
        session.add(
            KnowledgeProcessingJob(
                id="cancel-rebuild",
                tenant_id=101,
                space_id=2,
                kind="embedding_rebuild",
                state="running",
                actor_user_id=7,
                idempotency_key="cancel-rebuild",
                request_hash="a" * 64,
                expected_model_config_revision=0,
                lease_token="old-lease",
                pending_dispatch=True,
            )
        )
    from bisheng.knowledge.domain.services.model_reference_extractor import KNOWLEDGE_MODEL_REFERENCE_EXTRACTOR_VERSION
    from bisheng.resource_reference.application.contracts import SourceKey, SourceType

    async with context.db.sessions() as session, session.begin():

        async def lock_root(active):
            return await active.get(Knowledge, 2)

        binding = await application.runtime.aprepare_source_bindings(
            session,
            SourceKey(101, SourceType.KNOWLEDGE, "2", "current"),
            (),
            new_source=True,
            extractor_version=KNOWLEDGE_MODEL_REFERENCE_EXTRACTOR_VERSION,
            lock_source_root=lock_root,
        )
        await application.runtime.aapply_source_bindings(session, binding)
    target = {
        "tenant_id": 101,
        "resource_type": "knowledge_space",
        "resource_id": "2",
        "resource_version": 0,
        "context_version": "test",
    }
    monkeypatch.setattr(application, "_targets", AsyncMock(return_value=[target]))
    monkeypatch.setattr(application.proofs, "arequire_current", AsyncMock())
    dispatch = AsyncMock()
    monkeypatch.setattr(cleanup.KnowledgeSpaceDirectDeleteService, "dispatch", dispatch, raising=False)
    # The service stores this injected publication port on its instance.
    original = cleanup.KnowledgeSpaceDirectDeleteService.__init__

    def configured(self, **kwargs):
        original(self, **kwargs, dispatch=dispatch)

    monkeypatch.setattr(cleanup.KnowledgeSpaceDirectDeleteService, "__init__", configured)
    plan = await application.aprecheck(identity=application.user, space_id=2, operation="knowledge_space_delete")
    request = ProcessingCreateRequest(
        confirmation_id=plan.confirmation_id, plan_digest=plan.plan_digest, idempotency_key="delete-rebuild"
    )
    result = await application.aconfirm(identity=application.user, space_id=2, request=request)
    assert result["accepted"] and result["state"] == "pending"
    async with context.db.sessions() as session:
        rebuild = await session.get(KnowledgeProcessingJob, "cancel-rebuild")
        assert rebuild.state == "obsolete" and rebuild.obsolete_reason == "resource_deleted"
        assert not rebuild.pending_dispatch and rebuild.lease_until is None
        job = await session.get(KnowledgeSpaceDeleteJob, plan.confirmation_id)
        assert job.business_phase == "prepared" and job.manifest["cancel_processing"]
        assert await session.get(Knowledge, 2) is not None
    dispatch.assert_awaited_once_with(tenant_id=101, job_id=plan.confirmation_id)
    application.purge_step.assert_not_awaited()


async def test_completed_delete_periodically_rechecks_outputs_without_reopening_business(application, context):
    from bisheng.knowledge.domain.repositories.knowledge_space_delete_repository import KnowledgeSpaceDeleteRepository
    from bisheng.knowledge.domain.services.knowledge_space_direct_delete_service import (
        KnowledgeSpaceDirectDeleteService,
    )

    plan = await application.aprecheck(identity=application.user, space_id=2, operation="knowledge_space_clear")
    await application.aconfirm(
        identity=application.user,
        space_id=2,
        request=ProcessingCreateRequest(
            confirmation_id=plan.confirmation_id, plan_digest=plan.plan_digest, idempotency_key="complete-then-verify"
        ),
    )
    async with context.db.sessions() as session, session.begin():
        (await session.get(KnowledgeSpaceDeleteJob, plan.confirmation_id)).next_attempt_at = datetime(2020, 1, 1)
    repository = KnowledgeSpaceDeleteRepository(context.db.sessions)
    assert (101, plan.confirmation_id) in await repository.due_jobs()
    steps = AsyncMock()
    service = KnowledgeSpaceDirectDeleteService(
        session_factory=context.db.sessions, repository=repository, purge_step=steps
    )
    assert await service.purge(plan.confirmation_id)
    assert [call.args[0] for call in steps.await_args_list] == ["minio", "es", "milvus"]
    assert all(call.kwargs == {"verification": True} for call in steps.await_args_list)
    async with context.db.sessions() as session:
        job = await session.get(KnowledgeSpaceDeleteJob, plan.confirmation_id)
        assert job.state == "SUCCEEDED" and job.business_phase == "finalized"
        assert job.attempts == 2 and job.lease_token is None
        assert await session.get(Knowledge, 2) is not None
    assert not await service.purge(plan.confirmation_id)

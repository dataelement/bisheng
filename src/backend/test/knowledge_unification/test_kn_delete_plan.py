"""Local deletion business wiring; only external auth/catalog/purge IO is isolated."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from bisheng.common.errcode.knowledge import (
    KnowledgeOperationPlanConflictError,
    ResourceReferenceConflictError,
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
    tables = (
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
    app.user, app.permission_runtime = service.user, runtime
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


async def test_known_direct_reference_cannot_be_bypassed_by_confirming_non_executable_plan(application, context):
    await native.native.seed(context, (31, 101, "assistant", "configured", "current", "file"))
    plan = await application.aprecheck(
        identity=application.user, space_id=1, selections=native.native.selections(("knowledge_file", 31))
    )
    assert not plan.can_execute
    with pytest.raises(ResourceReferenceConflictError):
        await application.aconfirm(
            identity=application.user,
            space_id=1,
            request=ProcessingCreateRequest(
                confirmation_id=plan.confirmation_id, plan_digest=plan.plan_digest, idempotency_key="cannot-force-file"
            ),
        )
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

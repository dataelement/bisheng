"""§121 real new acceptance, P1 forward stages and original identity narrowing."""

from copy import deepcopy

import pytest
import sqlalchemy as sa

from bisheng.common.errcode.permission import PermissionDeniedError, PermissionPublishNotReadyError
from bisheng.knowledge.domain.models.knowledge_operation_plan import KnowledgeOperationPlan as Plan
from bisheng.knowledge.domain.models.knowledge_processing_item import KnowledgeProcessingItem as Item
from bisheng.knowledge.domain.models.knowledge_processing_retry import KnowledgeProcessingRetryReceipt as Retry
from bisheng.knowledge.domain.schemas.knowledge_space_schema import FileMoveReq
from bisheng.knowledge.domain.schemas.processing_job import ProcessingCreateRequest, ProcessingRetryRequest
from bisheng.permission.domain.models import (
    PermissionProjectionOperation as Operation,
)
from bisheng.permission.domain.models import (
    PermissionProjectionTuple as TupleRow,
)
from bisheng.permission.domain.models import (
    ResourcePermissionMode as Mode,
)
from bisheng.permission.domain.services.projection_service import projection_state_expectations
from bisheng.permission.domain.services.resource_lifecycle_policy import build_move_plan
from test.knowledge_unification import test_move_processing_owner as base
from test.knowledge_unification.test_processing_identity import request_context

store, tenant, moving, accepted, application = base.store, base.tenant, base.moving, base.accepted, base.application


async def reset_to_before(app):
    async with app.built.sessions() as session, session.begin():
        for model in (Item, Retry, base.Job, Plan, TupleRow, Operation):
            await session.execute(sa.delete(model.__table__))
        for item in app.built.expectations:
            await session.execute(
                sa.update(Mode.__table__)
                .where(Mode.resource_type == item.resource_type, Mode.resource_id == item.resource_id)
                .values(
                    mode=item.mode,
                    parent_type=item.before.parent_type,
                    parent_id=item.before.parent_id,
                    version=item.expected_permission_version,
                    projection_state="CURRENT",
                    operation_id=None,
                )
            )
    transport = app.built.bridge.components.projection._fga
    initial = set()
    for item in app.built.expectations:
        plan = build_move_plan(
            item.after,
            old_parent=(item.before.parent_type, item.before.parent_id),
            new_parent=(item.after.parent_type, item.after.parent_id),
            mode=item.mode,
            store_id="actual-store",
            model_id="actual-model",
            operator_id=7,
            idempotency_key="original-before",
        )
        initial.update(
            key for key, present in projection_state_expectations(plan.deltas, after=False).items() if present
        )
    transport.present = initial
    transport.calls.clear()
    app.calls.clear()


async def test_real_precheck_accept_then_fresh_worker_logical_from_no_operations(application):
    app = application
    await reset_to_before(app)
    request = FileMoveReq(items=[{"id": 50, "type": "folder"}], target_space_id=11, target_folder_id=51)
    with request_context(app.actor):
        precheck = await app.owner.aprecheck(10, request, identity=app.current, entry_kind="web")
        assert precheck.can_execute and [row.id for row in precheck.valid_items] == [50]
        assert not app.chat
        accepted = await app.owner.aaccept(
            10,
            ProcessingCreateRequest(
                confirmation_id=precheck.confirmation_id,
                plan_digest=precheck.plan_digest,
                idempotency_key="actual-new-job",
            ),
            identity=app.current,
            entry_kind="web",
        )
    assert accepted.state == "accepted" and not accepted.reused
    assert ("folder", 50, "move") in app.calls and ("folder", 51, "upload_file") in app.calls
    async with app.built.sessions() as session:
        job = await session.get(base.Job, accepted.job_id)
        assert job.move_logical_marker is None and job.pending_dispatch
        revision = job.revision
    app.built.job_id = accepted.job_id
    lease = await app.owner.astart_attempt(accepted.job_id, expected_dispatch_revision=revision)
    assert lease is not None
    result = await app.owner.aensure_logical(lease)
    assert result.state == "running"
    assert app.chat


@pytest.mark.parametrize("status", ["PREPARED", "STAGING", "COMMIT_UNKNOWN", "COMMITTED", "FAILED_CLOSED"])
async def test_original_partial_ledger_resumes_forward_before_business_cutover(application, status):
    app = application
    # Change only the native stage, retaining complete original checksummed ledger.
    async with app.built.sessions() as session, session.begin():
        operation = (await session.execute(sa.select(Operation))).scalars().one()
        operation.status = status
        if status == "PREPARED":
            item = app.built.expectations[0]
            await session.execute(
                sa.update(Mode.__table__)
                .where(Mode.operation_id == operation.id)
                .values(
                    version=item.expected_permission_version,
                    parent_type=item.before.parent_type,
                    parent_id=item.before.parent_id,
                    projection_state="CURRENT",
                    operation_id=None,
                )
            )
    result = await app.owner.aensure_logical(app.built.lease)
    assert result is not None
    assert (("folder", 50, "move") in app.calls) == (status == "PREPARED")
    async with app.built.sessions() as session:
        assert (await session.execute(sa.select(Operation.status))).scalar_one() == "FINALIZED"
        assert (await session.get(base.File, 81)).knowledge_id == 11


async def test_wrong_current_mode_and_foreign_candidate_are_not_continuation(application):
    app = application
    async with app.built.sessions() as session, session.begin():
        await session.execute(sa.update(Mode.__table__).where(Mode.resource_id == "50").values(operation_id=999))
    with pytest.raises(PermissionPublishNotReadyError):
        await app.owner.aensure_logical(app.built.lease)
    assert not app.chat


@pytest.mark.parametrize("subject", ["other_user", "same_audit_service_account"])
async def test_accept_replay_other_typed_subject_must_explicitly_retry(application, subject):
    app = application
    args = app.built.confirmed.args
    request = ProcessingCreateRequest(
        **{key: args[key] for key in ("confirmation_id", "plan_digest", "idempotency_key")}
    )
    current = base.user(8)
    from bisheng.permission.application.identity import PermissionActor

    actor = PermissionActor(user_id=8, tenant_id=101)
    if subject == "same_audit_service_account":
        # Same numeric subject cannot impersonate original user through capture.
        actor = PermissionActor(subject_type="service_account", subject_id=7, tenant_id=101)
        current = base.user(7)
    with request_context(actor), pytest.raises(PermissionDeniedError):
        await app.owner.aaccept(10, request, identity=current, entry_kind="web")


async def test_same_subject_new_retry_credential_and_original_ceiling_are_recorded(application):
    app = application
    await app.owner.aensure_logical(app.built.lease)
    lease = await app.owner.aclaim_item(app.built.lease)
    await app.owner.afail_item(lease, error_code=10900)
    await app.owner.afinalize_attempt(app.built.lease)
    async with app.built.sessions() as session:
        revision = (await session.get(base.Job, app.built.job_id)).revision
    app.current.token_version = 4
    app.current._runtime_credential_reference = deepcopy(base.user(version=4)._runtime_credential_reference)
    with request_context(app.actor):
        result = await app.owner.aretry_failed(
            app.built.job_id,
            ProcessingRetryRequest(idempotency_key="new-jwt", expected_job_revision=revision),
            identity=app.current,
            entry_kind="web",
        )
    assert result.state == "accepted"
    async with app.built.sessions() as session:
        receipt = (await session.execute(sa.select(Retry))).scalars().one()
        assert receipt.actor_reference["credential_reference"]["token_version"] == 4
        assert (await session.get(base.Job, app.built.job_id)).actor_reference["credential_reference"][
            "token_version"
        ] == 3


async def test_candidate_operator_must_be_real_job_membership(application):
    app = application
    async with app.built.sessions() as session, session.begin():
        await session.execute(sa.update(Operation.__table__).values(operator_id=999))
    with pytest.raises(PermissionDeniedError):
        await app.owner.aensure_logical(app.built.lease)
    assert not app.chat


async def test_same_subject_fresh_personal_credential_cannot_widen_to_original_all_scope(application, monkeypatch):
    from bisheng.permission.application import data_scope
    from bisheng.permission.application.identity import PermissionActor

    app = application
    monkeypatch.setattr(data_scope, "get_data_scope_resolver", lambda: None)
    admission = __import__(
        "bisheng.knowledge.application.move_processing_admission", fromlist=["get_data_scope_resolver"]
    )
    monkeypatch.setattr(admission, "get_data_scope_resolver", lambda: None)
    args = app.built.confirmed.args
    request = ProcessingCreateRequest(
        **{key: args[key] for key in ("confirmation_id", "plan_digest", "idempotency_key")}
    )
    with request_context(PermissionActor(user_id=7, tenant_id=101, data_scope="personal_only")):
        with pytest.raises(PermissionDeniedError):
            await app.owner.aaccept(10, request, identity=app.current, entry_kind="web")


async def test_unknown_actual_outer_commit_does_not_chat_and_ready_replay_recovers(application, monkeypatch):
    app = application
    original = app.owner.jobs.amark_move_ready
    fired = []

    async def mark(*args, **kwargs):
        result = await original(*args, **kwargs)
        if not fired:

            def unknown(session):
                if session.get_nested_transaction() is None and not fired:
                    fired.append(True)
                    raise RuntimeError("actual commit acknowledgement lost")

            sa.event.listen(args[0].sync_session, "after_commit", unknown)
        return result

    monkeypatch.setattr(app.owner.jobs, "amark_move_ready", mark)
    with pytest.raises(RuntimeError, match="acknowledgement lost"):
        await app.owner.aensure_logical(app.built.lease)
    assert fired and not app.chat
    async with app.built.sessions() as session:
        assert (await session.get(base.Job, app.built.job_id)).move_logical_marker is not None
    result = await app.owner.aensure_logical(app.built.lease)
    assert result.reused and len(app.chat) == 1


@pytest.mark.parametrize("zero", ["empty", "skipped"])
async def test_zero_items_public_precheck_accept_still_runs_actual_logical_and_chat(application, zero):
    from bisheng.database.models.tag import TagLink
    from bisheng.knowledge.domain.models.knowledge_document import KnowledgeDocument as Doc
    from bisheng.knowledge.domain.models.knowledge_document_version import KnowledgeDocumentVersion as Version

    app = application
    await reset_to_before(app)
    async with app.built.sessions() as session, session.begin():
        if zero == "empty":
            for model in (TagLink, Version, Doc):
                await session.execute(sa.delete(model.__table__))
            await session.execute(
                sa.delete(base.File.__table__).where(base.File.id.in_((81, 82)), base.File.tenant_id == 101)
            )
        else:
            await session.execute(
                sa.update(base.File.__table__).where(base.File.id == 81, base.File.tenant_id == 101).values(status=3)
            )
    with request_context(app.actor):
        checked = await app.owner.aprecheck(
            10,
            FileMoveReq(items=[{"id": 50, "type": "folder"}], target_space_id=11, target_folder_id=51),
            identity=app.current,
            entry_kind="web",
        )
        assert checked.can_execute and checked.valid_items
        result = await app.owner.aaccept(
            10,
            ProcessingCreateRequest(
                confirmation_id=checked.confirmation_id, plan_digest=checked.plan_digest, idempotency_key="real-zero"
            ),
            identity=app.current,
            entry_kind="web",
        )
    app.built.job_id = result.job_id
    async with app.built.sessions() as session:
        job = await session.get(base.Job, result.job_id)
        assert job.total_count == 0 and job.state == "accepted" and job.pending_dispatch
        revision = job.revision
    lease = await app.owner.astart_attempt(result.job_id, expected_dispatch_revision=revision)
    assert (await app.owner.aensure_logical(lease)).state == "succeeded"
    assert app.chat


@pytest.mark.parametrize(
    "kind", ["embedding_rebuild", "file_reprocess", "file_resplit", "metadata_schema_change", "space_copy"]
)
async def test_owner_explicitly_rejects_every_ordinary_kind(application, kind):
    app = application
    async with app.built.sessions() as session, session.begin():
        await session.execute(
            sa.update(base.Job.__table__)
            .where(base.Job.id == app.built.job_id, base.Job.tenant_id == 101)
            .values(kind=kind)
        )
    with pytest.raises(ValueError, match="only accepts move_index"):
        await app.owner.aensure_logical(app.built.lease)


async def test_different_subject_retry_rechecks_selected_current_move_and_records_real_receipt(
    application, monkeypatch
):
    from bisheng.permission.application.identity import PermissionActor

    app = application
    await app.owner.aensure_logical(app.built.lease)
    lease = await app.owner.aclaim_item(app.built.lease)
    assert await app.owner.afail_item(lease, error_code=10900)
    await app.owner.afinalize_attempt(app.built.lease)
    async with app.built.sessions() as session:
        revision = (await session.get(base.Job, app.built.job_id)).revision
    admission = __import__(
        "bisheng.knowledge.application.move_processing_admission", fromlist=["require_business_action"]
    )
    checked = []

    async def current_actions(identity, **kwargs):
        checked.append((kwargs["resource_type"], kwargs["resource_id"], kwargs["action"]))

    monkeypatch.setattr(admission, "require_business_action", current_actions)
    new = base.user(8)
    original_resolve = base.processing_identity.resolve_web_runtime_identity

    async def resolve_current(reference):
        if reference["user_id"] == 8:
            return new
        return await original_resolve(reference)

    monkeypatch.setattr(base.processing_identity, "resolve_web_runtime_identity", resolve_current)
    with request_context(PermissionActor(user_id=8, tenant_id=101)):
        result = await app.owner.aretry_failed(
            app.built.job_id,
            ProcessingRetryRequest(idempotency_key="other-user", expected_job_revision=revision),
            identity=new,
            entry_kind="web",
        )
    assert result.state == "accepted" and ("folder", 50, "move") in checked and ("folder", 51, "upload_file") in checked
    async with app.built.sessions() as session:
        receipt = (await session.execute(sa.select(Retry))).scalars().one()
        assert (receipt.actor_subject_type, receipt.actor_subject_id) == ("user", 8)
        assert (await session.get(base.Job, app.built.job_id)).actor_subject_id == 7

"""§121 actual application composition, native transactions and credential origin."""

import importlib
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
import sqlalchemy as sa

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.permission import PermissionDeniedError
from bisheng.knowledge.application import processing_identity
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile as File
from bisheng.knowledge.domain.models.knowledge_processing_job import KnowledgeProcessingJob as Job
from bisheng.knowledge.domain.schemas.knowledge_space_schema import FileMoveReq
from bisheng.knowledge.domain.schemas.processing_job import ProcessingCreateRequest
from bisheng.permission.application.identity import PermissionActor
from test.knowledge_unification import test_move_reference_ownership as refs
from test.knowledge_unification.test_move_execution_fixtures import pipeline
from test.knowledge_unification.test_processing_identity import request_context

store, tenant, moving, accepted = refs.store, refs.tenant, refs.moving, refs.accepted


def api():
    return importlib.import_module("bisheng.knowledge.application.move_processing_owner")


def user(ident=7, version=3):
    value = UserPayload(user_id=ident, tenant_id=101, user_role=[], token_version=version)
    value._runtime_credential_reference = dict(
        kind="web_session",
        user_id=ident,
        tenant_id=101,
        token_version=version,
        expires_at=(datetime.now(UTC) + timedelta(hours=1)).replace(tzinfo=None).isoformat(),
    )
    return value


@pytest.fixture
async def application(moving, accepted, monkeypatch):
    current = user()
    actor = PermissionActor(user_id=7, tenant_id=101)
    with request_context(actor):
        origin = await processing_identity.capture_processing_actor(
            current, space_id=10, required_action="move", entry_kind="web"
        )

    async def confirmed(**kwargs):
        return await accepted(origin=origin.reference, **kwargs)

    built = await pipeline(moving, confirmed, monkeypatch)
    await refs.seed(built)
    runtime = refs.compose(built).runtime
    calls, chat, restores = [], [], []

    async def resolve(reference):
        restores.append(deepcopy(reference))
        if reference["token_version"] < current.token_version:
            raise PermissionDeniedError(reason="revoked_old_credential")
        return current

    async def actor_for(identity):
        return PermissionActor(user_id=identity.user_id, tenant_id=identity.tenant_id)

    monkeypatch.setattr(processing_identity, "resolve_web_runtime_identity", resolve)
    monkeypatch.setattr(processing_identity, "resolve_permission_actor", actor_for)

    def rehome(**kwargs):
        chat.append(kwargs)
        return 1

    owner = api().KnowledgeMoveProcessingOwner(
        session_factory=built.sessions,
        projection=built.bridge,
        reference_runtime=runtime,
        clock=lambda: built.clock[0],
        chat_rehome=rehome,
    )
    admission = importlib.import_module("bisheng.knowledge.application.move_processing_admission")

    async def require(identity, *, resource_type, resource_id, action, **kwargs):
        calls.append((resource_type, int(resource_id), action))
        assert (resource_type, action) not in {("knowledge_space", "move"), ("knowledge_space", "edit")}

    monkeypatch.setattr(admission, "require_business_action", require)
    return SimpleNamespace(
        owner=owner, built=built, current=current, actor=actor, calls=calls, chat=chat, restores=restores
    )


async def test_real_logical_then_r2_ready_and_chat_only_after_commit(application):
    app = application
    assert await app.owner.aensure_logical(app.built.lease) is not None
    refs_after, _, files, marker = await refs.facts(app.built)
    assert {row["target_space_id"] for row in refs_after} == {"11"}
    assert marker is not None and all(row.knowledge_id == 11 for row in files)
    assert app.chat == [
        dict(
            source_space_id=10,
            source_flow_ids=["space_10_file_81", "space_10_file_82", "space_10_folder_50"],
            reason="cross_space_move",
        )
    ]
    assert ("folder", 51, "upload_file") in app.calls
    assert not any(action == "move" for _, _, action in app.calls)  # Actual own FINALIZED after facts.


async def test_same_subject_fresh_jwt_replays_original_j1_bytes_without_restoring_old(application):
    app = application
    async with app.built.sessions() as session:
        original = deepcopy((await session.get(Job, app.built.job_id)).actor_reference)
        request_hash = (await session.get(Job, app.built.job_id)).request_hash
    fresh = user(version=4)
    app.current.token_version = 4
    app.current._runtime_credential_reference = deepcopy(fresh._runtime_credential_reference)
    request = ProcessingCreateRequest(
        **{key: app.built.confirmed.args[key] for key in ("confirmation_id", "plan_digest", "idempotency_key")}
    )
    with request_context(app.actor):
        result = await app.owner.aaccept(10, request, identity=app.current, entry_kind="web")
    assert result.reused and result.job_id == app.built.job_id
    async with app.built.sessions() as session:
        job = await session.get(Job, app.built.job_id)
        assert job.actor_reference == original and job.request_hash == request_hash
    assert not any(ref["token_version"] == 3 for ref in app.restores)


async def test_restore_failure_can_be_persisted_via_trusted_fail_attempt(application, monkeypatch):
    app = application

    async def revoked(*args, **kwargs):
        raise PermissionDeniedError()

    monkeypatch.setattr(processing_identity, "resolve_web_runtime_identity", revoked)
    with pytest.raises(PermissionDeniedError):
        await app.owner.aensure_logical(app.built.lease)
    async with app.built.sessions() as session:
        revision = (await session.get(Job, app.built.job_id)).revision
    assert await app.owner.afail_attempt(
        app.built.job_id, expected_job_revision=revision, error_code=10900, lease=app.built.lease
    )
    async with app.built.sessions() as session:
        job = await session.get(Job, app.built.job_id)
        assert job.state == "failed" and job.error_code == 10900


@pytest.mark.parametrize("invalid", ["same_space", "skip_invalid"])
async def test_internal_precheck_rejects_unavailable_batch_mode_without_plan_write(application, invalid):
    app = application
    request = FileMoveReq(
        items=[dict(id=50, type="folder")],
        target_space_id=10 if invalid == "same_space" else 11,
        target_folder_id=51,
        skip_invalid=invalid == "skip_invalid",
    )
    with request_context(app.actor), pytest.raises((ValueError, PermissionDeniedError)):
        await app.owner.aprecheck(10, request, identity=app.current, entry_kind="web")
    assert not app.chat

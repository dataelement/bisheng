"""§121 actual API S/D restore and same-subject credential ceiling, native Job/P1."""

from dataclasses import replace

import pytest

from bisheng.knowledge.application import processing_identity
from bisheng.knowledge.domain.schemas.processing_job import ProcessingCreateRequest
from bisheng.permission.application.identity import PermissionActor
from test.knowledge_unification import test_move_processing_owner as base
from test.knowledge_unification.test_move_execution_fixtures import pipeline
from test.knowledge_unification.test_processing_identity import api_ports as api_ports
from test.knowledge_unification.test_processing_identity import principal, request_context

store, tenant, moving, accepted = base.store, base.tenant, base.moving, base.accepted


@pytest.mark.parametrize("delegated", [False, True])
async def test_real_api_origin_restores_same_s_d_subject_and_replays_new_credential(
    moving, accepted, api_ports, monkeypatch, delegated
):
    current = principal(
        delegated=delegated, scopes={"knowledge:write", "delegate"} if delegated else {"knowledge:write"}
    )
    actor = PermissionActor(
        subject_type=current.authorization_subject_type, subject_id=current.authorization_subject_id, tenant_id=101
    )
    with request_context(actor, current):
        origin = await processing_identity.capture_processing_actor(
            current, space_id=10, required_action="move", entry_kind="open_api"
        )

    async def confirmed(**kwargs):
        result = await accepted(origin=origin.reference, **kwargs)
        result.args["actor_user_id"] = origin.actor_user_id
        return result

    from test.knowledge_unification import test_move_execution_fixtures as pipeline_module

    original_compose = pipeline_module.compose

    async def compose_actual_subject(*args, **kwargs):
        built = await original_compose(*args, **kwargs)
        original_execute = built.bridge.aexecute_or_resume

        async def execute(*, job_id, changes, actor):
            actual = tuple(replace(item, allowed_operator_ids=(current.authorization_subject_id,)) for item in changes)
            return await original_execute(
                job_id=job_id,
                changes=actual,
                actor=PermissionActor(
                    subject_type=current.authorization_subject_type,
                    subject_id=current.authorization_subject_id,
                    tenant_id=101,
                ),
            )

        monkeypatch.setattr(built.bridge, "aexecute_or_resume", execute)
        return built

    monkeypatch.setattr(pipeline_module, "compose", compose_actual_subject)
    built = await pipeline(moving, confirmed, monkeypatch)
    await base.refs.seed(built)
    from bisheng.permission.application.knowledge_move_projection import KnowledgeMoveProjectionApplication

    monkeypatch.setattr(
        built.bridge, "aexecute_or_resume", KnowledgeMoveProjectionApplication.aexecute_or_resume.__get__(built.bridge)
    )
    runtime = base.refs.compose(built).runtime
    owner = base.api().KnowledgeMoveProcessingOwner(
        session_factory=built.sessions,
        projection=built.bridge,
        reference_runtime=runtime,
        clock=lambda: built.clock[0],
        chat_rehome=lambda **kwargs: 0,
    )
    admission = __import__(
        "bisheng.knowledge.application.move_processing_admission", fromlist=["require_business_action"]
    )
    observed = []

    async def require(identity, **kwargs):
        from bisheng.open_api.domain.context import get_current_open_api_principal
        from bisheng.permission.application.identity import get_current_permission_actor

        actual = get_current_open_api_principal()
        observed.append(actual)
        assert actual.mode == current.mode
        assert get_current_permission_actor().subject_id == current.authorization_subject_id
        assert not actual.has_scope("model:invoke")

    monkeypatch.setattr(admission, "require_business_action", require)
    api_ports.current[0] = current
    assert await owner.aensure_logical(built.lease) is not None
    newer = current.model_copy(update={"credential_id": 21, "scopes": current.scopes | {"model:invoke"}})
    api_ports.current[0] = newer
    api_ports.row.id = 21
    args = built.confirmed.args
    request = ProcessingCreateRequest(
        **{key: args[key] for key in ("confirmation_id", "plan_digest", "idempotency_key")}
    )
    with request_context(actor, newer):
        replay = await owner.aaccept(10, request, identity=newer, entry_kind="open_api")
    assert replay.reused
    async with built.sessions() as session:
        job = await session.get(base.Job, built.job_id)
        assert job.actor_reference == origin.reference
        assert (job.actor_subject_type, job.actor_subject_id) == (
            current.authorization_subject_type,
            current.authorization_subject_id,
        )
    assert observed and observed[-1].credential_id == 21

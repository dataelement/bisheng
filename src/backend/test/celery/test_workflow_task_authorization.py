"""The ``use`` gate on the workflow Celery tasks.

The gate runs on the Celery task thread, but the authorization coroutine runs
on the worker's shared event loop. ContextVars do not cross that boundary by
themselves: an earlier version submitted the coroutine without copying the
context, so the gate saw no actor and no tenant and silently authorized against
a weaker identity than the handshake had resolved.

These tests pin both halves of the fix — the context actually arrives, and the
actor is handed over explicitly so the decision never depends on propagation.
"""

from types import SimpleNamespace

import pytest

from bisheng.common.errcode.http_error import UnAuthorizedError
from bisheng.core.context.tenant import get_current_tenant_id
from bisheng.open_api.domain.context import OpenApiExecutionSnapshot
from bisheng.permission.application.identity import get_current_permission_actor
from bisheng.worker.workflow import tasks

WORKFLOW_ID = "flow-1"


def guest_snapshot(*, super_admin: bool = True) -> dict:
    return OpenApiExecutionSnapshot(
        tenant_id=3,
        actor_kind="natural_person",
        actor_id=41,
        authorization_subject_type="user",
        authorization_subject_id=41,
        resource_owner_user_id=41,
        effective_user_id=41,
        mode="S",
        credential_id=None,
        trace_id="public-v3",
        channel="public_v3",
        super_admin=super_admin,
        tenant_admin_tenant_ids=frozenset(),
    ).model_dump(mode="json")


@pytest.fixture
def harness(monkeypatch):
    """Stub everything around the gate and record what the gate observed."""

    seen = SimpleNamespace(calls=[], ran=[], allow=True)

    async def require_business_action(login_user, *, resource_type, resource_id, action, actor=None):
        # Observed from inside the coroutine, i.e. on the worker loop thread.
        seen.calls.append(
            {
                "ambient_actor": get_current_permission_actor(),
                "ambient_tenant": get_current_tenant_id(),
                "actor_kwarg": actor,
                "resource_type": resource_type,
                "resource_id": resource_id,
                "action": action,
                "login_user_id": login_user.user_id,
            }
        )
        if not seen.allow:
            raise UnAuthorizedError()

    monkeypatch.setattr(tasks, "require_business_action", require_business_action)
    monkeypatch.setattr(
        tasks, "_execute_workflow", lambda *args, **kwargs: seen.ran.append("execute")
    )
    monkeypatch.setattr(
        tasks, "_continue_workflow", lambda *args, **kwargs: seen.ran.append("continue")
    )
    monkeypatch.setattr(
        "bisheng.open_api.domain.services.execution_context.validate_execution_snapshot",
        lambda _snapshot: None,
    )
    monkeypatch.setattr(
        tasks.WorkFlowService, "get_one_workflow_simple_info_sync", lambda _id: None
    )
    monkeypatch.setattr(tasks.telemetry_service, "log_event_sync", lambda **kwargs: None)
    return seen


@pytest.mark.parametrize(
    ("task", "label"),
    # ``.run`` is the undecorated body; the suite stubs the Celery decorator.
    [(tasks.execute_workflow.run, "execute"), (tasks.continue_workflow.run, "continue")],
    ids=["execute", "continue"],
)
def test_use_gate_sees_the_restored_identity(harness, task, label) -> None:
    task("unique-1", WORKFLOW_ID, "chat-1", 41, "api", guest_snapshot())

    assert harness.ran == [label]
    assert len(harness.calls) == 1
    call = harness.calls[0]
    # The context crossed the thread boundary.
    assert call["ambient_actor"] is not None
    assert call["ambient_actor"].fga_subject == "user:41"
    assert call["ambient_tenant"] == 3
    # And the decision does not depend on that propagation.
    assert call["actor_kwarg"] is not None
    assert call["actor_kwarg"].super_admin is True
    assert call["resource_id"] == WORKFLOW_ID
    assert call["action"] == "use"


def test_gate_carries_a_plain_operator_without_privilege(harness) -> None:
    tasks.execute_workflow.run(
        "unique-1", WORKFLOW_ID, "chat-1", 41, "api", guest_snapshot(super_admin=False)
    )

    assert harness.calls[0]["actor_kwarg"].super_admin is False


@pytest.mark.parametrize(
    ("task", "label"),
    # ``.run`` is the undecorated body; the suite stubs the Celery decorator.
    [(tasks.execute_workflow.run, "execute"), (tasks.continue_workflow.run, "continue")],
    ids=["execute", "continue"],
)
def test_denied_use_stops_the_run(harness, task, label) -> None:
    del label
    harness.allow = False

    with pytest.raises(UnAuthorizedError):
        task("unique-1", WORKFLOW_ID, "chat-1", 41, "api", guest_snapshot())

    assert harness.ran == []


def test_platform_runs_without_a_snapshot_skip_the_gate(harness) -> None:
    """Workbench runs carry no snapshot and must stay on the existing path."""

    tasks.execute_workflow.run("unique-1", WORKFLOW_ID, "chat-1", 41, "platform", None)

    assert harness.calls == []
    assert harness.ran == ["execute"]

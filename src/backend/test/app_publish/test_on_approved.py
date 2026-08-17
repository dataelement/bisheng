"""T032 — ``on_approved``: what happens after the last approver says yes (AC-31 / AC-35 / AC-36 / AC-64).

Every assertion in this file exists to pin one boundary, because getting it
wrong is invisible: **the approval outbox judges success purely by whether the
callback raised.** A normal return marks the instance ``executed``. An exception
marks it ``execute_failed``, files an exception record and pages the
administrators — i.e. it tells everybody the *approval* failed.

So "待上线" — approved, but the machine had no room or the app would not start —
must return normally. It is a product terminal state with its own application
state, its own notification and its own button (AC-31); raising there
contradicts the approval that just succeeded. Conversely, swallowing an
unreachable orchestrator would report a publish that never happened.

The rule, and the shape of this file: **will the application get better on its
own or with one human click? return. Is something broken? raise.**

* return — capacity refused it · the start failed · the app was deleted mid-flight
  · the app is stopped so the version is only staged
* raise — the orchestrator is unreachable · the version record is missing · the
  state machine refuses the transition
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from .conftest import SUPER_ADMIN_USER_ID

pytestmark = pytest.mark.asyncio


def _handler():
    from bisheng.app_publish.domain.services.app_publish_scenario_handler import AppPublishScenarioHandler

    return AppPublishScenarioHandler()


def _result(*, state: str, ok: bool = True, reason: str = "", version_id: str | None = None, detail=None):
    """An ``ActionResult`` as F054's state actions return it."""
    from bisheng.app_runtime.domain.services.app_state_service import ActionResult

    return ActionResult(
        app_id="app",
        state=state,
        ok=ok,
        reason=reason,
        version_id=version_id,
        detail=detail or {},
    )


async def _scene(app_factory, deployment_factory, *, state: str = "draft"):
    """An app with a version and the deployment whose approval just passed."""
    from bisheng.app_publish.domain.models.app_deployment import STAGE_APPROVAL_CREATED, STATUS_WAITING_APPROVAL

    app, version = await app_factory(state=state, with_version=True)
    deployment = await deployment_factory(
        app_id=app.id,
        stage=STAGE_APPROVAL_CREATED,
        status=STATUS_WAITING_APPROVAL,
        version_id=version.id,
        tier_code="light",
        manifest={"name": app.name, "runtime": "python3.11", "port": 8080},
    )
    payload = {
        "app_id": app.id,
        "app_name": app.name,
        "version_id": version.id,
        "version_no": version.version_no,
        "deployment_id": deployment.id,
        "owner_user_id": app.owner_user_id,
        "tenant_id": app.tenant_id,
    }
    return app, version, deployment, payload


@pytest.fixture()
def state_actions(monkeypatch):
    """Programmable stand-ins for the two F054 state actions ``on_approved`` calls.

    Patched rather than exercised because a real ``publish`` needs a live
    orchestrator, and what is under test here is the *dispatch* — which branch
    ran, and whether the callback returned or raised.
    """
    from bisheng.app_runtime.domain.services.app_state_service import AppStateService

    calls: list[tuple[str, dict]] = []
    responses: dict[str, object] = {
        "stage_version": None,
        "publish": _result(state="online"),
        "manual_publish": _result(state="online"),
    }

    async def _stage(app_id, version_id):
        calls.append(("stage_version", {"app_id": app_id, "version_id": version_id}))
        value = responses["stage_version"]
        if isinstance(value, Exception):
            raise value
        return value

    def _action(name):
        async def _call(app_id, *, actor=None):
            calls.append((name, {"app_id": app_id, "actor": actor}))
            value = responses[name]
            if isinstance(value, Exception):
                raise value
            return value

        return _call

    monkeypatch.setattr(AppStateService, "stage_version", staticmethod(_stage))
    monkeypatch.setattr(AppStateService, "publish", staticmethod(_action("publish")))
    monkeypatch.setattr(AppStateService, "manual_publish", staticmethod(_action("manual_publish")))
    return SimpleNamespace(calls=calls, responses=responses)


async def _terminal_state(publish_db, app_id: str, version_id: str):
    from bisheng.database.models.app_version import AppVersionDao

    async with publish_db() as session:
        row = await AppVersionDao.aget(session, app_id, version_id)
    return row.terminal_state


# ---------------------------------------------------------------------------
# AC-31 — online
# ---------------------------------------------------------------------------


async def test_online_marks_terminal_online_and_audits(
    publish_db, app_factory, deployment_factory, state_actions, audit_sink, approval_notifications
):
    """The success path: the version is latched ``online`` and the event is recorded.

    No extra station message is sent here — the engine already told the
    applicant their request was approved, and the owner *is* the applicant
    (AC-16). A second "your app is online" would be one of only three new
    action codes this feature is allowed to introduce, spent on a duplicate.
    """
    app, version, _, payload = await _scene(app_factory, deployment_factory)

    outcome = await _handler().on_approved(1, payload)

    assert outcome["status"] == "online"
    assert await _terminal_state(publish_db, app.id, version.id) == "online"
    assert "app.release.online" in [call["action"] for call in audit_sink]


async def test_stage_version_called_before_publish(
    publish_db, app_factory, deployment_factory, state_actions, audit_sink, approval_notifications
):
    """``pending_version_id`` is written first, and it is what makes AC-36 work at all."""
    _, _, _, payload = await _scene(app_factory, deployment_factory)

    await _handler().on_approved(1, payload)

    assert [name for name, _ in state_actions.calls] == ["stage_version", "publish"]


async def test_publish_acts_as_the_owner_not_as_a_super_admin(
    publish_db, app_factory, deployment_factory, state_actions, audit_sink, approval_notifications
):
    """The audit trail should read "the owner published", because that is what happened.

    Passing an ``is_global_super`` actor would also skip F054's operator check
    — the very check we want exercised on this path.
    """
    app, _, _, payload = await _scene(app_factory, deployment_factory)

    await _handler().on_approved(1, payload)

    actor = dict(state_actions.calls[1][1])["actor"]
    assert actor.user_id == app.owner_user_id
    assert actor.is_global_super is False


# ---------------------------------------------------------------------------
# AC-31 — parked, which is NOT a failure
# ---------------------------------------------------------------------------


async def test_capacity_shortage_returns_normally_and_sets_pending_capacity(
    publish_db, app_factory, deployment_factory, state_actions, audit_sink, approval_notifications
):
    """Raising here would mark the approval ``execute_failed`` — the opposite of AC-31."""
    _, _, _, payload = await _scene(app_factory, deployment_factory)
    state_actions.responses["publish"] = _result(
        state="pending_capacity", ok=False, reason="capacity_exhausted", detail={"stage": "admission"}
    )

    outcome = await _handler().on_approved(1, payload)

    assert outcome["status"] == "pending_capacity"
    assert outcome["app_state"] == "pending_capacity"


async def test_deploy_failure_returns_normally_and_sets_pending_deploy_failed(
    publish_db, app_factory, deployment_factory, state_actions, audit_sink, approval_notifications
):
    """The second cause of "待上线": it had room, it just would not start."""
    _, _, _, payload = await _scene(app_factory, deployment_factory)
    state_actions.responses["publish"] = _result(
        state="pending_capacity", ok=False, reason="probe failed", detail={"stage": "deploy", "code": 16144}
    )

    outcome = await _handler().on_approved(1, payload)

    assert outcome["status"] == "pending_deploy_failed"


async def test_parked_causes_are_distinguished_by_the_park_stage(
    publish_db, app_factory, deployment_factory, state_actions, audit_sink, approval_notifications
):
    """ "No room" and "your code crashed" must not collapse into one message.

    Told apart by ``detail["stage"]``, which F054 sets when it parks. Guessing
    "deploy_failed" for a capacity shortage would send an owner to debug code
    that is fine.
    """
    _, _, _, payload = await _scene(app_factory, deployment_factory)

    state_actions.responses["publish"] = _result(state="pending_capacity", ok=False, detail={"stage": "admission"})
    capacity = await _handler().on_approved(1, payload)
    state_actions.responses["publish"] = _result(state="pending_capacity", ok=False, detail={"stage": "deploy"})
    failed = await _handler().on_approved(1, payload)

    assert capacity["status"] != failed["status"]


async def test_parked_keeps_terminal_state_null(
    publish_db, app_factory, deployment_factory, state_actions, audit_sink, approval_notifications
):
    """ "待上线" is derived from the app state, not stored as a fourth version outcome.

    Storing it would merge the version-outcome line and the availability line
    into one column, and they are orthogonal on purpose.
    """
    app, version, _, payload = await _scene(app_factory, deployment_factory)
    state_actions.responses["publish"] = _result(state="pending_capacity", ok=False, detail={"stage": "admission"})

    await _handler().on_approved(1, payload)

    assert await _terminal_state(publish_db, app.id, version.id) is None


async def test_pending_online_notifies_owner_and_admins(
    publish_db, app_factory, deployment_factory, state_actions, audit_sink, approval_notifications, super_admin_user
):
    """AC-64. The unconditional super-admin union is correct **here** — this is a notice.

    The same union used for approver resolution would be the defect AC-21
    removes; one extra reader costs nothing, one extra approver is one more
    person who can decide.
    """
    app, _, _, payload = await _scene(app_factory, deployment_factory)
    state_actions.responses["publish"] = _result(state="pending_capacity", ok=False, detail={"stage": "admission"})

    await _handler().on_approved(1, payload)

    parked = [one for one in approval_notifications if one.get("action_code") == "app_publish_pending_capacity"]
    assert len(parked) == 1
    assert app.owner_user_id in parked[0]["receiver_user_ids"]
    assert SUPER_ADMIN_USER_ID in parked[0]["receiver_user_ids"]


async def test_deploy_failed_uses_its_own_action_code(
    publish_db, app_factory, deployment_factory, state_actions, audit_sink, approval_notifications, super_admin_user
):
    _, _, _, payload = await _scene(app_factory, deployment_factory)
    state_actions.responses["publish"] = _result(state="pending_capacity", ok=False, detail={"stage": "deploy"})

    await _handler().on_approved(1, payload)

    assert [one["action_code"] for one in approval_notifications] == ["app_publish_deploy_failed"]


async def test_parked_audits_pending_online(
    publish_db, app_factory, deployment_factory, state_actions, audit_sink, approval_notifications
):
    _, _, _, payload = await _scene(app_factory, deployment_factory)
    state_actions.responses["publish"] = _result(
        state="pending_capacity", ok=False, reason="capacity_exhausted", detail={"stage": "admission"}
    )

    await _handler().on_approved(1, payload)

    rows = [call for call in audit_sink if call["action"] == "app.release.pending_online"]
    assert len(rows) == 1
    assert rows[0]["metadata"]["reason_kind"] == "capacity"


# ---------------------------------------------------------------------------
# AC-36 — a stopped application is staged, never restarted
# ---------------------------------------------------------------------------


async def test_stopped_app_only_stages_not_publishes(
    publish_db, app_factory, deployment_factory, state_actions, audit_sink, approval_notifications
):
    """Approval on a stopped app records the version and stops there.

    Auto-restarting would undo an operator's deliberate stop. ``resume`` picks
    ``pending_version_id`` up when they ask for it.
    """
    _, _, _, payload = await _scene(app_factory, deployment_factory, state="stopped")

    outcome = await _handler().on_approved(1, payload)

    assert outcome["status"] == "staged_only"
    assert [name for name, _ in state_actions.calls] == ["stage_version"]


async def test_stopped_app_keeps_terminal_state_null(
    publish_db, app_factory, deployment_factory, state_actions, audit_sink, approval_notifications
):
    """It is not online, so it is not ``online``. It becomes so on resume."""
    app, version, _, payload = await _scene(app_factory, deployment_factory, state="stopped")

    await _handler().on_approved(1, payload)

    assert await _terminal_state(publish_db, app.id, version.id) is None


# ---------------------------------------------------------------------------
# AC-35 — the deletion race
# ---------------------------------------------------------------------------


async def test_deleted_app_returns_normally_as_race_defense(
    publish_db, app_factory, deployment_factory, state_actions, audit_sink, approval_notifications
):
    """Deletion cancels the request; this is the losing side of that race, not an error."""
    _, _, _, payload = await _scene(app_factory, deployment_factory, state="deleted")

    outcome = await _handler().on_approved(1, payload)

    assert outcome["status"] == "app_deleted"
    assert state_actions.calls == []


async def test_unknown_app_returns_normally(
    publish_db, app_factory, deployment_factory, state_actions, audit_sink, approval_notifications
):
    _, _, _, payload = await _scene(app_factory, deployment_factory)
    payload["app_id"] = "no-such-app"

    assert (await _handler().on_approved(1, payload))["status"] == "app_deleted"


# ---------------------------------------------------------------------------
# The raise side
# ---------------------------------------------------------------------------


async def test_version_not_found_raises_16253(
    publish_db, app_factory, deployment_factory, state_actions, audit_sink, approval_notifications
):
    """Nothing to publish now or ever — that needs an administrator, so it raises."""
    from bisheng.common.errcode.app_publish import AppVersionNotFoundError

    _, _, _, payload = await _scene(app_factory, deployment_factory)
    payload["version_id"] = "no-such-version"

    with pytest.raises(AppVersionNotFoundError) as excinfo:
        await _handler().on_approved(1, payload)

    assert excinfo.value.Code == 16253


async def test_orchestrator_unreachable_raises(
    publish_db, app_factory, deployment_factory, state_actions, audit_sink, approval_notifications
):
    """The system is broken; the outbox's exception record is how somebody finds out."""
    from bisheng.common.errcode.app_factory import AppOrchestratorUnavailableError

    _, _, _, payload = await _scene(app_factory, deployment_factory)
    state_actions.responses["publish"] = AppOrchestratorUnavailableError()

    with pytest.raises(AppOrchestratorUnavailableError):
        await _handler().on_approved(1, payload)


async def test_state_conflict_raises(
    publish_db, app_factory, deployment_factory, state_actions, audit_sink, approval_notifications
):
    """A refused transition is a real conflict, not a parked app: it will not fix itself."""
    from bisheng.common.errcode.app_factory import AppStateConflictError

    _, _, _, payload = await _scene(app_factory, deployment_factory)
    state_actions.responses["stage_version"] = AppStateConflictError(app_id="app")

    with pytest.raises(AppStateConflictError):
        await _handler().on_approved(1, payload)


async def test_iteration_on_an_online_app_can_publish(publish_db, app_factory, deployment_factory, audit_sink):
    """An iteration of a running app must be publishable.

    This was pinned ``xfail(strict=True)`` while ``ALLOWED_TRANSITIONS`` had no
    ``online -> online`` edge: approval would pass and then ``_start`` raised
    16102, leaving the request ``execute_failed``. The edge landed 2026-08-17,
    so the assertion is live again.

    Deliberately exercises the *real* transition table rather than the
    fixture's stand-in — the gap was in the table, and a stub would hide it.
    """
    from bisheng.app_runtime.domain.constants import AppState, is_transition_allowed

    assert is_transition_allowed(AppState.ONLINE.value, AppState.ONLINE.value)
    # The neighbouring edges must not have been widened along with it: an online
    # application still may not be deleted without being stopped first (AC-42),
    # and that is the edge whose absence protects a running app from a stray
    # delete call.
    assert not is_transition_allowed(AppState.ONLINE.value, AppState.DELETED.value)


# ---------------------------------------------------------------------------
# Deployment bookkeeping
# ---------------------------------------------------------------------------


async def test_deployment_reaches_a_terminal_stage(
    publish_db, app_factory, deployment_factory, state_actions, audit_sink, approval_notifications
):
    """The CLI polls ``stage``; both outcomes are ``succeeded`` because the pipeline did its job."""
    from bisheng.app_publish.domain.models.app_deployment import AppDeploymentDao

    _, _, deployment, payload = await _scene(app_factory, deployment_factory)

    await _handler().on_approved(1, payload)

    async with publish_db() as session:
        row = await AppDeploymentDao.aget(session, deployment.id)
    assert (row.stage, row.status) == ("online", "succeeded")


async def test_parked_deployment_stage_is_pending_online(
    publish_db, app_factory, deployment_factory, state_actions, audit_sink, approval_notifications
):
    from bisheng.app_publish.domain.models.app_deployment import AppDeploymentDao

    _, _, deployment, payload = await _scene(app_factory, deployment_factory)
    state_actions.responses["publish"] = _result(state="pending_capacity", ok=False, detail={"stage": "admission"})

    await _handler().on_approved(1, payload)

    async with publish_db() as session:
        row = await AppDeploymentDao.aget(session, deployment.id)
    assert (row.stage, row.status) == ("pending_online", "succeeded")

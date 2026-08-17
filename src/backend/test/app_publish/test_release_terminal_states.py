"""T034 — rejected / withdrawn / cancelled, and the composition root (AC-33 / AC-34 / AC-35).

Three endings that are not "online". Each latches a version outcome, closes the
deployment attempt and writes one audit row; what this file mostly pins is what
they must **not** do:

* **They never touch the application state.** A rejected first release stays a
  draft; a rejected iteration keeps serving whatever it was serving. That is not
  enforced anywhere — it falls out of the fact that a release which was not
  approved never wrote ``pending_version_id``. Asserting it is how we notice if
  somebody "fixes" it into an explicit transition.
* **Cancellation writes no terminal state.** There is no fourth value, because a
  deleted application's version list is unreachable and the value would have no
  reader.
* **Cancellation notifies the approvers, not the applicant.** The applicant is
  the person who just pressed delete. Reusing ``cancel_exception_api`` here
  would notify exactly the wrong party and would not work anyway — it starts
  from an exception record, so it cannot touch a healthy pending request.

The composition-root tests are last and matter most in production: the hook is
what turns "the app was deleted" into "the approval task disappeared from the
approver's inbox", and it has to be installed in **both** the API process and
the Celery worker. Wiring one is the failure mode that passes every manual test.
"""

from __future__ import annotations

import ast
import pathlib

import pytest

from .conftest import OWNER_USER_ID, ROOT_TENANT_ID, SUPER_ADMIN_USER_ID

pytestmark = pytest.mark.asyncio

SCENARIO_CODE = "app_publish_request"


def _handler():
    from bisheng.app_publish.domain.services.app_publish_scenario_handler import AppPublishScenarioHandler

    return AppPublishScenarioHandler()


async def _scene(app_factory, deployment_factory, *, state: str = "draft"):
    from bisheng.app_publish.domain.models.app_deployment import STAGE_APPROVAL_CREATED, STATUS_WAITING_APPROVAL

    app, version = await app_factory(state=state, with_version=True)
    deployment = await deployment_factory(
        app_id=app.id,
        stage=STAGE_APPROVAL_CREATED,
        status=STATUS_WAITING_APPROVAL,
        version_id=version.id,
        tier_code="light",
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


async def _version(publish_db, app_id: str, version_id: str):
    from bisheng.database.models.app_version import AppVersionDao

    async with publish_db() as session:
        return await AppVersionDao.aget(session, app_id, version_id)


async def _app(publish_db, app_id: str):
    from bisheng.database.models.app import AppDao

    async with publish_db() as session:
        return await AppDao.aget(session, app_id)


async def _deployment(publish_db, deployment_id: str):
    from bisheng.app_publish.domain.models.app_deployment import AppDeploymentDao

    async with publish_db() as session:
        return await AppDeploymentDao.aget(session, deployment_id)


# ---------------------------------------------------------------------------
# AC-33 — rejected
# ---------------------------------------------------------------------------


async def test_reject_marks_version_rejected_and_keeps_app_state(
    publish_db, app_factory, deployment_factory, audit_sink
):
    """The version is latched; the draft stays a draft."""
    app, version, _, payload = await _scene(app_factory, deployment_factory)

    await _handler().on_rejected(1, payload, "缺少 README")

    assert (await _version(publish_db, app.id, version.id)).terminal_state == "rejected"
    assert (await _app(publish_db, app.id)).state == "draft"


async def test_reject_of_an_iteration_leaves_the_running_version_alone(
    publish_db, app_factory, deployment_factory, audit_sink
):
    """AC-33 for a live application: the current version keeps serving.

    True because a rejected release never wrote ``pending_version_id``, so
    ``pending ?? current`` still resolves to what is running.
    """
    app, version, _, payload = await _scene(app_factory, deployment_factory, state="online")

    await _handler().on_rejected(1, payload, "接口未鉴权")

    refreshed = await _app(publish_db, app.id)
    assert refreshed.state == "online"
    assert refreshed.pending_version_id is None
    assert refreshed.current_version_id == version.id


async def test_reject_reason_full_text_is_recorded(publish_db, app_factory, deployment_factory, audit_sink):
    """Kept whole, never truncated — a reason an owner cannot read is a resubmission."""
    reason = "本次发布被驳回：" + "详细说明 " * 40
    _, _, _, payload = await _scene(app_factory, deployment_factory)

    await _handler().on_rejected(1, payload, reason)

    rows = [call for call in audit_sink if call["action"] == "app.release.rejected"]
    assert len(rows) == 1
    assert rows[0]["reason"] == reason


async def test_reject_closes_the_deployment_with_a_codeless_failure(
    publish_db, app_factory, deployment_factory, audit_sink
):
    """``code`` is ``None``: a person decided against this, it did not fail a check.

    The CLI and the publish face both branch on ``failure.code``; giving a
    rejection a number would file it with the precheck failures.
    """
    _, _, deployment, payload = await _scene(app_factory, deployment_factory)

    await _handler().on_rejected(1, payload, "不通过")

    row = await _deployment(publish_db, deployment.id)
    assert row.status == "failed"
    assert row.stage == "approved"
    assert row.failure["code"] is None
    assert row.failure["details"]["reason"] == "approval_rejected"


async def test_resubmit_after_reject_is_allowed(publish_db, app_factory, deployment_factory, audit_sink):
    """Nothing is left in flight, so the next ``deploy`` passes both AC-03 gates."""
    from bisheng.app_publish.domain.services import publish_approval_service

    app, _, _, payload = await _scene(app_factory, deployment_factory)

    await _handler().on_rejected(1, payload, "不通过")

    assert await publish_approval_service.assert_submittable(app.id) is None


# ---------------------------------------------------------------------------
# AC-34 — withdrawn
# ---------------------------------------------------------------------------


async def test_withdraw_marks_version_withdrawn(publish_db, app_factory, deployment_factory, audit_sink):
    """Owner-only is already enforced by the engine, which refuses anybody but the applicant.

    A second owner check here would be a second source of truth for one rule.
    """
    app, version, _, payload = await _scene(app_factory, deployment_factory)

    await _handler().on_withdrawn(1, payload, None)

    assert (await _version(publish_db, app.id, version.id)).terminal_state == "withdrawn"
    assert "app.release.withdrawn" in [call["action"] for call in audit_sink]


async def test_withdraw_cannot_overwrite_an_online_version(publish_db, app_factory, deployment_factory, audit_sink):
    """A repeated withdraw must not relabel a version that already shipped (design 坑 4).

    The latch carries a ``terminal_state IS NULL`` predicate, so this is
    idempotent by construction rather than by a guard somebody has to remember.
    """
    app, version, _, payload = await _scene(app_factory, deployment_factory)
    from bisheng.app_publish.domain.services.version_service import VersionService

    await VersionService.mark_terminal_state(app.id, version.id, "online")

    await _handler().on_withdrawn(1, payload, None)

    assert (await _version(publish_db, app.id, version.id)).terminal_state == "online"


async def test_withdraw_then_resubmit_is_allowed(publish_db, app_factory, deployment_factory, audit_sink):
    from bisheng.app_publish.domain.services import publish_approval_service

    app, _, _, payload = await _scene(app_factory, deployment_factory)

    await _handler().on_withdrawn(1, payload, None)

    assert await publish_approval_service.assert_submittable(app.id) is None


# ---------------------------------------------------------------------------
# AC-35 — cancelled because the application was deleted
# ---------------------------------------------------------------------------


async def test_cancel_keeps_terminal_state_null(publish_db, app_factory, deployment_factory, audit_sink):
    """No fifth value: the version list of a deleted application is unreachable."""
    app, version, _, payload = await _scene(app_factory, deployment_factory)

    await _handler().on_cancelled(1, payload, "应用已删除")

    assert (await _version(publish_db, app.id, version.id)).terminal_state is None


async def test_cancel_audit_carries_app_id_and_version_no(publish_db, app_factory, deployment_factory, audit_sink):
    """The audit row is the entire record of what happened — it has to carry the identifiers."""
    app, version, deployment, payload = await _scene(app_factory, deployment_factory)

    await _handler().on_cancelled(1, payload, "应用已删除")

    rows = [call for call in audit_sink if call["action"] == "app.release.cancelled"]
    assert len(rows) == 1
    assert rows[0]["metadata"]["app_id"] == app.id
    assert rows[0]["metadata"]["version_no"] == version.version_no
    assert rows[0]["metadata"]["deployment_id"] == deployment.id
    assert rows[0]["target_type"] == "app_version"


async def test_app_deleted_cancels_active_instance_and_notifies_approvers(
    publish_db,
    app_factory,
    deployment_factory,
    approval_env,
    audit_sink,
    approval_notifications,
    super_admin_user,
):
    """The whole AC-35 path: submit → delete → the request is cancelled, approvers told.

    Deliberately **not** ``cancel_exception_api``: that one starts from an
    exception record and notifies the applicant — who is the person that just
    pressed delete, while the approvers keep a task pointing at nothing.
    """
    from bisheng.app_publish.composition import on_app_deleted
    from bisheng.app_publish.domain.services import publish_approval_service
    from bisheng.approval.domain.models.approval_instance import ApprovalInstanceStatus
    from bisheng.approval.domain.repositories.approval_instance_repository import ApprovalInstanceRepository

    app, _, deployment, _ = await _scene(app_factory, deployment_factory)
    result = await publish_approval_service.submit(deployment)
    approval_notifications.clear()

    await on_app_deleted(app_id=app.id, actor_user_id=OWNER_USER_ID, tenant_id=ROOT_TENANT_ID)

    instance = await ApprovalInstanceRepository.get_instance(result.instance_id)
    assert instance.status == ApprovalInstanceStatus.CANCELLED
    cancelled = [one for one in approval_notifications if one.get("action_code") == "approval_instance_cancelled"]
    assert len(cancelled) == 1
    assert cancelled[0]["receiver_user_ids"] == [SUPER_ADMIN_USER_ID]
    assert OWNER_USER_ID not in cancelled[0]["receiver_user_ids"]


async def test_cancelling_pending_tasks_closes_them(
    publish_db,
    app_factory,
    deployment_factory,
    approval_env,
    audit_sink,
    approval_notifications,
    super_admin_user,
):
    """An approver's inbox must not keep an item for an application that is gone."""
    from bisheng.app_publish.composition import on_app_deleted
    from bisheng.app_publish.domain.services import publish_approval_service
    from bisheng.approval.domain.models.approval_instance import ApprovalTaskStatus
    from bisheng.approval.domain.repositories.approval_instance_repository import ApprovalInstanceRepository

    app, _, deployment, _ = await _scene(app_factory, deployment_factory)
    result = await publish_approval_service.submit(deployment)

    await on_app_deleted(app_id=app.id, actor_user_id=OWNER_USER_ID, tenant_id=ROOT_TENANT_ID)

    tasks = await ApprovalInstanceRepository.list_tasks(result.instance_id)
    assert tasks
    assert {one.status for one in tasks} == {ApprovalTaskStatus.CANCELLED}


async def test_deleting_an_app_without_a_release_is_a_no_op(
    publish_db, app_factory, approval_env, audit_sink, approval_notifications
):
    """The ordinary case. Nothing open, nothing to cancel, no error."""
    from bisheng.app_publish.composition import on_app_deleted

    app, _ = await app_factory(with_version=False)

    await on_app_deleted(app_id=app.id, actor_user_id=OWNER_USER_ID, tenant_id=ROOT_TENANT_ID)

    assert approval_notifications == []


async def test_cancel_is_idempotent(
    publish_db,
    app_factory,
    deployment_factory,
    approval_env,
    audit_sink,
    approval_notifications,
    super_admin_user,
):
    """A second cancellation must not fire ``on_cancelled`` again.

    A business handler cannot tell a repeat from the first call, so the guard
    belongs in the approval module where the instance status is known.
    """
    from bisheng.app_publish.composition import on_app_deleted
    from bisheng.app_publish.domain.services import publish_approval_service

    app, _, deployment, _ = await _scene(app_factory, deployment_factory)
    await publish_approval_service.submit(deployment)

    await on_app_deleted(app_id=app.id, actor_user_id=OWNER_USER_ID, tenant_id=ROOT_TENANT_ID)
    approval_notifications.clear()
    await on_app_deleted(app_id=app.id, actor_user_id=OWNER_USER_ID, tenant_id=ROOT_TENANT_ID)

    assert approval_notifications == []


async def test_hook_failure_does_not_rollback_delete(publish_db, monkeypatch):
    """F054 collects hook failures instead of raising, and the deletion stands.

    By the time hooks run the container and the volume are gone; undoing the
    state change would leave "the app exists but its data does not". The read
    side therefore judges "was this cancelled" from the application's own state
    rather than trusting the hook arrived (design D10).
    """
    from bisheng.app_runtime.domain.services import lifecycle_hooks

    lifecycle_hooks.clear_app_deleted_hooks()

    async def _boom(**kwargs):
        raise RuntimeError("approval backend down")

    lifecycle_hooks.register_app_deleted_hook(_boom)
    try:
        failures = await lifecycle_hooks.on_app_deleted(app_id="app-1", actor_user_id=1, tenant_id=1)
    finally:
        lifecycle_hooks.clear_app_deleted_hooks()

    assert len(failures) == 1
    assert isinstance(failures[0], RuntimeError)


# ---------------------------------------------------------------------------
# The composition root
# ---------------------------------------------------------------------------


async def test_register_is_idempotent():
    """Both roots install the same subscriber; a re-initialising worker must not double it."""
    from bisheng.app_publish.composition import on_app_deleted, register
    from bisheng.app_runtime.domain.services import lifecycle_hooks

    lifecycle_hooks.clear_app_deleted_hooks()
    try:
        register()
        register()
        assert lifecycle_hooks._hooks.count(on_app_deleted) == 1
    finally:
        lifecycle_hooks.clear_app_deleted_hooks()


def _function_body(relative_path: str, function_name: str) -> ast.AST:
    """Parse one function out of a source file under ``bisheng/``.

    Reads the file rather than using ``inspect``: ``on_worker_init`` is
    decorated with a Celery signal's ``connect``, and under the test session
    that decorator hands back a ``MagicMock`` — from which no source can be
    recovered. Parsing what is on disk also asserts what actually ships, which
    is the point of a wiring guard.
    """
    import bisheng

    path = pathlib.Path(bisheng.__file__).parent / relative_path
    tree = ast.parse(path.read_text())
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == function_name:
            return node
    raise AssertionError(f"{relative_path} has no function named {function_name}")


def _calls_register(node: ast.AST) -> bool:
    """Whether the function body contains a call to the app_publish composition root."""
    for child in ast.walk(node):
        if isinstance(child, ast.Call):
            name = getattr(child.func, "id", None) or getattr(child.func, "attr", None)
            if name in {"register_app_publish", "_register_app_publish_composition"}:
                return True
    return False


async def test_composition_root_registered_in_both_api_and_worker():
    """Both processes, not one.

    The API process serves the detail page's delete button; the Celery worker
    runs the approval outbox and every task-triggered deletion. An API-only
    wiring is correct in every manual test and silently half-dead in
    production, leaving one ``_record_outbox_task_failure`` line behind.
    """
    assert _calls_register(_function_body("main.py", "lifespan")), (
        "bisheng/main.py lifespan does not register the app_publish composition root"
    )
    assert _calls_register(_function_body("worker/main.py", "on_worker_init")), (
        "bisheng/worker/main.py on_worker_init does not register the app_publish composition root"
    )


async def test_composition_registration_failure_does_not_stop_startup():
    """A registration failure is logged, never fatal: a backend that refuses to boot is worse."""
    for relative_path in ("main.py", "worker/main.py"):
        node = _function_body(relative_path, "_register_app_publish_composition")
        assert any(isinstance(child, ast.Try) for child in ast.walk(node)), (
            f"{relative_path} must not let a registration failure abort startup"
        )

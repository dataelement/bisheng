"""T036 — the publish face's read model and the manual-publish action (AC-32 / AC-38 / AC-62).

Two things are being guarded, and neither is about the happy path.

**"Both consumers return the same thing" is structural, not a promise.** AC-38
wants the publish face and F052's MCP status tool to agree; the way that is
guaranteed is that there is exactly one function. A test that called both and
compared would only prove they agreed on the day it ran.

**Refusals must not be 403 or 404.** The platform SPA's response interceptor
navigates the whole page to ``/403`` on either, so a non-owner opening somebody
else's application would lose the page instead of seeing a read-only block
(design 坑 22). Business errors ride inside the 200 envelope; that is what
makes them renderable, and it is why ``_require_viewer`` raises a
``BaseErrorCode`` rather than an ``HTTPException``.

Owner-only is checked twice on the action path — once to draw the button, once
to run it — because the permission runtime cannot express "only the owner" at
all: it short-circuits administrators to ALLOW, so a tenant admin would pass.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from .conftest import OWNER_USER_ID, ROOT_TENANT_ID, SUB_TENANT_ID, SUPER_ADMIN_USER_ID, TENANT_ADMIN_USER_ID

pytestmark = pytest.mark.asyncio


def _service():
    from bisheng.app_publish.domain.services.publish_status_service import PublishStatusService

    return PublishStatusService


def _actor(user_id: int, *, tenant_id: int = ROOT_TENANT_ID, is_global_super: bool = False):
    return SimpleNamespace(user_id=user_id, tenant_id=tenant_id, is_global_super=is_global_super)


@pytest.fixture()
def state_actions(monkeypatch):
    """Programmable ``manual_publish`` — a real one needs a live orchestrator."""
    from bisheng.app_runtime.domain.services.app_state_service import ActionResult, AppStateService

    calls: list[dict] = []
    responses: dict[str, object] = {"manual_publish": ActionResult(app_id="app", state="online", ok=True)}

    async def _manual(app_id, *, actor=None):
        calls.append({"app_id": app_id, "actor": actor})
        value = responses["manual_publish"]
        if isinstance(value, Exception):
            raise value
        return value

    monkeypatch.setattr(AppStateService, "manual_publish", staticmethod(_manual))
    return SimpleNamespace(calls=calls, responses=responses)


async def _parked(app_factory, deployment_factory, *, reason: str = "capacity"):
    """An application parked in ``pending_capacity`` with the attempt that parked it."""
    from bisheng.app_publish.domain.models.app_deployment import STAGE_PENDING_ONLINE, STATUS_SUCCEEDED

    app, version = await app_factory(state="pending_capacity", with_version=True)
    deployment = await deployment_factory(
        app_id=app.id,
        stage=STAGE_PENDING_ONLINE,
        status=STATUS_SUCCEEDED,
        version_id=version.id,
        tier_code="light",
        failure={
            "stage": STAGE_PENDING_ONLINE,
            "code": 16226 if reason == "capacity" else 16228,
            "message": "parked",
            "details": {"reason": reason},
            "hints": [],
        },
    )
    return app, version, deployment


# ---------------------------------------------------------------------------
# AC-38 — one implementation, one shape
# ---------------------------------------------------------------------------


async def test_status_service_is_single_implementation_for_ui_and_mcp():
    """Structural, not behavioural: there is one function, so two callers cannot diverge."""
    import inspect

    from bisheng.app_publish.domain.services import publish_status_service

    getters = [
        name
        for name, obj in inspect.getmembers(publish_status_service.PublishStatusService)
        if name.startswith("get_publish_status")
    ]
    assert getters == ["get_publish_status"]


async def test_status_shape_matches_contract(publish_db, app_factory, tier_seed):
    """Field for field against design §4.2 ② — both consumers are written to this."""
    app, _ = await app_factory(with_version=True)

    status = await _service().get_publish_status(app.id, actor=_actor(OWNER_USER_ID))

    assert set(status) == {
        "app_id",
        "app_state",
        "pending_reason",
        "current_version",
        "pending_version",
        "deployment",
        "approval",
        "tier",
        "capabilities",
        "schema_change",
        "can",
    }
    assert set(status["can"]) == {"withdraw", "manual_publish", "submit"}
    assert status["capabilities"] == []
    assert status["schema_change"] is None


async def test_status_reports_versions_and_tier(publish_db, app_factory, tier_seed):
    app, version = await app_factory(with_version=True)

    status = await _service().get_publish_status(app.id, actor=_actor(OWNER_USER_ID))

    assert status["current_version"]["version_id"] == version.id
    assert status["current_version"]["is_current"] is True
    assert status["pending_version"] is None
    assert status["tier"]["code"] == "light"


async def test_status_reports_pending_reason_capacity(publish_db, app_factory, deployment_factory, tier_seed):
    """ "待上线" is derived — from the app state plus the parked attempt's reason."""
    app, _, _ = await _parked(app_factory, deployment_factory, reason="capacity")

    status = await _service().get_publish_status(app.id, actor=_actor(OWNER_USER_ID))

    assert status["app_state"] == "pending_capacity"
    assert status["pending_reason"] == "capacity"


async def test_status_reports_pending_reason_deploy_failed(publish_db, app_factory, deployment_factory, tier_seed):
    """The other cause. Collapsing the two would send an owner to debug code that is fine."""
    app, _, _ = await _parked(app_factory, deployment_factory, reason="deploy_failed")

    status = await _service().get_publish_status(app.id, actor=_actor(OWNER_USER_ID))

    assert status["pending_reason"] == "deploy_failed"


async def test_running_app_has_no_pending_reason(publish_db, app_factory, deployment_factory, tier_seed):
    """A stale attempt must not make a healthy application look parked."""
    app, version = await app_factory(state="online", with_version=True)
    await deployment_factory(
        app_id=app.id,
        stage="pending_online",
        status="succeeded",
        version_id=version.id,
        failure={
            "stage": "pending_online",
            "code": 16226,
            "message": "",
            "details": {"reason": "capacity"},
            "hints": [],
        },
    )

    status = await _service().get_publish_status(app.id, actor=_actor(OWNER_USER_ID))

    assert status["pending_reason"] is None


async def test_status_returns_reject_reason_full_text(
    publish_db, app_factory, deployment_factory, approval_env, audit_sink, approval_notifications, super_admin_user
):
    """The rejection reason survives the decision — otherwise the owner cannot act on it."""
    from bisheng.app_publish.domain.services import publish_approval_service
    from bisheng.approval.domain.models.approval_instance import ApprovalInstanceStatus, ApprovalTaskStatus
    from bisheng.approval.domain.repositories.approval_instance_repository import ApprovalInstanceRepository

    reason = "驳回原因：" + "接口缺少鉴权。" * 30
    app, version = await app_factory(with_version=True)
    deployment = await deployment_factory(
        app_id=app.id, stage="precheck_probe", status="running", version_id=version.id, tier_code="light"
    )
    result = await publish_approval_service.submit(deployment)

    tasks = await ApprovalInstanceRepository.list_tasks(result.instance_id)
    tasks[0].status = ApprovalTaskStatus.REJECTED
    tasks[0].comment = reason
    await ApprovalInstanceRepository.update_task(tasks[0])
    instance = await ApprovalInstanceRepository.get_instance(result.instance_id)
    instance.status = ApprovalInstanceStatus.REJECTED
    await ApprovalInstanceRepository.update_instance(instance)

    status = await _service().get_publish_status(app.id, actor=_actor(OWNER_USER_ID))

    assert status["approval"]["reject_reason"] == reason
    assert status["approval"]["instance_id"] == result.instance_id


async def test_status_lists_approver_names(
    publish_db, app_factory, deployment_factory, approval_env, audit_sink, approval_notifications, super_admin_user
):
    from bisheng.app_publish.domain.services import publish_approval_service

    app, version = await app_factory(with_version=True)
    deployment = await deployment_factory(
        app_id=app.id, stage="precheck_probe", status="running", version_id=version.id, tier_code="light"
    )
    await publish_approval_service.submit(deployment)

    status = await _service().get_publish_status(app.id, actor=_actor(OWNER_USER_ID))

    assert status["approval"]["approver_names"] == ["f055-super-admin"]


async def test_deleted_app_status_reports_independently(publish_db, app_factory, tier_seed):
    """The read side judges "deleted" itself instead of trusting the deletion hook arrived.

    F054 records a hook failure and lets the deletion stand, so the publish face
    must not depend on the cancellation having been delivered (design D10).
    """
    app, _ = await app_factory(state="deleted", with_version=True)

    status = await _service().get_publish_status(app.id, actor=_actor(OWNER_USER_ID))

    assert status["app_state"] == "deleted"
    assert status["can"] == {"withdraw": False, "manual_publish": False, "submit": False}


async def test_missing_app_is_a_business_code_not_a_404(publish_db):
    """404 would navigate the whole SPA away from the detail page."""
    from bisheng.common.errcode.app_publish import AppPublishOwnerOnlyError

    with pytest.raises(AppPublishOwnerOnlyError) as excinfo:
        await _service().get_publish_status("no-such-app", actor=_actor(OWNER_USER_ID))

    assert excinfo.value.Code == 16254


# ---------------------------------------------------------------------------
# AC-62 — who may see what, and who may act
# ---------------------------------------------------------------------------


async def test_status_no_permission_returns_business_code_not_403(publish_db, app_factory, tier_seed):
    """A stranger gets a refusal it can render, not a page navigation."""
    from bisheng.common.errcode.app_publish import AppPublishOwnerOnlyError

    app, _ = await app_factory(with_version=True)

    with pytest.raises(AppPublishOwnerOnlyError) as excinfo:
        await _service().get_publish_status(app.id, actor=_actor(999999))

    assert excinfo.value.Code == 16254
    assert excinfo.value.kwargs["details"]["reason"] == "not_visible"


async def test_super_admin_can_view(publish_db, app_factory, tier_seed):
    app, _ = await app_factory(with_version=True)

    status = await _service().get_publish_status(app.id, actor=_actor(SUPER_ADMIN_USER_ID, is_global_super=True))

    assert status["app_id"] == app.id


async def test_tenant_admin_can_view_but_cannot_manual_publish(
    publish_db, app_factory, deployment_factory, tenant_admin_user, tier_seed, monkeypatch
):
    """The role matrix: viewing is wider than acting, and ``can`` says so.

    A tenant administrator passes every permission check there is, which is
    exactly why "only the owner may publish manually" cannot be a permission
    check.
    """
    from bisheng.app_publish.domain.services import publish_status_service
    from bisheng.common.errcode.app_publish import AppPublishOwnerOnlyError

    async def _is_tenant_admin(user_id: int, tenant_id: int) -> bool:
        return user_id == TENANT_ADMIN_USER_ID

    monkeypatch.setattr(publish_status_service, "check_tenant_admin", _is_tenant_admin)
    app, _, _ = await _parked(app_factory, deployment_factory)
    actor = _actor(TENANT_ADMIN_USER_ID, tenant_id=SUB_TENANT_ID)

    status = await _service().get_publish_status(app.id, actor=actor)
    assert status["app_id"] == app.id
    assert status["can"]["manual_publish"] is False
    assert status["can"]["withdraw"] is False

    with pytest.raises(AppPublishOwnerOnlyError):
        await _service().request_manual_publish(app.id, actor=actor)


async def test_can_flags_reflect_role_and_state(
    publish_db, app_factory, deployment_factory, approval_env, audit_sink, approval_notifications, super_admin_user
):
    """``withdraw`` needs an open request; ``manual_publish`` needs a parked app; ``submit`` is never true here."""
    from bisheng.app_publish.domain.services import publish_approval_service

    app, version = await app_factory(with_version=True)
    deployment = await deployment_factory(
        app_id=app.id, stage="precheck_probe", status="running", version_id=version.id, tier_code="light"
    )
    await publish_approval_service.submit(deployment)

    status = await _service().get_publish_status(app.id, actor=_actor(OWNER_USER_ID))

    assert status["can"]["withdraw"] is True
    assert status["can"]["manual_publish"] is False
    # AC-06: a CLI-imported application has no draft workspace to submit.
    assert status["can"]["submit"] is False


async def test_manual_publish_flag_true_only_when_parked(publish_db, app_factory, deployment_factory, tier_seed):
    app, _, _ = await _parked(app_factory, deployment_factory)

    status = await _service().get_publish_status(app.id, actor=_actor(OWNER_USER_ID))

    assert status["can"]["manual_publish"] is True


# ---------------------------------------------------------------------------
# AC-32 — manual publish
# ---------------------------------------------------------------------------


async def test_manual_publish_does_not_re_approve_and_marks_online(
    publish_db, app_factory, deployment_factory, state_actions, audit_sink, tier_seed
):
    """A success latches the same version ``online`` and creates **no** new version record."""
    from bisheng.database.models.app_version import AppVersionDao

    app, version, _ = await _parked(app_factory, deployment_factory)

    outcome = await _service().request_manual_publish(app.id, actor=_actor(OWNER_USER_ID))

    assert outcome["status"] == "online"
    async with publish_db() as session:
        rows = await AppVersionDao.alist_by_app(session, app.id)
        refreshed = await AppVersionDao.aget(session, app.id, version.id)
    assert len(rows) == 1, "manual publish must not produce a second version record"
    assert refreshed.terminal_state == "online"
    assert "app.release.manual_publish" in [call["action"] for call in audit_sink]


async def test_manual_publish_failure_keeps_pending_and_does_not_change_approval(
    publish_db, app_factory, deployment_factory, state_actions, audit_sink, approval_notifications, tier_seed
):
    """Still no room: the app stays parked, the version stays undecided, the approval is untouched."""
    from bisheng.app_runtime.domain.services.app_state_service import ActionResult
    from bisheng.database.models.app_version import AppVersionDao

    app, version, _ = await _parked(app_factory, deployment_factory)
    state_actions.responses["manual_publish"] = ActionResult(
        app_id=app.id, state="pending_capacity", ok=False, reason="capacity_exhausted", detail={"stage": "admission"}
    )

    outcome = await _service().request_manual_publish(app.id, actor=_actor(OWNER_USER_ID))

    assert outcome["status"] == "pending_capacity"
    async with publish_db() as session:
        refreshed = await AppVersionDao.aget(session, app.id, version.id)
    assert refreshed.terminal_state is None


async def test_manual_publish_owner_only_prefilter_not_permission_runtime(
    publish_db, app_factory, deployment_factory, state_actions, audit_sink, tier_seed
):
    """A super admin is refused — which no permission check could ever do.

    The runtime short-circuits ``is_global_super`` to ALLOW before ReBAC is
    consulted, so an owner-only rule expressed there would be a rule that never
    fires.
    """
    from bisheng.common.errcode.app_publish import AppPublishOwnerOnlyError

    app, _, _ = await _parked(app_factory, deployment_factory)

    with pytest.raises(AppPublishOwnerOnlyError) as excinfo:
        await _service().request_manual_publish(app.id, actor=_actor(SUPER_ADMIN_USER_ID, is_global_super=True))

    assert excinfo.value.Code == 16254
    assert state_actions.calls == []


async def test_manual_publish_acts_before_asking_the_client(
    publish_db, app_factory, deployment_factory, state_actions, audit_sink, tier_seed
):
    """The action re-checks ownership itself rather than trusting the ``can`` flag it emitted."""
    import inspect

    from bisheng.app_publish.domain.services.publish_status_service import PublishStatusService

    source = inspect.getsource(PublishStatusService.request_manual_publish)

    assert "_is_owner" in source


# ---------------------------------------------------------------------------
# F053 T034 write-back 2 — runtime_hint decorates the log payload
# ---------------------------------------------------------------------------


async def test_runtime_hint_reports_state_so_empty_logs_are_explainable(publish_db, app_factory):
    """An empty ``lines`` has two causes and the log text cannot tell them apart.

    Either the app is running and quiet, or it has no running instance at all.
    Printing "no logs" for both reads as a broken log query and sends the owner
    off to check the wrong thing.
    """
    from bisheng.app_publish.domain.services.publish_status_service import PublishStatusService

    app_row, _ = await app_factory()

    hint = await PublishStatusService.runtime_hint(app_row.id)

    assert hint["app_state"] == app_row.state
    assert set(hint) == {"app_state", "pending_reason"}


async def test_runtime_hint_never_breaks_the_payload_it_decorates(publish_db):
    """A hint that cannot be produced must not take down the log response.

    The logs themselves are the answer; the hint is decoration. Raising here
    would turn "your app printed nothing yet" into "the log endpoint is
    broken" — strictly worse than the missing hint.
    """
    from bisheng.app_publish.domain.services.publish_status_service import PublishStatusService

    hint = await PublishStatusService.runtime_hint("no-such-app-id")

    assert hint == {"app_state": None, "pending_reason": None}

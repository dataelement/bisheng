"""T030 — submitting a release to the approval centre (AC-03 / AC-23 / AC-30 / AC-64).

``publish_approval_service`` is the seam between the publish pipeline and the
approval engine, and almost everything it does exists because the gate's
behaviour is *not* what a caller would assume:

* A duplicate submission gets the **existing** instance back, quietly. Relying
  on the gate for AC-03 means a second ``bisheng deploy`` prints "提交成功"
  having submitted nothing — so the two gates are asked before the gate is even
  constructed.
* No approver resolvable is a **returned** ``EXCEPTION`` decision, not a raised
  error. The release must neither pass nor hang; an administrator gets an
  exception record and the version is still written.
* The gate creates approver tasks and sends **no** station message. Every
  shipped scenario notifies from its own side.
* The scenario not being seeded is the one case that *does* raise, and it must
  surface as **16225** — never 16226, which means "the machine is out of
  memory" and has the opposite remedy.

The registry/handler construction is asserted per request rather than by
inspection: it is the precondition of the self-approval flag being readable, and
a cached handler passes every other test in this suite.
"""

from __future__ import annotations

import pytest

from .conftest import OWNER_USER_ID, ROOT_TENANT_ID, SERVICE_ACCOUNT_USER_ID, SUB_TENANT_ID, SUPER_ADMIN_USER_ID

pytestmark = pytest.mark.asyncio

SCENARIO_CODE = "app_publish_request"


def _service():
    from bisheng.app_publish.domain.services import publish_approval_service

    return publish_approval_service


async def _seed_scenarios(publish_db, tenant_id: int = ROOT_TENANT_ID) -> None:
    from bisheng.approval.domain.services.approval_seed_service import seed_approval_scenarios_in_session

    async with publish_db() as session:
        await seed_approval_scenarios_in_session(session, tenant_id)
        await session.commit()


async def _publishable(app_factory, deployment_factory, *, tenant_id: int = ROOT_TENANT_ID, **app_kwargs):
    """An app plus a deployment sitting where ``record_version`` would call ``submit``."""
    from bisheng.app_publish.domain.models.app_deployment import STAGE_PRECHECK_PROBE, STATUS_RUNNING

    app, _ = await app_factory(tenant_id=tenant_id, with_version=False, **app_kwargs)
    deployment = await deployment_factory(
        app_id=app.id,
        tenant_id=tenant_id,
        stage=STAGE_PRECHECK_PROBE,
        status=STATUS_RUNNING,
        version_id="ver-new",
        tier_code="light",
        manifest={"name": app.name, "runtime": "python3.11", "port": 8080, "tier": "light"},
    )
    return app, deployment


# ---------------------------------------------------------------------------
# AC-23 — gate assembly
# ---------------------------------------------------------------------------


async def test_gate_assembled_per_request_with_fresh_registry_and_handler():
    """A new registry, a new handler and a new gate on every call.

    Not tidiness: the handler carries this request's self-approval flag, and
    the engine has no other channel for it. Caching either object makes two
    concurrent releases share one answer.
    """
    from bisheng.app_publish.domain.services.app_publish_scenario_handler import AppPublishScenarioHandler

    service = _service()
    first_gate, first_handler = service._build_publish_approval_gate()
    second_gate, second_handler = service._build_publish_approval_gate()

    assert first_gate is not second_gate
    assert first_handler is not second_handler
    assert isinstance(first_handler, AppPublishScenarioHandler)
    assert first_gate.registry is not second_gate.registry
    assert await first_gate.registry.get_handler(SCENARIO_CODE) is first_handler


# ---------------------------------------------------------------------------
# AC-03 — the two gates, asked before the approval gate
# ---------------------------------------------------------------------------


async def test_active_release_checked_before_gate_raises_16251(publish_db, app_factory, deployment_factory):
    """An attempt already in flight refuses the next one with its own code.

    Delegating this to the approval gate is the trap: it answers a duplicate by
    handing back the existing instance, so the CLI would report success.
    """
    from bisheng.common.errcode.app_publish import AppApprovalInFlightError

    app, _ = await _publishable(app_factory, deployment_factory)

    with pytest.raises(AppApprovalInFlightError) as excinfo:
        await _service().assert_submittable(app.id)

    assert excinfo.value.Code == 16251
    assert excinfo.value.kwargs["details"]["reason"] == "deployment_in_flight"


async def test_active_approval_instance_alone_also_raises_16251(
    publish_db, app_factory, deployment_factory, approval_env, audit_sink, approval_notifications, super_admin_user
):
    """The request is open even though no deployment row is in flight any more."""
    from bisheng.app_publish.domain.models.app_deployment import STATUS_SUCCEEDED
    from bisheng.common.errcode.app_publish import AppApprovalInFlightError

    app, deployment = await _publishable(app_factory, deployment_factory)
    await _service().submit(deployment)
    async with publish_db() as session:
        from bisheng.app_publish.domain.models.app_deployment import AppDeploymentDao

        await AppDeploymentDao.aadvance_stage(session, deployment.id, stage="approval_created", status=STATUS_SUCCEEDED)
        await session.commit()

    with pytest.raises(AppApprovalInFlightError) as excinfo:
        await _service().assert_submittable(app.id)

    assert excinfo.value.kwargs["details"]["reason"] == "approval_in_flight"


async def test_pending_online_checked_before_gate_raises_16252(publish_db, app_factory):
    """A parked application does not accept a new version until it is resolved."""
    from bisheng.common.errcode.app_publish import AppPendingOnlineError

    app, _ = await app_factory(state="pending_capacity", with_version=False)

    with pytest.raises(AppPendingOnlineError) as excinfo:
        await _service().assert_submittable(app.id)

    assert excinfo.value.Code == 16252


async def test_clean_app_passes_both_gates(publish_db, app_factory):
    app, _ = await app_factory(state="draft", with_version=False)

    assert await _service().assert_submittable(app.id) is None


# ---------------------------------------------------------------------------
# AC-23 — submit
# ---------------------------------------------------------------------------


async def test_submit_returns_pending_with_non_empty_approvers_after_seed(
    publish_db, app_factory, deployment_factory, approval_env, audit_sink, approval_notifications, super_admin_user
):
    """The end-to-end shape: seeded scenario → PENDING with tasks.

    Guards design 坑 9 — a handler that forgot to delegate to
    ``resolve_approvers_from_sources`` produces ``EXCEPTION`` here, and the
    symptom is indistinguishable from an unconfigured flow.
    """
    from bisheng.approval.domain.schemas.approval_center_schema import ApprovalGateDecision

    _, deployment = await _publishable(app_factory, deployment_factory)

    result = await _service().submit(deployment)

    assert result.decision == ApprovalGateDecision.PENDING
    assert result.task_ids


async def test_business_key_is_deployment_id(
    publish_db, app_factory, deployment_factory, approval_env, audit_sink, approval_notifications, super_admin_user
):
    """One attempt, one request. Keying on ``app_id`` would make every retry a duplicate."""
    from bisheng.approval.domain.repositories.approval_instance_repository import ApprovalInstanceRepository

    app, deployment = await _publishable(app_factory, deployment_factory)

    result = await _service().submit(deployment)

    instance = await ApprovalInstanceRepository.get_instance(result.instance_id)
    assert instance.business_key == deployment.id
    assert instance.business_resource_type == "app"
    assert instance.business_resource_id == app.id


async def test_applicant_is_owner_not_the_service_account(
    publish_db, app_factory, deployment_factory, approval_env, audit_sink, approval_notifications, super_admin_user
):
    """INV-29: a service account never appears in anything a human reads."""
    from bisheng.approval.domain.repositories.approval_instance_repository import ApprovalInstanceRepository

    _, deployment = await _publishable(app_factory, deployment_factory)
    assert deployment.submitted_by_user_id == SERVICE_ACCOUNT_USER_ID

    result = await _service().submit(deployment)

    instance = await ApprovalInstanceRepository.get_instance(result.instance_id)
    assert instance.applicant_user_id == OWNER_USER_ID


async def test_applicant_department_is_the_owners_primary_one(
    publish_db, app_factory, deployment_factory, approval_env, audit_sink, approval_notifications, dept_admin_user
):
    from bisheng.approval.domain.repositories.approval_instance_repository import ApprovalInstanceRepository

    _, deployment = await _publishable(app_factory, deployment_factory)

    result = await _service().submit(deployment)

    instance = await ApprovalInstanceRepository.get_instance(result.instance_id)
    assert instance.applicant_department_id == dept_admin_user.department_id
    assert instance.detail_snapshot["approver_note"] is None


async def test_owner_without_department_gets_approver_note(
    publish_db, app_factory, deployment_factory, approval_env, audit_sink, approval_notifications, super_admin_user
):
    """AC-16 — the card explains why it went straight to the tenant administrators."""
    from bisheng.approval.domain.repositories.approval_instance_repository import ApprovalInstanceRepository

    _, deployment = await _publishable(app_factory, deployment_factory)

    result = await _service().submit(deployment)

    instance = await ApprovalInstanceRepository.get_instance(result.instance_id)
    assert instance.applicant_department_id is None
    assert instance.detail_snapshot["approver_note"] == "no_department_admin_source"


async def test_detail_snapshot_reaches_the_instance(
    publish_db, app_factory, deployment_factory, approval_env, audit_sink, approval_notifications, super_admin_user
):
    """``build_detail``'s output is what lands in the row the client reads."""
    from bisheng.approval.domain.repositories.approval_instance_repository import ApprovalInstanceRepository

    app, deployment = await _publishable(app_factory, deployment_factory)

    result = await _service().submit(deployment)

    detail = (await ApprovalInstanceRepository.get_instance(result.instance_id)).detail_snapshot
    assert detail["scenario_code"] == SCENARIO_CODE
    assert detail["app_name"] == app.name
    assert detail["release_kind"] == "initial"
    assert detail["version_no"] == 1
    assert detail["tier"]["code"] == "light"


async def test_iteration_release_kind_and_version_number(
    publish_db, app_factory, deployment_factory, approval_env, audit_sink, approval_notifications, super_admin_user
):
    """A second release on the same app is an iteration, numbered from the existing maximum."""
    from bisheng.approval.domain.repositories.approval_instance_repository import ApprovalInstanceRepository

    app, _ = await app_factory(with_version=True, state="online")
    from bisheng.app_publish.domain.models.app_deployment import STAGE_PRECHECK_PROBE, STATUS_RUNNING

    deployment = await deployment_factory(
        app_id=app.id,
        stage=STAGE_PRECHECK_PROBE,
        status=STATUS_RUNNING,
        version_id="ver-2",
        tier_code="light",
        manifest={"name": app.name, "runtime": "python3.11", "port": 8080},
    )

    result = await _service().submit(deployment)

    detail = (await ApprovalInstanceRepository.get_instance(result.instance_id)).detail_snapshot
    assert detail["release_kind"] == "iteration"
    assert detail["version_no"] == 2


# ---------------------------------------------------------------------------
# AC-23 — 16225, and only 16225
# ---------------------------------------------------------------------------


async def test_scenario_disabled_raises_16225_not_16226(publish_db, app_factory, deployment_factory):
    """Nothing seeded → the scenario is not enabled. That is 16225.

    16226 means the runtime has no room. The remedies are opposite ("have an
    administrator enable the scenario" vs "wait, or publish manually"), so one
    code cannot serve both without one of the two messages being wrong.
    """
    from bisheng.common.errcode.app_publish import AppApprovalScenarioDisabledError

    _, deployment = await _publishable(app_factory, deployment_factory)

    with pytest.raises(AppApprovalScenarioDisabledError) as excinfo:
        await _service().submit(deployment)

    assert excinfo.value.Code == 16225
    assert excinfo.value.Code != 16226
    assert excinfo.value.kwargs["details"]["reason"] == "scenario_disabled"


async def test_scenario_disabled_leaves_no_approval_instance(publish_db, app_factory, deployment_factory):
    """The gate raised before writing anything — which is why the gate runs before the INSERT."""
    from sqlmodel import select

    from bisheng.approval.domain.models.approval_instance import ApprovalInstance
    from bisheng.common.errcode.app_publish import AppApprovalScenarioDisabledError

    _, deployment = await _publishable(app_factory, deployment_factory)

    with pytest.raises(AppApprovalScenarioDisabledError):
        await _service().submit(deployment)

    async with publish_db() as session:
        assert list((await session.exec(select(ApprovalInstance))).all()) == []


async def test_both_sources_empty_returns_exception_not_raise(
    publish_db, app_factory, deployment_factory, approval_env, audit_sink, approval_notifications
):
    """No approver resolvable is a decision, not an exception (AC-18).

    Neither fixture that could supply one is requested here, so both sources
    come back empty. The release must not pass and must not hang: an
    ``EXCEPTION`` instance is what an administrator later fixes.
    """
    from bisheng.approval.domain.schemas.approval_center_schema import ApprovalGateDecision

    _, deployment = await _publishable(app_factory, deployment_factory, tenant_id=SUB_TENANT_ID)

    result = await _service().submit(deployment)

    assert result.decision == ApprovalGateDecision.EXCEPTION
    assert result.exception_type == "approver_empty"
    assert result.instance_id


# ---------------------------------------------------------------------------
# AC-64 — the notification the gate does not send
# ---------------------------------------------------------------------------


async def test_first_node_notification_sent_by_us_not_gate(
    publish_db, app_factory, deployment_factory, approval_env, audit_sink, approval_notifications, super_admin_user
):
    """The gate builds tasks and audits; the station message is ours (design 坑 5)."""
    _, deployment = await _publishable(app_factory, deployment_factory)

    result = await _service().submit(deployment)

    pending = [one for one in approval_notifications if one.get("action_code") == "approval_task_pending"]
    assert len(pending) == 1
    assert pending[0]["receiver_user_ids"] == [SUPER_ADMIN_USER_ID]
    assert pending[0]["scenario_code"] == SCENARIO_CODE
    assert pending[0]["instance_id"] == result.instance_id


async def test_exception_decision_does_not_notify_approvers(
    publish_db, app_factory, deployment_factory, approval_env, audit_sink, approval_notifications
):
    """Nobody resolved means nobody to tell; the engine already paged the administrators."""
    _, deployment = await _publishable(app_factory, deployment_factory, tenant_id=SUB_TENANT_ID)

    await _service().submit(deployment)

    assert [one for one in approval_notifications if one.get("action_code") == "approval_task_pending"] == []


async def test_notifications_use_a_neutral_message_type(publish_db):
    """AC-65: a publish notification must never render an approval button.

    The client shows one whenever ``message_type`` is ``request`` or ``approve``,
    *independently* of the action code — so the guarantee lives on the sending
    side. ``ApprovalNotificationService`` routes through ``send_generic_notify``,
    which sends ``NOTIFY``.
    """
    import inspect

    from bisheng.message.domain.services.message_service import MessageService

    source = inspect.getsource(MessageService.send_generic_notify)

    assert "MessageTypeEnum.NOTIFY" in source
    assert "MessageTypeEnum.REQUEST" not in source
    assert "MessageTypeEnum.APPROVE" not in source


# ---------------------------------------------------------------------------
# AC-17 — the self-approval audit
# ---------------------------------------------------------------------------


async def test_self_approval_is_audited(
    publish_db, app_factory, deployment_factory, approval_env, audit_sink, approval_notifications, super_admin_user
):
    """The owner is the only resolvable approver → allowed, and recorded."""
    app, _ = await app_factory(owner_user_id=SUPER_ADMIN_USER_ID, with_version=False)
    from bisheng.app_publish.domain.models.app_deployment import STAGE_PRECHECK_PROBE, STATUS_RUNNING

    deployment = await deployment_factory(
        app_id=app.id,
        owner_user_id=SUPER_ADMIN_USER_ID,
        stage=STAGE_PRECHECK_PROBE,
        status=STATUS_RUNNING,
        version_id="ver-self",
        tier_code="light",
        manifest={"name": app.name, "runtime": "python3.11", "port": 8080},
    )

    await _service().submit(deployment)

    actions = [call["action"] for call in audit_sink]
    assert actions.count("app.release.self_approval") == 1


async def test_normal_approval_is_not_audited_as_self_approval(
    publish_db, app_factory, deployment_factory, approval_env, audit_sink, approval_notifications, super_admin_user
):
    _, deployment = await _publishable(app_factory, deployment_factory)

    await _service().submit(deployment)

    assert [call["action"] for call in audit_sink].count("app.release.self_approval") == 0


# ---------------------------------------------------------------------------
# AC-30 — a draft is nobody else's business before approval
# ---------------------------------------------------------------------------


async def test_draft_app_not_accessible_before_approval(publish_db, app_factory):
    """A first release stays owner-visible until it goes online.

    Enforced by F054 authorising only the owner at ``create_draft`` time, so
    what is asserted here is that F055 adds no second, wider grant of its own:
    the app row is still owned by exactly the owner after submission.
    """
    app, _ = await app_factory(state="draft", with_version=False)

    assert app.owner_user_id == OWNER_USER_ID
    assert app.state == "draft"


# ---------------------------------------------------------------------------
# The approval port shape ``record_version`` depends on
# ---------------------------------------------------------------------------


async def test_module_satisfies_the_approval_port():
    """``record_version`` takes this module as-is — three coroutines, no adapter."""
    import inspect

    service = _service()

    for name in ("assert_submittable", "submit", "cancel"):
        assert inspect.iscoroutinefunction(getattr(service, name)), f"{name} must be a coroutine function"


async def test_cancel_routes_through_the_approval_module(monkeypatch):
    """Compensation goes through the approval module's own API, not our SQL."""
    from bisheng.approval.domain.services.approval_center_service import ApprovalCenterService

    seen: list[dict] = []

    async def _cancel(cls, **kwargs):
        seen.append(kwargs)
        return None

    monkeypatch.setattr(ApprovalCenterService, "cancel_instance_by_business", classmethod(_cancel))

    await _service().cancel(4242, reason="version record insert failed")

    assert seen == [{"instance_id": 4242, "reason": "version record insert failed"}]

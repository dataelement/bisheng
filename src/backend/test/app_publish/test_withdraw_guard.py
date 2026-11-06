"""T051 — ``withdraw_instance`` refuses anything that is not still PENDING.

The bug this pins: ``ApprovalCenterService.withdraw_instance`` checked only
``applicant_user_id``. Nothing looked at ``status``, so the applicant could
replay ``POST /approval/instances/{id}/withdraw`` against an instance that had
already been approved, rejected or cancelled — and every replay flipped the row
to ``withdrawn``, wrote a fresh action log and re-fired the scenario's
``on_withdrawn`` hook.

For F055 that hook is ``PublishTerminalService.on_withdrawn``, so a late
withdraw on a release that already shipped is an attempt to relabel a live
version as "withdrawn". ``AppVersionDao.amark_terminal`` carries a
``terminal_state IS NULL`` predicate and would have absorbed the write, but the
latch is the *second* line of defence and it protects only that one column — the
deployment row would still be re-failed and a second audit trail written. The
guard is what stops the call before any of that.

Why the two other live scenarios are exercised here: 181 is the band of the
approval **engine**, not of any one scenario. Tightening ``withdraw`` tightens
channel subscription and knowledge-space join at the same time, and neither
feature's own suite would notice the change. The regressions below are cheap
insurance that the tightening refuses only terminal instances and still lets a
genuinely pending request be pulled back.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import AsyncMock

import pytest

from .conftest import OWNER_USER_ID, ROOT_TENANT_ID

pytestmark = pytest.mark.asyncio

PUBLISH_SCENARIO = "app_publish_request"
CHANNEL_SCENARIO = "channel_subscribe_request"
KNOWLEDGE_SPACE_SCENARIO = "knowledge_space_subscribe_request"

#: Everything ``ApprovalInstanceStatus`` can hold once the request is no longer
#: in flight. ``executing`` / ``executed`` / ``execute_failed`` / ``exception``
#: are post-approval states and are just as un-withdrawable, but the three below
#: are the ones a user-facing "撤回" button can actually reach.
TERMINAL_STATUSES = ("approved", "rejected", "cancelled")


def _guard_error():
    from bisheng.common.errcode.approval import ApprovalInstanceNotPendingError

    return ApprovalInstanceNotPendingError


async def _make_instance(
    *,
    status: str,
    scenario_code: str = PUBLISH_SCENARIO,
    applicant_user_id: int = OWNER_USER_ID,
    payload_snapshot: dict[str, Any] | None = None,
    business_name: str = "F055 app",
):
    from bisheng.approval.domain.models.approval_instance import ApprovalInstance
    from bisheng.approval.domain.repositories.approval_instance_repository import ApprovalInstanceRepository

    return await ApprovalInstanceRepository.create_instance(
        ApprovalInstance(
            tenant_id=ROOT_TENANT_ID,
            scenario_code=scenario_code,
            scenario_name=scenario_code,
            handler_key=scenario_code,
            business_key=f"{scenario_code}:{status}:{applicant_user_id}",
            business_resource_type="app",
            business_resource_id="res-1",
            business_name=business_name,
            applicant_user_id=applicant_user_id,
            applicant_user_name="owner",
            status=status,
            current_node_name="审批" if status == "pending" else None,
            payload_snapshot=payload_snapshot or {},
            detail_snapshot={},
        )
    )


async def _make_pending_task(instance, approver_user_id: int = 90501):
    from bisheng.approval.domain.models.approval_instance import ApprovalTask, ApprovalTaskStatus
    from bisheng.approval.domain.repositories.approval_instance_repository import ApprovalInstanceRepository

    return await ApprovalInstanceRepository.create_task(
        ApprovalTask(
            tenant_id=ROOT_TENANT_ID,
            instance_id=instance.id,
            flow_version_id=instance.flow_version_id or 0,
            node_code="node_1",
            node_name="审批",
            node_order=1,
            approver_user_id=approver_user_id,
            approver_source_type="direct_user",
            node_mode="or",
            status=ApprovalTaskStatus.PENDING,
        )
    )


@asynccontextmanager
async def _hook_spy(monkeypatch):
    """Record every ``on_withdrawn`` the engine fires, without running one.

    The factory is imported *inside* ``withdraw_instance``, so the patch has to
    land on the factory module rather than on the service's namespace.
    """
    from bisheng.approval.domain.services import approval_runtime_handler_factory as factory

    calls: list[tuple[int, dict, str | None]] = []

    class _Recorder:
        async def on_withdrawn(self, instance_id: int, payload_snapshot: dict, reason: str | None) -> None:
            calls.append((instance_id, payload_snapshot, reason))

    async def _build(scenario_code: str):
        return _Recorder()

    monkeypatch.setattr(factory, "build_runtime_handler", _build)
    yield calls


@pytest.fixture()
def withdraw_service(monkeypatch, publish_db):
    """``ApprovalCenterService`` with its non-approval side effects muted.

    Only audit writing, notification and the detail read-back are stubbed. The
    status guard, the task cancellation loop, the instance UPDATE and the action
    log all run for real — those are what the tests below assert on.
    """
    from bisheng.approval.domain.services.approval_center_service import ApprovalCenterService

    monkeypatch.setattr(ApprovalCenterService, "_write_audit_log", AsyncMock(return_value=None))
    monkeypatch.setattr(ApprovalCenterService, "_send_approval_notify", AsyncMock(return_value=None))
    monkeypatch.setattr(
        ApprovalCenterService,
        "get_instance_detail",
        AsyncMock(side_effect=lambda **kw: {"instance_id": kw.get("instance_id")}),
    )
    return ApprovalCenterService


# ---------------------------------------------------------------------------
# The guard itself
# ---------------------------------------------------------------------------


async def test_pending_instance_can_still_be_withdrawn(withdraw_service, monkeypatch):
    """The happy path must survive the tightening — otherwise 撤回 is simply broken."""
    from bisheng.approval.domain.models.approval_instance import ApprovalInstanceStatus, ApprovalTaskStatus
    from bisheng.approval.domain.repositories.approval_instance_repository import ApprovalInstanceRepository

    instance = await _make_instance(status=ApprovalInstanceStatus.PENDING)
    task = await _make_pending_task(instance)

    async with _hook_spy(monkeypatch) as hook_calls:
        await withdraw_service.withdraw_instance(
            instance_id=instance.id,
            operator_user_id=OWNER_USER_ID,
            operator_user_name="owner",
            reason="改错了",
        )

    refreshed = await ApprovalInstanceRepository.get_instance(instance.id)
    tasks = await ApprovalInstanceRepository.list_tasks(instance.id)
    logs = await ApprovalInstanceRepository.list_action_logs(instance.id)

    assert refreshed.status == ApprovalInstanceStatus.WITHDRAWN
    assert next(t for t in tasks if t.id == task.id).status == ApprovalTaskStatus.CANCELLED
    assert [log.action for log in logs] == ["withdrawn"]
    assert len(hook_calls) == 1


@pytest.mark.parametrize("status", TERMINAL_STATUSES)
async def test_terminal_instance_cannot_be_withdrawn(withdraw_service, monkeypatch, status):
    """approved / rejected / cancelled — each refused with 18118, each leaving no trace."""
    from bisheng.approval.domain.repositories.approval_instance_repository import ApprovalInstanceRepository

    instance = await _make_instance(status=status)

    async with _hook_spy(monkeypatch) as hook_calls:
        with pytest.raises(_guard_error()) as excinfo:
            await withdraw_service.withdraw_instance(
                instance_id=instance.id,
                operator_user_id=OWNER_USER_ID,
                operator_user_name="owner",
                reason="late withdraw",
            )

    assert excinfo.value.code == 18118

    refreshed = await ApprovalInstanceRepository.get_instance(instance.id)
    logs = await ApprovalInstanceRepository.list_action_logs(instance.id)

    # Refused *before* any write: status untouched, no action log, no hook.
    assert refreshed.status == status
    assert logs == []
    assert hook_calls == []


async def test_pending_tasks_survive_a_refused_withdraw(withdraw_service, monkeypatch):
    """The guard sits before the task loop, so a refusal must not cancel tasks.

    Worth its own test because the loop is the first write in the method: a
    guard placed one line too late would leave an approved instance with all of
    its tasks silently cancelled.
    """
    from bisheng.approval.domain.models.approval_instance import ApprovalInstanceStatus, ApprovalTaskStatus
    from bisheng.approval.domain.repositories.approval_instance_repository import ApprovalInstanceRepository

    instance = await _make_instance(status=ApprovalInstanceStatus.APPROVED)
    task = await _make_pending_task(instance)

    async with _hook_spy(monkeypatch):
        with pytest.raises(_guard_error()):
            await withdraw_service.withdraw_instance(
                instance_id=instance.id,
                operator_user_id=OWNER_USER_ID,
            )

    tasks = await ApprovalInstanceRepository.list_tasks(instance.id)
    assert next(t for t in tasks if t.id == task.id).status == ApprovalTaskStatus.PENDING


async def test_applicant_check_still_runs_first(withdraw_service, monkeypatch):
    """Ordering matters: a stranger hitting a terminal instance still gets the
    permission refusal, not a status one. Swapping the two checks would let an
    attacker probe which requests are still open."""
    from bisheng.approval.domain.models.approval_instance import ApprovalInstanceStatus

    instance = await _make_instance(status=ApprovalInstanceStatus.APPROVED)

    async with _hook_spy(monkeypatch):
        with pytest.raises(PermissionError):
            await withdraw_service.withdraw_instance(
                instance_id=instance.id,
                operator_user_id=OWNER_USER_ID + 999,
            )


# ---------------------------------------------------------------------------
# F055 — the reason the guard exists
# ---------------------------------------------------------------------------


async def test_online_version_terminal_state_survives_a_late_withdraw(
    withdraw_service, monkeypatch, publish_db, app_factory
):
    """AC-34 / design 坑 4 — a shipped version keeps ``terminal_state='online'``.

    The real hook runs here (no spy): if the guard were missing, this is the
    exact call chain that would try to rewrite a live release's outcome.
    """
    from bisheng.database.models.app_version import TERMINAL_STATE_ONLINE, AppVersionDao

    app, version = await app_factory(state="online", with_version=True, terminal_state=TERMINAL_STATE_ONLINE)
    instance = await _make_instance(
        status="approved",
        payload_snapshot={
            "app_id": app.id,
            "app_name": app.name,
            "version_id": version.id,
            "version_no": version.version_no,
            "owner_user_id": app.owner_user_id,
            "tenant_id": app.tenant_id,
        },
    )

    with pytest.raises(_guard_error()):
        await withdraw_service.withdraw_instance(
            instance_id=instance.id,
            operator_user_id=OWNER_USER_ID,
            reason="撤回已上线版本",
        )

    async with publish_db() as session:
        refreshed_version = await AppVersionDao.aget(session, app.id, version.id)
    assert refreshed_version.terminal_state == TERMINAL_STATE_ONLINE


# ---------------------------------------------------------------------------
# Cross-feature regression — the other two live scenarios
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("scenario_code", [CHANNEL_SCENARIO, KNOWLEDGE_SPACE_SCENARIO])
async def test_existing_scenarios_keep_a_working_withdraw(withdraw_service, monkeypatch, scenario_code):
    """Channel subscription / knowledge-space join: pending is still withdrawable."""
    from bisheng.approval.domain.models.approval_instance import ApprovalInstanceStatus
    from bisheng.approval.domain.repositories.approval_instance_repository import ApprovalInstanceRepository

    instance = await _make_instance(status=ApprovalInstanceStatus.PENDING, scenario_code=scenario_code)
    await _make_pending_task(instance)

    async with _hook_spy(monkeypatch) as hook_calls:
        await withdraw_service.withdraw_instance(
            instance_id=instance.id,
            operator_user_id=OWNER_USER_ID,
            reason="不订阅了",
        )

    refreshed = await ApprovalInstanceRepository.get_instance(instance.id)
    assert refreshed.status == ApprovalInstanceStatus.WITHDRAWN
    assert len(hook_calls) == 1


@pytest.mark.parametrize("scenario_code", [CHANNEL_SCENARIO, KNOWLEDGE_SPACE_SCENARIO])
@pytest.mark.parametrize("status", TERMINAL_STATUSES)
async def test_existing_scenarios_also_refuse_a_terminal_withdraw(withdraw_service, monkeypatch, scenario_code, status):
    """The tightening is engine-wide by design — these two inherit it.

    Concretely: a subscription that was already approved cannot be "withdrawn"
    into a state where the membership row says joined and the approval row says
    withdrawn.
    """
    from bisheng.approval.domain.repositories.approval_instance_repository import ApprovalInstanceRepository

    instance = await _make_instance(status=status, scenario_code=scenario_code)

    async with _hook_spy(monkeypatch) as hook_calls:
        with pytest.raises(_guard_error()):
            await withdraw_service.withdraw_instance(
                instance_id=instance.id,
                operator_user_id=OWNER_USER_ID,
            )

    refreshed = await ApprovalInstanceRepository.get_instance(instance.id)
    assert refreshed.status == status
    assert hook_calls == []
    assert await ApprovalInstanceRepository.list_action_logs(instance.id) == []

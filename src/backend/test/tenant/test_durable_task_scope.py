"""AC-56: old messages recover only from authoritative resource/job facts."""

from types import SimpleNamespace

import pytest

from bisheng.core.context.tenant import get_current_tenant_id
from bisheng.worker import tenant_context as signals


def workflow(headers):
    return SimpleNamespace(
        name="bisheng.worker.workflow.tasks.execute_workflow",
        request=SimpleNamespace(
            headers=headers, args=("run", "flow", "chat", 191), kwargs={}, id="job", called_directly=True
        ),
    )


@pytest.mark.parametrize("header,allowed", [(None, True), (60, True), (65, False)])
def test_workflow_proof_recovers_legacy_header_and_rejects_conflict(monkeypatch, header, allowed):
    from bisheng.workflow.domain.repositories.creation_repository import CreationRepository

    monkeypatch.setattr(CreationRepository, "tenant_for_message", lambda _: 60)
    sender = workflow({} if header is None else {"tenant_id": header})
    try:
        if allowed:
            signals.restore_tenant_context(sender=sender)
            assert get_current_tenant_id() == 60
        else:
            with pytest.raises(signals.PermissionTaskTenantContextError):
                signals.restore_tenant_context(sender=sender)
            assert get_current_tenant_id() is None
    finally:
        signals.reset_tenant_context(sender=sender)


def test_platform_periodic_tasks_keep_platform_contract():
    sender = SimpleNamespace(name="runtime_audit_reconcile", request=SimpleNamespace(headers={}, id="periodic"))
    try:
        signals.restore_tenant_context(sender=sender)
        assert get_current_tenant_id() == 1
    finally:
        signals.reset_tenant_context(sender=sender)


def test_task_body_checks_proof_even_when_signal_did_not_abort(monkeypatch):
    from bisheng.workflow.domain.repositories.creation_repository import CreationRepository

    monkeypatch.setattr(CreationRepository, "tenant_for_message", lambda _: 60)
    sender = workflow({"tenant_id": 65})
    monkeypatch.setattr(signals, "current_task", SimpleNamespace(_get_current_object=lambda: sender))
    with pytest.raises(signals.PermissionTaskTenantContextError):
        with signals.durable_workload_scope("workflow", "flow"):
            pytest.fail("conflicting task must not execute")


def test_task_round_trip_restores_an_eager_callers_context(monkeypatch):
    from bisheng.core.context.tenant import tenant_execution_scope
    from bisheng.workflow.domain.repositories.creation_repository import CreationRepository

    monkeypatch.setattr(CreationRepository, "tenant_for_message", lambda _: 60)
    sender = workflow({"tenant_id": 60})
    with tenant_execution_scope(91):
        signals.restore_tenant_context(sender=sender)
        assert get_current_tenant_id() == 60
        signals.reset_tenant_context(sender=sender)
        assert get_current_tenant_id() == 91


@pytest.mark.parametrize("value", [1.5, True, 0, "x", "-1"])
def test_malformed_workload_tenants_are_never_coerced_to_a_real_tenant(value):
    with pytest.raises(signals.PermissionTaskTenantContextError):
        signals._parse_tenant_id(value)

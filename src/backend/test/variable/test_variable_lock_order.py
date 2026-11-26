"""Never hold synchronous row locks across asynchronous permission checks."""

from types import SimpleNamespace

import pytest

from bisheng.variable.domain.schemas import VariableInput
from bisheng.variable.domain.services.variable_service import VariableService
from test.variable.test_variable_security import harness as variable_harness
from test.variable.test_variable_security import payload

harness = variable_harness


@pytest.mark.parametrize("operation", ["save", "delete", "replace"])
async def test_authorization_finishes_before_row_lock(harness, monkeypatch, operation):
    from bisheng.variable.domain.repositories.variable_repository import VariableRepository
    from bisheng.variable.domain.services import variable_service

    locked = []
    original_flow = VariableRepository.flow

    def flow(self, flow_id, *, lock=False):
        if lock:
            locked.append(flow_id)
        return original_flow(self, flow_id, lock=lock)

    async def authorize(*args, **kwargs):
        assert not locked, "Synchronous row lock held across permission await"

    monkeypatch.setattr(VariableRepository, "flow", flow)
    monkeypatch.setattr(variable_service, "require_business_action", authorize)
    user = SimpleNamespace(user_id=7, tenant_id=1)
    data = VariableInput(**payload(id=1))
    if operation == "save":
        await VariableService.save(user, data)
    elif operation == "delete":
        await VariableService.delete(user, 1)
    else:
        await VariableService.replace(user, [data])
    assert locked == ["a"]


@pytest.mark.parametrize("operation", ["save", "replace"])
async def test_write_collection_uses_current_read(harness, monkeypatch, operation):
    from bisheng.variable.domain.repositories.variable_repository import VariableRepository

    original = VariableRepository.variables
    locks = []

    def variables(self, *args, **kwargs):
        locks.append(kwargs.get("lock", False))
        return original(self, *args, **kwargs)

    monkeypatch.setattr(VariableRepository, "variables", variables)
    user = SimpleNamespace(user_id=7, tenant_id=1)
    data = VariableInput(**payload(id=1))
    if operation == "save":
        await VariableService.save(user, data)
    else:
        await VariableService.replace(user, [data])
    assert locks == [True], "Write collection reads must not use a stale repeatable-read snapshot"

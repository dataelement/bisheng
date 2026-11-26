"""A fail-closed creation projection must not brick a provider space forever."""

from types import SimpleNamespace

import pytest

from bisheng.common.errcode.permission import (
    PermissionProjectionFailedError,
    PermissionVersionConflictError,
)
from bisheng.knowledge.domain.services.department_knowledge_space_service import (
    DepartmentKnowledgeSpaceService as Dept,
)

SPACE_ID = 42
OPERATION_ID = 179


class _Shell:
    id = SPACE_ID


class _Service:
    """Records projection attempts; the first one fails like a closed scope."""

    def __init__(self, failure):
        self.failure = failure
        self.calls = []

    async def _project_space_created(self, shell):
        self.calls.append(shell)
        if len(self.calls) == 1:
            raise self.failure


def _mode(state):
    return SimpleNamespace(projection_state=state, operation_id=OPERATION_ID)


def _install(monkeypatch, *, mode, recovered):
    async def aget_mode(self, *, resource_type, resource_id):
        assert (resource_type, resource_id) == ("knowledge_space", str(SPACE_ID))
        return mode

    async def recover(operation_id):
        recovered.append(operation_id)

    async def runtime():
        return SimpleNamespace(recover_failed_closed_projection=recover)

    monkeypatch.setattr(
        "bisheng.permission.domain.repositories.grant_repository.ResourcePermissionModeRepository.aget_mode", aget_mode
    )
    monkeypatch.setattr("bisheng.permission.application.access.get_f048_runtime", runtime)


@pytest.mark.parametrize("failure", [PermissionProjectionFailedError(), PermissionVersionConflictError()])
async def test_a_fail_closed_shell_projection_is_forward_completed_then_reprojected(monkeypatch, failure):
    recovered = []
    _install(monkeypatch, mode=_mode("FAILED_CLOSED"), recovered=recovered)
    service, shell = _Service(failure), _Shell()
    await Dept._project_created_shell(service, shell)
    assert recovered == [OPERATION_ID]
    assert service.calls == [shell, shell]


async def test_a_current_scope_is_never_recovered(monkeypatch):
    recovered = []
    _install(monkeypatch, mode=_mode("CURRENT"), recovered=recovered)
    service = _Service(PermissionProjectionFailedError())
    with pytest.raises(PermissionProjectionFailedError):
        await Dept._project_created_shell(service, _Shell())
    assert recovered == []
    assert len(service.calls) == 1


async def test_a_missing_mode_row_is_not_treated_as_recoverable(monkeypatch):
    recovered = []
    _install(monkeypatch, mode=None, recovered=recovered)
    service = _Service(PermissionProjectionFailedError())
    with pytest.raises(PermissionProjectionFailedError):
        await Dept._project_created_shell(service, _Shell())
    assert recovered == []
    assert len(service.calls) == 1

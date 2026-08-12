"""An unresolvable publish must leave a labelled state, not a silent fence.

Publishing fences the CURRENT Catalog and only a resolved commit lifts that
fence, so staying fenced after an unresolvable commit is deliberate. Staying
fenced *unlabelled* is not: a crashed publish left the release fenced with no
FAILED_CLOSED marker and no event, which stayed invisible until the next restart
refused to initialize the permission runtime — reporting a data migration that
was never pending.
"""

from __future__ import annotations

import pytest

from bisheng.common.errcode.permission import (
    PermissionProjectionFailedError,
    PermissionPublishNotReadyError,
)
from bisheng.core.openfga.exceptions import FGAClientError
from bisheng.permission.application.process_runtime import (
    register_f048_permission_runtime_context,
)


class _StubProjector:
    """Fail the active-pointer read the way a rejected Read filter did."""

    def __init__(self, error: Exception) -> None:
        self.error = error
        self.read_calls = 0

    async def read_active_release_keys(self):
        self.read_calls += 1
        raise self.error


class _RecordingState:
    def __init__(self) -> None:
        self.fail_closed_calls: list[str] = []

    async def fail_closed(self, context, *, reason: str) -> None:
        del context
        self.fail_closed_calls.append(reason)


def _service(projector: _StubProjector, state: _RecordingState):
    from bisheng.permission.domain.services.catalog_service import CatalogService

    service = CatalogService.__new__(CatalogService)
    service._projector = projector
    service._state = state

    async def _emit(context, *, status, error=None):
        del context, status, error

    service._emit = _emit
    return service


@pytest.mark.asyncio
async def test_unreadable_active_pointer_still_fails_closed() -> None:
    projector = _StubProjector(
        FGAClientError('OpenFGA 400: {"code":"validation_error","message":"object type is required"}')
    )
    state = _RecordingState()
    service = _service(projector, state)

    with pytest.raises(PermissionProjectionFailedError):
        await service._resolve_unknown_commit(
            object(),
            original_error=RuntimeError("commit blew up"),
            allow_retry=True,
        )

    assert projector.read_calls == 1
    # The release is recorded as FAILED_CLOSED, carrying both errors, instead of
    # the read error escaping and leaving the fence unexplained.
    assert len(state.fail_closed_calls) == 1
    reason = state.fail_closed_calls[0]
    assert "unreadable" in reason
    assert "validation_error" in reason
    assert "commit blew up" in reason


class _StubManager:
    def __init__(self, readiness: dict) -> None:
        self._readiness = readiness
        self.marked: list[str] = []

    def readiness(self) -> dict:
        return self._readiness

    async def mark_migration_required(self, *, reason: str = "permission_data_migration_required") -> None:
        self.marked.append(reason)

    async def async_get_instance(self):
        return object()


def _capture_initializer(monkeypatch, manager: _StubManager):
    """Register the runtime context against a stub manager and return its init."""

    from bisheng.core.context.manager import app_context

    def get_context(name: str):
        if name == "openfga":
            return manager
        raise KeyError(name)

    monkeypatch.setattr(app_context, "get_context", get_context)

    captured: dict = {}

    def register_context(context, **kwargs):
        del kwargs
        captured["init"] = context.init_func

    monkeypatch.setattr(app_context, "register_context", register_context)

    async def initializer(client):
        raise AssertionError("the initializer must not run while the gate is latched")

    register_f048_permission_runtime_context(initializer)
    return captured["init"]


@pytest.mark.asyncio
async def test_latched_gate_reports_the_reason_that_latched_it(monkeypatch) -> None:
    manager = _StubManager(
        {
            "migration_required": True,
            "error": "CURRENT Permission Catalog is write fenced",
        }
    )
    initialize = _capture_initializer(monkeypatch, manager)

    with pytest.raises(PermissionPublishNotReadyError) as excinfo:
        await initialize()

    # Not the generic "migration is required", which sent an operator hunting a
    # migration that was never pending.
    assert "write fenced" in str(excinfo.value)


@pytest.mark.asyncio
async def test_gate_falls_back_when_no_reason_was_recorded(monkeypatch) -> None:
    manager = _StubManager({"migration_required": True, "error": None})
    initialize = _capture_initializer(monkeypatch, manager)

    with pytest.raises(PermissionPublishNotReadyError) as excinfo:
        await initialize()

    assert "migration is required" in str(excinfo.value)

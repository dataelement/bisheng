"""F115 AC-01/04/06/08/09/10/52: never report historical execution facts."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest


@pytest.fixture
def query(monkeypatch):
    from bisheng.app_runtime.domain.services import app_query_service as module

    monkeypatch.setattr(module.AppQueryService, "_load_visible", AsyncMock(return_value=SimpleNamespace(id="app-a")))
    return module


async def test_live_nullable_facts_and_public_whitelist(query, monkeypatch):
    facts = {
        "instance_id": "exec-a",
        "phase": "running",
        "health": None,
        "restart_count": None,
        "started_at": None,
        "observation_state": "current",
        "private_environment": "not-public",
    }
    monkeypatch.setattr(query.orchestrator_client, "status", AsyncMock(return_value=facts))
    result = await query.AppQueryService.get_instance("app-a", actor=object())
    assert result["restart_count"] is None and result["observation_state"] == "current"
    assert "private_environment" not in result


async def test_ambiguous_old_manager_404_does_not_read_historical_instance(query, monkeypatch):
    from bisheng.common.errcode.app_factory import AppNotFoundError, AppOrchestratorUnavailableError

    monkeypatch.setattr(query.orchestrator_client, "status", AsyncMock(side_effect=AppNotFoundError()))

    def no_history():
        pytest.fail("historical instance fallback attempted")

    monkeypatch.setattr(query, "get_async_db_session", no_history)
    with pytest.raises(AppOrchestratorUnavailableError):
        await query.AppQueryService.get_instance("app-a", actor=object())


async def test_observer_failure_is_not_no_execution(query, monkeypatch):
    from bisheng.common.errcode.app_factory import AppOrchestratorUnavailableError

    monkeypatch.setattr(query.orchestrator_client, "status", AsyncMock(side_effect=AppOrchestratorUnavailableError()))
    with pytest.raises(AppOrchestratorUnavailableError):
        await query.AppQueryService.get_instance("app-a", actor=object())

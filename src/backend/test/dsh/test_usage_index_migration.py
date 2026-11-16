"""Operator command verifies both index families and requires explicit stopped-service apply."""

import importlib.util
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest


@pytest.fixture
def command():
    path = Path(__file__).resolve().parents[2] / "scripts/backfill_redis_processing_indexes.py"
    spec = importlib.util.spec_from_file_location("processing_index_command", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    "apply,verify,ready,expected",
    [(False, False, False, 0), (False, True, False, 1), (True, False, True, 0), (True, False, False, 1)],
)
async def test_combined_command_verifies_coverage_and_closes_context(
    command, monkeypatch, apply, verify, ready, expected
):
    from bisheng.common.services import config_service
    from bisheng.core.cache import redis_manager
    from bisheng.core.context import manager
    from bisheng.dsh.infrastructure import usage_index_backfill
    from bisheng.linsight.domain.services import checkpoint_index_backfill

    initialize, close = AsyncMock(), AsyncMock()
    monkeypatch.setattr(manager, "initialize_app_context", initialize)
    monkeypatch.setattr(manager, "close_app_context", close)
    monkeypatch.setattr(
        redis_manager, "get_redis_client", AsyncMock(return_value=SimpleNamespace(async_connection=object()))
    )
    monkeypatch.setattr(config_service, "settings", SimpleNamespace(dsh=SimpleNamespace(enabled=True)))
    checkpoints = AsyncMock(return_value={"ready": True})
    usage = AsyncMock(return_value={"ready": ready})
    monkeypatch.setattr(checkpoint_index_backfill, "backfill_checkpoint_indexes", checkpoints)
    monkeypatch.setattr(usage_index_backfill, "backfill_usage_indexes", usage)
    assert await command.run(apply, verify) == expected
    initialize.assert_awaited_once()
    close.assert_awaited_once()
    assert checkpoints.await_args.kwargs["apply"] is apply
    assert usage.await_args.kwargs["apply"] is apply


def test_apply_requires_all_producers_and_consumers_stopped(command, monkeypatch):
    monkeypatch.setattr("sys.argv", ["backfill_redis_processing_indexes.py", "--apply"])
    with pytest.raises(SystemExit) as result:
        command.main()
    assert result.value.code == 2

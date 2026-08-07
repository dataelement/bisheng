# ruff: noqa: E402
from __future__ import annotations

import importlib.util
import subprocess
import sys
import types
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

_BACKEND = Path(__file__).resolve().parents[2]


def _load_filelib_sync_worker_module():
    """Load worker module without triggering mocked bisheng.worker package imports."""
    asyncio_utils_name = "bisheng.worker._asyncio_utils"
    if asyncio_utils_name not in sys.modules or isinstance(sys.modules[asyncio_utils_name], MagicMock):
        utils_spec = importlib.util.spec_from_file_location(
            asyncio_utils_name,
            _BACKEND / "bisheng/worker/_asyncio_utils.py",
        )
        utils_mod = importlib.util.module_from_spec(utils_spec)
        sys.modules[asyncio_utils_name] = utils_mod
        assert utils_spec.loader is not None
        utils_spec.loader.exec_module(utils_mod)

    worker_main = sys.modules.get("bisheng.worker.main")
    if worker_main is None or isinstance(worker_main, MagicMock):
        main_mod = types.ModuleType("bisheng.worker.main")

        def _task_decorator(*_args, **_kwargs):
            def _wrap(fn):
                return fn

            return _wrap

        main_mod.bisheng_celery = SimpleNamespace(task=_task_decorator)
        sys.modules["bisheng.worker.main"] = main_mod

    module_name = "bisheng.open_endpoints.worker.filelib_sync_worker"
    if module_name in sys.modules and not isinstance(sys.modules[module_name], MagicMock):
        return sys.modules[module_name]

    spec = importlib.util.spec_from_file_location(
        module_name,
        _BACKEND / "bisheng/open_endpoints/worker/filelib_sync_worker.py",
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


filelib_sync_worker = _load_filelib_sync_worker_module()

from bisheng.core.context.tenant import current_tenant_id, set_current_tenant_id
from bisheng.open_endpoints.domain.services.automotive_sheet_intro_sync_service import AutomotiveSheetIntroSyncRunResult


def test_worker_package_imports_module_explicitly():
    source = (_BACKEND / "bisheng/worker/__init__.py").read_text(encoding="utf-8")
    assert "open_endpoints.worker.filelib_sync_worker" in source


def test_tasks_and_beat_registered_by_worker_package():
    """Beat publishes the fanout task and the worker package registers both tasks."""
    script = r"""
import json
from bisheng.common.services.config_service import settings
from bisheng.worker.main import bisheng_celery

required = [
    "bisheng.open_endpoints.worker.filelib_sync_worker.fanout_automotive_sheet_intro_sync",
    "bisheng.open_endpoints.worker.filelib_sync_worker.run_automotive_sheet_intro_sync",
]
missing = [name for name in required if name not in bisheng_celery.tasks]
entry = settings.celery_task.beat_schedule.get("automotive_sheet_intro_sync_daily")
beat_ok = bool(entry) and entry["task"] == required[0]
print("RESULT=" + json.dumps({"missing": missing, "beat_ok": beat_ok}))
raise SystemExit(0 if (not missing and beat_ok) else 1)
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=_BACKEND,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.asyncio
async def test_fanout_dispatches_per_tenant_with_headers():
    dispatched = []

    def _capture(*, kwargs=None, headers=None, queue=None):
        dispatched.append((headers, kwargs, queue))

    original_dao = filelib_sync_worker.TenantDao
    original_run = filelib_sync_worker.run_automotive_sheet_intro_sync
    run_stub = SimpleNamespace(apply_async=_capture)
    filelib_sync_worker.TenantDao = SimpleNamespace(aget_children_ids_active=AsyncMock(return_value=[5, 7]))
    filelib_sync_worker.run_automotive_sheet_intro_sync = run_stub
    try:
        count = await filelib_sync_worker._fanout_async()
    finally:
        filelib_sync_worker.TenantDao = original_dao
        filelib_sync_worker.run_automotive_sheet_intro_sync = original_run

    assert count == 3
    tenant_ids = sorted(item[0]["tenant_id"] for item in dispatched)
    assert tenant_ids == [1, 5, 7]
    assert all(item[1]["trigger_type"] == "scheduled" for item in dispatched)
    assert all(item[2] == "celery" for item in dispatched)


@pytest.mark.asyncio
async def test_run_uses_current_tenant_context(async_db_session):
    captured_tenant_ids: list[int] = []

    class _RecordingService:
        def __init__(self, *, session, config_service=None, pdf_client=None):
            self.session = session

        async def run(self, *, tenant_id: int, trigger_type: str):
            captured_tenant_ids.append(int(tenant_id))
            return AutomotiveSheetIntroSyncRunResult(status="skipped", skip_reason="disabled")

    token = set_current_tenant_id(5)
    try:
        with patch.object(filelib_sync_worker, "AutomotiveSheetIntroSyncService", _RecordingService):
            with patch.object(filelib_sync_worker, "get_async_db_session") as session_ctx:
                session_ctx.return_value.__aenter__ = AsyncMock(return_value=async_db_session)
                session_ctx.return_value.__aexit__ = AsyncMock(return_value=False)
                status = await filelib_sync_worker._run_async("scheduled")
    finally:
        current_tenant_id.reset(token)

    assert status == "skipped"
    assert captured_tenant_ids == [5]


@pytest.mark.asyncio
async def test_run_disabled_writes_skipped_status(async_db_session):
    service = MagicMock()
    service.run = AsyncMock(
        return_value=AutomotiveSheetIntroSyncRunResult(status="skipped", skip_reason="disabled", run_id=1)
    )
    token = set_current_tenant_id(5)
    try:
        with patch.object(filelib_sync_worker, "AutomotiveSheetIntroSyncService", return_value=service):
            with patch.object(filelib_sync_worker, "get_async_db_session") as session_ctx:
                session_ctx.return_value.__aenter__ = AsyncMock(return_value=async_db_session)
                session_ctx.return_value.__aexit__ = AsyncMock(return_value=False)
                status = await filelib_sync_worker._run_async("scheduled")
    finally:
        current_tenant_id.reset(token)

    assert status == "skipped"
    service.run.assert_awaited_once_with(tenant_id=5, trigger_type="scheduled")


@pytest.mark.asyncio
async def test_run_lock_held_writes_skipped_status(async_db_session):
    service = MagicMock()
    service.run = AsyncMock(
        return_value=AutomotiveSheetIntroSyncRunResult(status="skipped", skip_reason="lock_held", run_id=2)
    )
    token = set_current_tenant_id(5)
    try:
        with patch.object(filelib_sync_worker, "AutomotiveSheetIntroSyncService", return_value=service):
            with patch.object(filelib_sync_worker, "get_async_db_session") as session_ctx:
                session_ctx.return_value.__aenter__ = AsyncMock(return_value=async_db_session)
                session_ctx.return_value.__aexit__ = AsyncMock(return_value=False)
                status = await filelib_sync_worker._run_async("scheduled")
    finally:
        current_tenant_id.reset(token)

    assert status == "skipped"
    assert service.run.await_args.kwargs["trigger_type"] == "scheduled"


@pytest.mark.asyncio
async def test_run_disabled_token_returns_failed_status(async_db_session):
    service = MagicMock()
    service.run = AsyncMock(
        return_value=AutomotiveSheetIntroSyncRunResult(
            status="failed",
            run_id=3,
            error_message="Developer Token disabled",
        )
    )
    token = set_current_tenant_id(5)
    try:
        with patch.object(filelib_sync_worker, "AutomotiveSheetIntroSyncService", return_value=service):
            with patch.object(filelib_sync_worker, "get_async_db_session") as session_ctx:
                session_ctx.return_value.__aenter__ = AsyncMock(return_value=async_db_session)
                session_ctx.return_value.__aexit__ = AsyncMock(return_value=False)
                status = await filelib_sync_worker._run_async("manual")
    finally:
        current_tenant_id.reset(token)

    assert status == "failed"
    service.run.assert_awaited_once_with(tenant_id=5, trigger_type="manual")

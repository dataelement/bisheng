from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import types
from unittest.mock import AsyncMock

import pytest

for mod in ('celery', 'celery.signals', 'celery.schedules', 'celery.app', 'celery.app.task'):
    if mod not in sys.modules:
        from unittest.mock import MagicMock

        sys.modules[mod] = MagicMock()
from test.fixtures.mock_services import premock_import_chain

premock_import_chain()

class _FakeCelery:
    def task(self, *args, **kwargs):
        def _decorator(func):
            return func

        return _decorator

fake_worker_pkg = types.ModuleType('bisheng.worker')
fake_worker_pkg.__path__ = []  # type: ignore[attr-defined]
sys.modules['bisheng.worker'] = fake_worker_pkg

fake_worker_main = types.ModuleType('bisheng.worker.main')
fake_worker_main.bisheng_celery = _FakeCelery()
sys.modules['bisheng.worker.main'] = fake_worker_main

fake_asyncio_utils = types.ModuleType('bisheng.worker._asyncio_utils')

def _run_async_task(coro_factory):
    raise RuntimeError('run_async_task should not be called in unit tests')

fake_asyncio_utils.run_async_task = _run_async_task
sys.modules['bisheng.worker._asyncio_utils'] = fake_asyncio_utils

from bisheng.approval.domain.models.approval_instance import (
    ApprovalInstance,
    ApprovalInstanceStatus,
    ApprovalOutbox,
    ApprovalOutboxStatus,
)
from bisheng.approval.domain.services.approval_outbox_service import ApprovalOutboxService
from bisheng.approval.domain.repositories.approval_instance_repository import ApprovalInstanceRepository

_TASKS_PATH = Path(__file__).resolve().parents[2] / 'bisheng' / 'worker' / 'approval' / 'tasks.py'
_TASKS_SPEC = importlib.util.spec_from_file_location('approval_worker_tasks_test_module', _TASKS_PATH)
assert _TASKS_SPEC and _TASKS_SPEC.loader
_TASKS_MODULE = importlib.util.module_from_spec(_TASKS_SPEC)
_TASKS_SPEC.loader.exec_module(_TASKS_MODULE)

_build_outbox_executor = _TASKS_MODULE._build_outbox_executor
_execute_approval_outbox_async = _TASKS_MODULE._execute_approval_outbox_async
_retry_approval_outbox_async = _TASKS_MODULE._retry_approval_outbox_async


def _instance() -> ApprovalInstance:
    return ApprovalInstance(
        id=1,
        tenant_id=1,
        scenario_code='menu_access_request',
        scenario_name='菜单权限申请',
        handler_key='menu_access_request',
        business_key='menu:knowledge:user:7',
        business_resource_type='web_menu',
        business_resource_id='knowledge',
        business_name='知识库',
        applicant_user_id=7,
        applicant_user_name='alice',
        status=ApprovalInstanceStatus.APPROVED,
        payload_snapshot={'menu_key': 'knowledge'},
        detail_snapshot={'menu_name': '知识库'},
    )


def _outbox() -> ApprovalOutbox:
    return ApprovalOutbox(
        id=1,
        tenant_id=1,
        instance_id=1,
        handler_key='menu_access_request',
        status=ApprovalOutboxStatus.PENDING,
        payload_snapshot={'menu_key': 'knowledge'},
    )


@pytest.mark.asyncio
async def test_build_outbox_executor_returns_success_and_failure():
    class _SuccessHandler:
        async def on_approved(self, instance_id: int, payload_snapshot: dict) -> dict:
            assert instance_id == 1
            assert payload_snapshot['menu_key'] == 'knowledge'
            return {'ok': True}

    class _FailHandler:
        async def on_approved(self, instance_id: int, payload_snapshot: dict) -> dict:
            raise RuntimeError('boom')

    executor = _build_outbox_executor(handler=_SuccessHandler(), instance_id=1)
    assert await executor(_outbox()) == (True, None)

    executor = _build_outbox_executor(handler=_FailHandler(), instance_id=1)
    success, error_summary = await executor(_outbox())
    assert success is False
    assert error_summary == 'boom'


@pytest.mark.asyncio
async def test_execute_approval_outbox_async_invokes_outbox_service(monkeypatch: pytest.MonkeyPatch):
    outbox = _outbox()
    instance = _instance()
    handler = type(
        'Handler',
        (),
        {'on_approved': AsyncMock(return_value={'status': 'ok'})},
    )()

    monkeypatch.setattr(ApprovalInstanceRepository, 'get_outbox', AsyncMock(return_value=outbox))
    monkeypatch.setattr(ApprovalInstanceRepository, 'get_instance', AsyncMock(return_value=instance))
    monkeypatch.setattr(_TASKS_MODULE, 'build_runtime_handler', AsyncMock(return_value=handler))

    async def fake_execute_outbox(_self, *, outbox_id: int, executor):
        success, error_summary = await executor(outbox)
        assert outbox_id == 1
        assert success is True
        assert error_summary is None
        return True

    monkeypatch.setattr(ApprovalOutboxService, 'execute_outbox', fake_execute_outbox)

    result = await _execute_approval_outbox_async(1)

    assert result is True
    handler.on_approved.assert_awaited_once_with(1, {'menu_key': 'knowledge'})


@pytest.mark.asyncio
async def test_retry_approval_outbox_async_invokes_retry_service(monkeypatch: pytest.MonkeyPatch):
    outbox = _outbox()
    outbox.status = ApprovalOutboxStatus.FAILED
    instance = _instance()
    handler = type(
        'Handler',
        (),
        {'on_approved': AsyncMock(return_value={'status': 'ok'})},
    )()

    monkeypatch.setattr(ApprovalInstanceRepository, 'get_outbox', AsyncMock(return_value=outbox))
    monkeypatch.setattr(ApprovalInstanceRepository, 'get_instance', AsyncMock(return_value=instance))
    monkeypatch.setattr(_TASKS_MODULE, 'build_runtime_handler', AsyncMock(return_value=handler))

    async def fake_retry_outbox(_self, *, outbox_id: int, executor):
        success, error_summary = await executor(outbox)
        assert outbox_id == 1
        assert success is True
        assert error_summary is None
        return True

    monkeypatch.setattr(ApprovalOutboxService, 'retry_outbox', fake_retry_outbox)

    result = await _retry_approval_outbox_async(1)

    assert result is True
    handler.on_approved.assert_awaited_once_with(1, {'menu_key': 'knowledge'})

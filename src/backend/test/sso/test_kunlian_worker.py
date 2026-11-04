"""T050 覆盖 AC-05, AC-06, AC-19, AC-24, AC-26。"""

import importlib
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from bisheng.common.errcode.sso_sync import KunlianDependencyUnavailableError
from bisheng.core.context.tenant import get_current_tenant_id, tenant_execution_scope
from bisheng.sso_sync.domain.services.kunlian_directory import KunlianDirectoryService
from test.sso import test_kunlian_directory as directory_tests
from test.sso import test_kunlian_session_store as store_tests
from test.sso.test_kunlian_admission import config

directory_store = directory_tests.directory_store
session_store = store_tests.session_store


@pytest.fixture
async def worker(directory_store, monkeypatch):
    from bisheng.common.services import config_service

    module = importlib.import_module("bisheng.worker.sso_sync.tasks")
    repository, _, _, _ = directory_store
    cfg = config()
    cfg.login_enabled = False
    monkeypatch.setattr(config_service, "settings", SimpleNamespace(sso_sync=SimpleNamespace(kunlian=cfg)))
    directory = KunlianDirectoryService(repository, cfg, credential_resolver=lambda _: None)
    projection = SimpleNamespace(
        project_pending=AsyncMock(
            return_value={"succeeded": 1, "failed": 0, "has_more": False, "next_after_key": "a" * 64}
        )
    )
    services = SimpleNamespace(config=cfg, directory=directory, projection=projection)
    runtime = SimpleNamespace(worker_services=AsyncMock(return_value=services), aclose=AsyncMock())
    monkeypatch.setattr(module, "KunlianRuntimeProvider", lambda: runtime)
    sync, recover = Mock(), Mock()
    monkeypatch.setattr(module, "sync_directory", SimpleNamespace(apply_async=sync))
    monkeypatch.setattr(module, "recover_projection", SimpleNamespace(apply_async=recover))
    return module, repository, cfg, services, runtime, sync, recover


async def test_durable_request_survives_publish_loss_and_next_tick_requeues(worker):
    module, repository, _, _, runtime, sync, recover = worker
    sync.side_effect = OSError("fixture-broker-unavailable")
    with tenant_execution_scope(7):
        with pytest.raises(KunlianDependencyUnavailableError):
            await module.run_control_operation("dispatch")
        assert get_current_tenant_id() == 7
    pending = (await repository.get_status("fixture"))["sync_requested_version"]
    assert pending > 0
    sync.side_effect = None
    with tenant_execution_scope(7):
        result = await module.run_control_operation("dispatch")
        assert get_current_tenant_id() == 7
    assert result["status"] == "REQUESTED"
    assert (await repository.get_status("fixture"))["sync_requested_version"] >= pending
    assert sync.call_args.kwargs["headers"] == {"tenant_id": 1}
    assert recover.call_args.kwargs["headers"] == {"tenant_id": 1}
    assert runtime.aclose.await_count == 2


async def test_bounded_projection_continues_by_key_and_disabled_configuration_is_inert(worker):
    module, _, cfg, services, runtime, sync, recover = worker
    services.projection.project_pending.return_value.update(has_more=True)
    await module.run_control_operation("recover", connection_id="fixture")
    services.projection.project_pending.assert_awaited_once_with("fixture", after_key="", limit=25)
    assert recover.call_args.kwargs["args"] == ["fixture", "a" * 64]
    cfg.directory_enabled = False
    sync.reset_mock()
    recover.reset_mock()
    runtime.worker_services.reset_mock()
    result = await module.run_control_operation("dispatch")
    assert result == {"status": "DISABLED"}
    runtime.worker_services.assert_not_awaited()
    sync.assert_not_called()
    recover.assert_not_called()


async def test_sync_reports_directory_and_projection_separately_and_cannot_select_another_connection(worker):
    from bisheng.common.errcode.sso_sync import KunlianTrustRejectedError

    module, _, _, services, runtime, _, recover = worker

    async def run(connection_id, owner):
        assert connection_id == "fixture" and len(owner) == 36 and get_current_tenant_id() == 1
        return SimpleNamespace(directory_status="FETCHING", projection_status="PENDING", batch_id="fixture-batch")

    services.directory.run_sync = AsyncMock(side_effect=run)
    with tenant_execution_scope(7):
        result = await module.run_control_operation("sync", connection_id="fixture")
        assert get_current_tenant_id() == 7
    assert result == {"directory_status": "FETCHING", "projection_status": "PENDING", "batch_id": "fixture-batch"}
    recover.assert_not_called()
    services.directory.run_sync.side_effect = None
    services.directory.run_sync.return_value = SimpleNamespace(
        directory_status="PUBLISHED", projection_status="FAILED", batch_id="fixture-batch"
    )
    assert (await module.run_control_operation("sync", connection_id="fixture"))["projection_status"] == "FAILED"
    recover.assert_called_once()
    with pytest.raises(KunlianTrustRejectedError):
        await module.run_control_operation("sync", connection_id="other-connection")
    assert runtime.aclose.await_count == 2


def test_real_registration_strict_headers_beat_and_import_without_network():
    import subprocess
    import sys
    import textwrap

    script = textwrap.dedent("""
        import asyncio, importlib, importlib.util, socket, sys
        from pathlib import Path
        from types import ModuleType, SimpleNamespace
        from unittest.mock import patch
        from celery import Celery
        for name in ('celery.schedules', 'celery.app', 'celery.app.task', 'celery.signals'):
            importlib.import_module(name)
        app = Celery('f118-worker-fixture', broker='memory://', backend='cache+memory://')
        from test.fixtures.mock_services import premock_import_chain
        premock_import_chain()
        main = ModuleType('bisheng.worker.main'); main.bisheng_celery = app
        sys.modules['bisheng.worker.main'] = main
        for name, directory in (('bisheng.worker', 'bisheng/worker'), ('bisheng.worker.sso_sync', 'bisheng/worker/sso_sync')):
            package = ModuleType(name); package.__path__ = [str(Path(directory).resolve())]; sys.modules[name] = package
        importlib.import_module('bisheng.worker.tenant_context')
        with patch.object(socket.socket, 'connect', side_effect=AssertionError('unexpected network IO')):
            name = 'bisheng.worker.sso_sync.tasks'
            spec = importlib.util.spec_from_file_location(name, 'bisheng/worker/sso_sync/tasks.py')
            module = importlib.util.module_from_spec(spec)
            sys.modules[name] = module
            spec.loader.exec_module(module)
        from bisheng.common.services import config_service
        from bisheng.core.config.sso_sync import KunlianConf
        from bisheng.core.context.tenant import get_current_tenant_id, tenant_execution_scope
        from bisheng.common.errcode.sso_sync import KunlianTrustRejectedError
        cfg = KunlianConf()
        config_service.settings = SimpleNamespace(sso_sync=SimpleNamespace(kunlian=cfg), celery_redis_url='memory://',
            celery_task=SimpleNamespace(task_routers={}, beat_schedule={}), dsh=SimpleNamespace(enabled=False))
        module.run_async_task = lambda fn: asyncio.run(fn())
        name = 'bisheng.worker.sso_sync.tasks.'
        for task_name, args in (('dispatch_sync', []), ('sync_directory', ['fixture']), ('recover_projection', ['fixture']), ('expire_session_material', [])):
            task = app.tasks[name + task_name]
            with tenant_execution_scope(7):
                assert task.apply(args=args, headers={'tenant_id': 1}, throw=True).get() == {'status': 'DISABLED'}
                assert get_current_tenant_id() == 7
            for bad in ({}, {'tenant_id': 'external-uuid'}, {'tenant_id': True}, {'tenant_id': 7}):
                with tenant_execution_scope(7):
                    try:
                        task.apply(args=args, headers=bad, throw=True).get()
                    except KunlianTrustRejectedError:
                        pass
                    else:
                        raise AssertionError('invalid control-plane tenant accepted')
        config = importlib.import_module('bisheng.worker.config')
        assert 'kunlian-directory-recovery' not in config.beat_schedule
        assert 'kunlian-session-material-expiry' not in config.beat_schedule
        cfg.connection_id = 'fixture'
        config = importlib.reload(config)
        expiry = config.beat_schedule['kunlian-session-material-expiry']
        assert expiry['task'] == name + 'expire_session_material' and expiry['options']['headers'] == {'tenant_id': 1}
        assert 'kunlian-directory-recovery' not in config.beat_schedule
        cfg.directory_enabled = True
        config = importlib.reload(config)
        item = config.beat_schedule['kunlian-directory-recovery']
        assert item['task'] == name + 'dispatch_sync' and item['options']['headers'] == {'tenant_id': 1}
        assert config.task_routes[name + '*']['queue'] == 'celery'
        app.close()
        print('PASS registered Kunlian tasks and bounded Beat entry')
    """)
    result = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "PASS registered Kunlian tasks" in result.stdout


async def test_registered_connection_keeps_cleanup_when_both_business_switches_are_disabled(session_store, monkeypatch):
    from bisheng.common.services import config_service
    from bisheng.sso_sync.domain.services.kunlian_logout import KunlianLogoutService

    module = importlib.import_module("bisheng.worker.sso_sync.tasks")
    repository, _, clock, bindings = session_store
    await store_tests.issue(repository, clock, bindings[0])
    cfg = config()
    cfg.login_enabled = cfg.directory_enabled = False
    monkeypatch.setattr(config_service, "settings", SimpleNamespace(sso_sync=SimpleNamespace(kunlian=cfg)))
    monkeypatch.setattr(
        KunlianLogoutService,
        "for_material_cleanup",
        lambda value: KunlianLogoutService(repository, value, sessions=None),
    )
    queued = Mock()
    monkeypatch.setattr(module, "expire_session_material", SimpleNamespace(apply_async=queued))
    clock.advance(61)
    with tenant_execution_scope(7):
        assert await module.run_expiry_operation() == {"expired_sessions": 0, "expired_receipts": 1, "has_more": False}
        assert get_current_tenant_id() == 7
    clock.advance(3600)
    assert (await module.run_expiry_operation())["expired_sessions"] == 1
    queued.assert_not_called()

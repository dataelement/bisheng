"""Operational bounds for DSH scans and the default Compose deployment."""

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[4]


def test_dispatch_task_uses_projection_runtime_without_scanning_or_fanout(monkeypatch):
    import asyncio
    from contextlib import asynccontextmanager
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from bisheng.dsh import operations_runtime
    from bisheng.worker import _asyncio_utils
    from bisheng.worker.dsh import registry
    from test.dsh.test_task_request_context import ThreadLocalTaskApp

    service = SimpleNamespace()
    dispatcher = SimpleNamespace(dispatch=AsyncMock(return_value=7))

    @asynccontextmanager
    async def factory():
        yield service

    monkeypatch.setattr(operations_runtime, "projection_worker_runtime", factory)
    monkeypatch.setattr(_asyncio_utils, "run_async_task", lambda factory: asyncio.run(factory()))
    monkeypatch.setattr(registry, "UsageDispatcher", lambda actual: dispatcher if actual is service else None)
    assert registry.register_dsh_tasks(ThreadLocalTaskApp())["dispatch"].run() == 7
    dispatcher.dispatch.assert_awaited_once()


def test_default_backend_containers_have_hard_stdout_rotation():
    compose = yaml.safe_load((ROOT / "docker/docker-compose.yml").read_text(encoding="utf-8"))
    for service in ("backend", "backend_worker"):
        logging = compose["services"][service]["logging"]
        assert logging == {"driver": "json-file", "options": {"max-size": "100m", "max-file": "5"}}


def test_shipped_container_config_does_not_enable_debug_logging():
    # BaseLoader keeps deployment-only !env values inert; this assertion does
    # not need or resolve any production secret.
    config = yaml.load((ROOT / "docker/bisheng/config/config.yaml").read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
    assert config["logger_conf"]["level"] == "INFO"
    main, statistic = config["logger_conf"]["handlers"]
    assert (main["rotation"], main["retention"]) == ("100 MB", "3 Days")
    assert (statistic["rotation"], statistic["retention"]) == ("100 MB", "3 Days")

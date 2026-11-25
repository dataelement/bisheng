"""Verify worker registration in a process isolated from collection-time stubs."""

import os
import subprocess
import sys
from pathlib import Path


def test_rehome_task_registration_and_delivery_contract():
    # Other worker tests replace sys.modules entries during collection. A fresh
    # process keeps their stubs out of this contract and leaves ours out of theirs.
    code = """
import importlib
import inspect
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

from celery import Celery
import celery.app.task
import celery.signals
import celery.schedules

# Reuse the explicit disposable config/keyring and external-boundary stubs.
import test.conftest
from bisheng.core.config.settings import CeleryConf

package = ModuleType("bisheng.worker")
package.__path__ = [str(Path.cwd() / "bisheng/worker")]
sys.modules["bisheng.worker"] = package
app = Celery("retention-contract", broker="memory://", backend="cache+memory://", set_as_current=False)
sys.modules["bisheng.worker.main"].bisheng_celery = app

# Use the real routing defaults and real worker config, not a mocked registry.
import bisheng.common.services.config_service as config_service
config_service.settings = SimpleNamespace(
    celery_redis_url="redis://localhost:6379/2",
    celery_task=CeleryConf(),
    dsh=SimpleNamespace(enabled=False),
)
config = importlib.import_module("bisheng.worker.config")
sys.modules.pop("bisheng.worker.knowledge.knowledge_chat_history_retention", None)
worker = importlib.import_module("bisheng.worker.knowledge.knowledge_chat_history_retention")
source = inspect.getsource(worker)
assert worker.TASK_NAME in source
assert "name=TASK_NAME, acks_late=True, max_retries=3" in source
assert callable(worker.rehome_knowledge_chat_sessions.run)
assert app.tasks[worker.TASK_NAME] is worker.rehome_knowledge_chat_sessions._get_current_object()
assert worker.rehome_knowledge_chat_sessions.acks_late is True
assert worker.rehome_knowledge_chat_sessions.max_retries == 3
assert config.task_routes["bisheng.worker.knowledge.*"]["queue"] == "knowledge_celery"
"""
    env = {key: value for key, value in os.environ.items() if key in {"HOME", "PATH", "TMPDIR", "LANG", "LC_ALL"}}
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=Path(__file__).resolve().parents[2],
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr

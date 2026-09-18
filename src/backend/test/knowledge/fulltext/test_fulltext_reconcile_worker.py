import importlib.util
import subprocess
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from bisheng.knowledge.domain.contracts.fulltext_reconcile import ReconcileLeaseLost

BACKEND = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location(
    "fulltext_reconcile_worker_under_test", BACKEND / "bisheng/worker/knowledge/fulltext_reconcile.py"
)
subject = importlib.util.module_from_spec(spec)
runtime_name = "bisheng.worker._asyncio_utils"
previous_runtime = sys.modules.get(runtime_name)
sys.modules[runtime_name] = SimpleNamespace(run_async_task=MagicMock())
try:
    spec.loader.exec_module(subject)
finally:
    if previous_runtime is None:
        sys.modules.pop(runtime_name, None)
    else:
        sys.modules[runtime_name] = previous_runtime


def test_real_worker_registers_daily_schedule_and_independent_tasks():
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            """
import bisheng.worker
from bisheng.worker.main import bisheng_celery
from bisheng.worker.config import timezone
from bisheng.worker.knowledge.fulltext_reconcile import START_TASK, RESUME_TASK, PARSE_TASK, PROJECTION_TASK
assert timezone == 'Asia/Shanghai'
entry = bisheng_celery.conf.beat_schedule['daily_knowledge_fulltext_reconcile']
assert entry['task'] == START_TASK
assert entry['schedule'].hour == {1} and entry['schedule'].minute == {0}
assert bisheng_celery.conf.beat_schedule['resume_knowledge_fulltext_reconcile']['schedule'] == 300.0
for task in (START_TASK, RESUME_TASK, PARSE_TASK, PROJECTION_TASK):
    assert task in bisheng_celery.tasks
assert bisheng_celery.amqp.router.route({}, PARSE_TASK)['queue'].name == 'knowledge_celery'
""",
        ],
        cwd=BACKEND,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize("owned", [False, ConnectionError("redis unavailable")])
async def test_unverifiable_lease_stops_mutations(owned):
    lock = SimpleNamespace(owned=AsyncMock())
    if isinstance(owned, Exception):
        lock.owned.side_effect = owned
    else:
        lock.owned.return_value = owned
    lease = subject.Lease(lock)
    with pytest.raises(ReconcileLeaseLost):
        await lease.guard()
    assert lease.lost


async def test_repair_publish_failure_keeps_ticket_and_continues_other_file(monkeypatch):
    tickets = [SimpleNamespace(file_id=i, fingerprint=str(i), task_id=f"task-{i}", reason="parse") for i in (1, 2)]
    state = SimpleNamespace(pending_repairs=AsyncMock(return_value=tickets), repair_published=AsyncMock())

    @asynccontextmanager
    async def factory():
        yield SimpleNamespace(state=state)

    sent = []

    def dispatch(**kwargs):
        sent.append(kwargs)
        if kwargs["kwargs"]["file_id"] == 1:
            raise ConnectionError("broker unavailable")

    monkeypatch.setattr(subject, "repository_factory", factory)
    monkeypatch.setattr(subject, "reparse_fulltext_file", SimpleNamespace(apply_async=dispatch))
    result = await subject.publish_repairs(AsyncMock())
    assert result == {"repair_submitted": 1, "repair_publish_failed": 1}
    assert [call["task_id"] for call in sent] == ["task-1", "task-2"]
    assert all(call["queue"] == "knowledge_celery" for call in sent)
    state.repair_published.assert_awaited_once()
    assert state.repair_published.call_args.args[0].file_id == 2


async def test_overlapping_run_never_starts_work(monkeypatch):
    lock = SimpleNamespace(acquire=AsyncMock(return_value=False), release=AsyncMock())
    monkeypatch.setattr(subject, "settings", SimpleNamespace(multi_tenant=SimpleNamespace(enabled=False)))
    monkeypatch.setattr(
        subject,
        "get_redis_client",
        AsyncMock(return_value=SimpleNamespace(async_connection=SimpleNamespace(lock=MagicMock(return_value=lock)))),
    )
    es = AsyncMock()
    monkeypatch.setattr(subject, "get_es_connection", es)
    assert await subject._run(create=True) == {"status": "already_running"}
    es.assert_not_awaited()
    lock.release.assert_not_awaited()

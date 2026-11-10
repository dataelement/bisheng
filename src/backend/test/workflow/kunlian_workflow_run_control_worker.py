"""本地 Redis 队列使用的独立昆联运行 Worker。"""

import json
import os
import sys
from contextlib import ExitStack
from pathlib import Path
from threading import Event
from types import SimpleNamespace
from unittest.mock import patch

from celery import Celery
from sqlalchemy import create_engine
from sqlmodel import Session

from bisheng.core.context.tenant import get_current_tenant_id, tenant_execution_scope
from bisheng.worker._asyncio_utils import run_async_task
from bisheng.worker.workflow import kunlian_workflow_run as worker
from bisheng.workflow.application.kunlian_workflow_invocation import WorkflowInvocationService
from bisheng.workflow.domain.repositories.kunlian_registration import RegistrationRepository
from bisheng.workflow.domain.repositories.kunlian_workflow_run import RunRepository
from bisheng.workflow.domain.schemas.kunlian_registration import RegistrationScope
from bisheng.workflow.nodes.start.start import StartNode
from test.workflow.kunlian_interaction_worker import fake_node_services

QUEUE = "f127_mock_workflow"
RUN_TASK = "kunlian.workflow_run"
RECONCILE_TASK = "f127.mock.reconcile"


def main(database, broker, ready_path, clock_path, gate):
    from celery.contrib.testing.worker import start_worker

    engine = create_engine(f"sqlite:///{database}")
    ready = Path(ready_path)
    ledger = ready.with_suffix(".events")
    runs = RunRepository(
        RegistrationRepository(lambda: Session(engine)), clock=lambda: int(Path(clock_path).read_text())
    )
    app = Celery("f127_mock", broker=broker, backend=broker, set_as_current=False)
    app.conf.update(task_default_queue=QUEUE, worker_prefetch_multiplier=1)

    def record(event, **fields):
        with ledger.open("a") as stream:
            stream.write(json.dumps({"event": event, "pid": os.getpid(), **fields}) + "\n")

    async def authorize(row):
        assert get_current_tenant_id() == row.tenant_id == 7
        assert (row.connection_id, row.user_id) == ("mock", 12)
        return SimpleNamespace(tenant_id=row.tenant_id, user_id=row.user_id)

    class Service(WorkflowInvocationService):
        async def authorize_run(self, row):
            return await authorize(row)

    service = Service(runs, None, lambda *args: worker.dispatch_task(run, *args))
    run = worker.register_task(app, service)

    @app.task(bind=True, name=RECONCILE_TASK, shared=False)
    def reconcile(task):
        tenant_id = (task.request.headers or {}).get("tenant_id")
        assert type(tenant_id) is int and tenant_id > 0
        with tenant_execution_scope(tenant_id):
            run_async_task(lambda: service.reconcile(RegistrationScope(get_current_tenant_id(), "mock", 0)))
        return os.getpid()

    original_start = StartNode._run
    original_output = worker.ResultCallback.on_output_msg

    def start(node, unique_id):
        record("start", node=node.id, tenant_id=get_current_tenant_id())
        if gate == "hold" and not Event().wait(40):
            raise TimeoutError("隔离 Worker 未按测试预期退出")
        return original_start(node, unique_id)

    def output(callback, data):
        record("output", node=data.node_id)
        return original_output(callback, data)

    try:
        with ExitStack() as stack:
            fake_node_services(lambda obj, name, value: stack.enter_context(patch.object(obj, name, value)))
            stack.enter_context(patch.object(StartNode, "_run", start))
            stack.enter_context(patch.object(worker.ResultCallback, "on_output_msg", output))
            with start_worker(app, queues=[QUEUE], concurrency=1, pool="solo", perform_ping_check=False):
                ready.write_text(str(os.getpid()))
                sys.stdin.readline()
    finally:
        app.close()
        engine.dispose()


if __name__ == "__main__":
    main(*sys.argv[1:])

"""在单进程单执行槽的隔离 Celery Worker 中执行真实 Workflow 任务体。"""

import json
import os
import sys
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from sqlalchemy import create_engine
from sqlmodel import Session

from bisheng.core.config.settings import PlatformAgentConf
from bisheng.core.context.tenant import get_current_tenant_id
from bisheng.database.models.session import MessageSessionDao
from bisheng.worker.workflow import platform_agent_long_task_resume as resume_worker
from bisheng.worker.workflow import tasks
from bisheng.worker.workflow.platform_agent_long_task import register_long_task_reconcile
from bisheng.workflow.application import platform_agent
from bisheng.workflow.callback.base_callback import BaseCallback
from bisheng.workflow.domain.clients.platform_agent_mock import MockPlatformAgentProvider
from bisheng.workflow.domain.repositories.platform_agent import PlatformAgentRepository
from bisheng.workflow.domain.services import platform_agent_service as domain
from test.workflow.kunlian_interaction_worker import fake_node_services
from test.workflow.platform_agent_interaction_worker import FileLedger

TASK_NAME = "f126.mock.execute_workflow"
QUEUE = "f126_mock_workflow"
RESUME_TASK = "kunlian.platform_agent_long_task_resume"
RECONCILE_TASK = "kunlian.platform_agent_long_task_reconcile"


def main(database, ledger_path, broker, ready_path, clock="1000", notification="normal"):
    from celery import Celery
    from celery.contrib.testing.worker import start_worker

    engine = create_engine(f"sqlite:///{database}")
    repo = PlatformAgentRepository(lambda: Session(engine), clock=lambda: float(clock))
    config = PlatformAgentConf()
    provider = MockPlatformAgentProvider(config, ledger=FileLedger(ledger_path), clock=repo.clock)

    async def authorize(user, **kwargs):
        assert get_current_tenant_id() == user.tenant_id == 7
        assert user.user_id == 12 and kwargs["action"] == "use"

    async def identity_reader(ids):
        return {ident: {"tenant_id": 7, "state": "active", "token_version": 0} for ident in ids}

    service = domain.PlatformAgentService(
        config=config,
        repository=repo,
        provider=provider,
        identity_reader=identity_reader,
        enable_long_tasks=True,
        enable_long_task_resume=True,
    )
    trace = {}
    events = Path(ready_path).with_suffix(".events")

    def record(event, **fields):
        with events.open("a") as stream:
            stream.write(json.dumps({"event": event, "pid": os.getpid(), **fields}) + "\n")

    original_start = provider.start

    async def record_start(*args):
        observation = await original_start(*args)
        record("start", run_id=observation.run_id)
        return observation

    class Callback(BaseCallback):
        def __init__(self, unique_id, workflow_id, *_args, **_kwargs):
            self.unique_id = unique_id
            self.workflow_id = workflow_id

        def get_workflow_data(self):
            return repo.get_workflow(self.workflow_id)["data"]

        def get_platform_knowledge_reference(self):
            return None

        def bind_platform_agent_execution(self, execution_id):
            trace["execution_id"] = execution_id

        def set_workflow_status(self, status, reason=None):
            trace["statuses"].append(status)

        def on_node_start(self, data):
            assert get_current_tenant_id() == 7
            trace["nodes"].append(data.node_id)

        def on_output_msg(self, data):
            trace["outputs"].append(data.msg)

        def on_agent_long_task(self, summary):
            trace["summaries"].append(summary)

    class ResumeOutput(resume_worker.LongTaskResumeOutput):
        def on_node_start(self, data):
            assert get_current_tenant_id() == 7
            record("node", node=data.node_id)

    class ResumeNotification:
        publish_long_task_resume_output = resume_worker.RedisCallback.publish_long_task_resume_output

        def __init__(self, session_id, workflow_id, chat_id, *_args, **_kwargs):
            self.workflow_id = workflow_id
            self.chat_id = chat_id

        def bind_platform_agent_execution(self, execution_id):
            self.platform_agent_execution_id = execution_id

        def send_chat_response(self, response):
            assert repo.get_execution(self.platform_agent_execution_id)["state"] == "SUCCEEDED"
            assert response.message["agent_long_task_execution_id"] == self.platform_agent_execution_id
            record("notify", message_id=response.message_id)
            if notification == "lost":
                raise ConnectionError()

        def set_workflow_status(self, status):
            record("status", status=status)

    app = Celery("f126_mock", broker=broker, backend=broker, set_as_current=False)
    app.conf.update(task_default_queue=QUEUE, worker_prefetch_multiplier=1)
    resume = tasks.register_long_task_resume(app)
    register_long_task_reconcile(app, lambda: service, long_resume_task=resume)

    @app.task(bind=True, name=TASK_NAME, shared=False)
    def execute(task, *args, **kwargs):
        trace.clear()
        trace.update(
            pid=os.getpid(),
            worker=task.request.hostname,
            slots=worker.pool.num_processes,
            queue=task.request.delivery_info["routing_key"],
            task_id=task.request.id,
            tenant_id=get_current_tenant_id(),
            statuses=[],
            nodes=[],
            outputs=[],
            summaries=[],
        )
        real_task = tasks.execute_workflow
        real_task.push_request(headers=task.request.headers)
        try:
            real_task.run(*args, **kwargs)
        finally:
            real_task.pop_request()
        return trace.copy()

    with ExitStack() as stack:

        def replace(obj, key, value):
            stack.enter_context(patch.object(obj, key, value))

        fake_node_services(replace)
        replace(platform_agent, "get_service", lambda: service)
        replace(provider, "start", record_start)
        replace(domain, "require_business_action", authorize)
        replace(MessageSessionDao, "async_get_one", AsyncMock(return_value=None))
        replace(tasks, "RedisCallback", Callback)
        replace(resume_worker, "RedisCallback", ResumeNotification)
        replace(resume_worker, "LongTaskResumeOutput", ResumeOutput)
        replace(tasks.FlowDao, "get_flow_by_id", lambda workflow_id: SimpleNamespace(**repo.get_workflow(workflow_id)))
        config_fixture = SimpleNamespace(get_workflow_conf=lambda: SimpleNamespace(max_steps=12, timeout=2))
        replace(tasks, "settings", config_fixture)
        replace(resume_worker, "settings", config_fixture)
        replace(tasks, "_log_workflow_telemetry", lambda *_: None)
        with start_worker(app, pool="solo", concurrency=1, queues=[QUEUE], perform_ping_check=False) as worker:
            Path(ready_path).touch()
            sys.stdin.read()
    app.close()
    engine.dispose()


if __name__ == "__main__":
    main(*sys.argv[1:])

"""执行真实任务体的独立 4C Mock 进程夹具。"""

import json
import os
import sqlite3
import sys
from contextlib import ExitStack, closing
from types import SimpleNamespace
from unittest.mock import patch

from celery import Celery
from sqlalchemy import create_engine
from sqlmodel import Session

from bisheng.common.errcode.flow import PlatformAgentError
from bisheng.common.errcode.http_error import UnAuthorizedError
from bisheng.core.config.settings import PlatformAgentConf
from bisheng.core.context.tenant import get_current_tenant_id, tenant_execution_scope
from bisheng.worker.workflow import tasks
from bisheng.workflow.application import platform_agent
from bisheng.workflow.callback.base_callback import BaseCallback
from bisheng.workflow.domain.clients.platform_agent_mock import MockPlatformAgentProvider
from bisheng.workflow.domain.repositories.platform_agent import PlatformAgentRepository
from bisheng.workflow.domain.services import platform_agent_service as domain
from test.workflow.kunlian_interaction_worker import fake_node_services


class FileLedger:
    def __init__(self, path):
        self.path = path
        with closing(sqlite3.connect(path)) as db:
            db.execute("CREATE TABLE IF NOT EXISTS ledger (key TEXT PRIMARY KEY, value TEXT NOT NULL)")

    async def aget(self, key):
        with closing(sqlite3.connect(self.path)) as db:
            row = db.execute("SELECT value FROM ledger WHERE key = ?", (key,)).fetchone()
        return json.loads(row[0]) if row else None

    async def asetNx(self, key, value, expiration):
        with closing(sqlite3.connect(self.path)) as db, db:
            cursor = db.execute("INSERT OR IGNORE INTO ledger VALUES (?, ?)", (key, json.dumps(value)))
            return cursor.rowcount == 1


def main(database, ledger_path, envelope_text):
    envelope = json.loads(envelope_text)
    execution_id = envelope["execution_id"]
    clock = [float(envelope["clock"])]
    engine = create_engine(f"sqlite:///{database}")
    repo = PlatformAgentRepository(lambda: Session(engine), clock=lambda: clock[0])
    config = PlatformAgentConf()
    ledger = FileLedger(ledger_path)
    provider = MockPlatformAgentProvider(config, ledger=ledger, clock=repo.clock, enable_interactions=True)
    provider_calls = []

    async def advance(delay):
        clock[0] += delay

    async def identity_reader(ids):
        return {ident: {"tenant_id": 7, "state": "active", "token_version": 0} for ident in ids}

    async def authorize(user, **kwargs):
        assert get_current_tenant_id() == user.tenant_id == 7
        assert user.user_id == 12 and kwargs["action"] == "use"
        if envelope.get("revoked"):
            raise UnAuthorizedError()

    original_start, original_submit = provider.start, provider.submit_interaction

    async def start(*args):
        provider_calls.append(["start", args[1].version_id])
        return await original_start(*args)

    async def submit(*args):
        provider_calls.append(["submit", args[1].version_id])
        return await original_submit(*args)

    service = domain.PlatformAgentService(
        config=config,
        repository=repo,
        provider=provider,
        identity_reader=identity_reader,
        long_pause=advance,
        enable_long_tasks=True,
        enable_interactions=True,
    )
    outputs, nodes = [], []

    class Callback(BaseCallback):
        def __init__(self, unique_id, *_args, **_kwargs):
            self.unique_id = unique_id

        def get_platform_knowledge_reference(self):
            return None

        def bind_platform_agent_execution(self, execution_id):
            pass

        def set_workflow_status(self, status, reason=None):
            pass

        def on_node_start(self, data):
            assert get_current_tenant_id() == 7
            nodes.append(data.node_id)

        def on_output_msg(self, data):
            outputs.append(data.msg)

        def on_agent_long_task(self, summary):
            pass

    def flow_info(workflow_id):
        return SimpleNamespace(**repo.get_workflow(workflow_id))

    with ExitStack() as stack:

        def replace(obj, key, value):
            stack.enter_context(patch.object(obj, key, value))

        fake_node_services(replace)
        replace(platform_agent, "get_service", lambda: service)
        replace(domain, "require_business_action", authorize)
        replace(provider, "start", start)
        replace(provider, "submit_interaction", submit)
        replace(tasks, "RedisCallback", Callback)
        replace(tasks.FlowDao, "get_flow_by_id", flow_info)
        replace(tasks, "settings", SimpleNamespace(get_workflow_conf=lambda: SimpleNamespace(max_steps=12, timeout=2)))
        replace(tasks, "_log_workflow_telemetry", lambda *_: None)
        app = Celery("agent_interaction_test", broker="memory://", set_as_current=False)
        try:
            if envelope["phase"] == "START":
                task = tasks.execute_workflow
                with tenant_execution_scope(7):
                    row = repo.get_execution(execution_id)
                args = (row["session_id"], row["workflow_id"], "interaction", row["user_id"])
                kwargs = {
                    "platform_agent_execution": {"execution_id": execution_id, "dispatch_id": envelope["dispatch_id"]}
                }
            else:
                task = tasks.register_interaction_resume(app)
                args = (execution_id, envelope["interaction_id"], envelope["dispatch_id"])
                kwargs = {}
            task.push_request(headers=envelope["headers"])
            try:
                task.run(*args, **kwargs)
                error = None
            except PlatformAgentError as exc:
                error = type(exc).__name__
            finally:
                task.pop_request()
        finally:
            app.close()
        with tenant_execution_scope(7):
            state = repo.get_execution(execution_id)["state"]
    engine.dispose()
    print(
        json.dumps(
            {
                "pid": os.getpid(),
                "state": state,
                "nodes": nodes,
                "outputs": outputs,
                "calls": provider_calls,
                "error": error,
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main(*sys.argv[1:])

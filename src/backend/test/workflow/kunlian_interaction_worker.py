"""独立 Mock Worker 使用的本地夹具。"""

import json
import os
import sys
from contextlib import ExitStack
from types import SimpleNamespace
from unittest.mock import patch

from celery import Celery
from sqlalchemy import create_engine
from sqlmodel import Session

from bisheng.worker.workflow import kunlian_workflow_run as worker
from bisheng.workflow.domain.repositories.kunlian_registration import RegistrationRepository
from bisheng.workflow.domain.repositories.kunlian_workflow_run import RunRepository
from bisheng.workflow.nodes.output import output
from bisheng.workflow.nodes.start import start


def fake_node_services(setattr):
    starts = []

    def get_user(user_id):
        starts.append(user_id)
        return SimpleNamespace(user_name=f"prefix-{os.getpid()}")

    setattr(output, "get_minio_storage_sync", lambda: None)
    setattr(worker, "settings", SimpleNamespace(get_workflow_conf=lambda: SimpleNamespace(max_steps=20, timeout=2)))
    setattr(start.UserDao, "get_user", get_user)
    setattr(start.UserGroupDao, "get_user_group", lambda *_: None)
    setattr(start.UserRoleDao, "get_user_roles", lambda *_: None)
    setattr(start.UserDepartmentDao, "get_user_primary_department", lambda *_: None)
    return starts


def main(path, clock, message):
    envelope = json.loads(message)
    session_id = envelope["args"][0]
    engine = create_engine(f"sqlite:///{path}")
    registration = RegistrationRepository(lambda: Session(engine))
    runs = RunRepository(registration, clock=lambda: int(clock))

    async def authorize(row):
        assert (row.tenant_id, row.connection_id, row.user_id) == (7, "mock", 12)
        return SimpleNamespace(tenant_id=7, user_id=12)

    with ExitStack() as stack:
        starts = fake_node_services(lambda obj, name, value: stack.enter_context(patch.object(obj, name, value)))
        app = Celery("interaction_test", broker="memory://", set_as_current=False)
        task = worker.register_task(app, SimpleNamespace(repository=runs, authorize_run=authorize))
        task.push_request(headers=envelope["headers"])
        try:
            task.run(*envelope["args"], **envelope.get("kwargs", {}))
        finally:
            task.pop_request()
            app.close()
        row = runs.load(7, session_id)
        print(json.dumps({"pid": os.getpid(), "starts": starts, "status": row.status}))
    engine.dispose()


if __name__ == "__main__":
    main(*sys.argv[1:])

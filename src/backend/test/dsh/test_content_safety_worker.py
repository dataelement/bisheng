"""Coverage AC: AC-39, AC-41, AC-47, AC-48, AC-53, AC-55.

Isolated child interpreters use genuine Celery eager dispatch and tenant signals;
task bodies, the async bridge, SQL executor and projection services stay real.
The memory publisher boundary is captured, not a production broker. Restart
coverage uses two clean process exits and SQLite persistence, not kill/crash or
dual-DB locking. No parent pytest Celery/sys.modules mocks are reused.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

SCENARIOS = (
    "registration",
    "scope",
    "headers_missing",
    "headers_mismatch",
    "headers_string",
    "headers_boolean",
    "headers_zero",
    "failure_recovery",
    "idempotent",
    "bounded_projection",
    "disabled",
    "archived",
    "bounded_scan",
    "lease_recovery",
    "late_hit",
)


def run_child(tmp_path, scenario, *, database=None):
    config = tmp_path / "synthetic-config.yaml"
    config.write_text("{}\n")
    environment = {key: value for key, value in os.environ.items() if not key.startswith("BS_")}
    environment.update(config=str(config), PYTHONDONTWRITEBYTECODE="1")
    root = Path(__file__).resolve().parents[2]
    environment["PYTHONPATH"] = str(root)
    result = subprocess.run(
        [sys.executable, str(Path(__file__).resolve()), scenario, str(database or tmp_path / "worker.sqlite")],
        cwd=root,
        env=environment,
        capture_output=True,
        text=True,
        timeout=45,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "F111_WORKER_PASS" in result.stdout


@pytest.mark.parametrize("scenario", SCENARIOS)
def test_real_celery_content_safety_worker(tmp_path, scenario):
    run_child(tmp_path, scenario)


def test_genuine_celery_prerun_and_postrun_control(tmp_path):
    run_child(tmp_path, "signal_control")


def test_new_worker_process_recovers_durable_progress_after_lost_continuation(tmp_path):
    database = tmp_path / "restart.sqlite"
    run_child(tmp_path, "restart_seed", database=database)
    run_child(tmp_path, "restart_resume", database=database)


def bootstrap():
    import importlib
    from types import ModuleType

    from celery import Celery, signals

    # Skip unrelated application-startup imports, retaining the real worker package path.
    package = ModuleType("bisheng.worker")
    package.__path__ = [str(Path(__file__).resolve().parents[2] / "bisheng/worker")]
    sys.modules["bisheng.worker"] = package
    context_signals = importlib.import_module("bisheng.worker.tenant_context")
    assert Path(Celery.__module__.replace(".", "/")).parts[0] == "celery"
    assert signals.task_prerun.__class__.__module__ == "celery.utils.dispatch.signal"
    app = Celery("f111-content-safety", broker="memory://", backend="cache+memory://", set_as_current=False)
    app.conf.update(task_always_eager=True, task_eager_propagates=False, task_default_queue="celery")
    return app, signals, context_signals


def snapshot():
    from bisheng.core.context import tenant as context

    return (
        context.get_current_tenant_id(),
        context.get_admin_scope_tenant_id(),
        context.get_visible_tenant_ids(),
        context.is_tenant_filter_bypassed(),
    )


def signal_control():
    from bisheng.core.context import tenant as context

    app, _signals, _handlers = bootstrap()
    observed = []

    @app.task(bind=True, name="f111.signal_control")
    def control(task):
        observed.append((snapshot(), dict(task.request.headers or {})))
        return context.get_current_tenant_id()

    token = context.set_current_tenant_id(202)
    try:
        result = control.apply_async(headers={"tenant_id": 101})
        assert result.get(propagate=True) == 101
        assert observed[0][0][0] == 101 and observed[0][1] == {"tenant_id": 101}
        assert context.get_current_tenant_id() == 202
    finally:
        token.var.reset(token)
        app.close()


class Runtime:
    def __init__(self, database):
        import importlib
        import threading
        from contextlib import contextmanager

        from sqlalchemy import create_engine
        from sqlmodel import Session

        from bisheng.dsh.domain.models.model_audit_tree import DshAuditTreeState
        from test.dsh.content_safety_fixtures import SafetyClock, safety_database, safety_event_factory

        self.app, self.signals, _handlers = bootstrap()
        worker = importlib.import_module("bisheng.worker.dsh.content_safety")
        self.clock = SafetyClock()
        self.make = safety_event_factory(self.clock)
        self.engine = create_engine("sqlite:///" + str(database), connect_args={"check_same_thread": False})
        self.database = safety_database(engine=self.engine)
        self.database.__enter__()
        self.jobs, self.scopes, self.preruns = [], [], []
        self.required_tenant, self.faults = None, 0
        self.main_thread = threading.get_ident()
        self.State = DshAuditTreeState

        @contextmanager
        def repository_scope(repository_type):
            current = snapshot()
            self.scopes.append((current, threading.current_thread().name, threading.get_ident()))
            if self.required_tenant is not None:
                assert current == (self.required_tenant, None, frozenset({self.required_tenant}), False)
                assert threading.get_ident() != self.main_thread
                assert threading.current_thread().name.startswith("dsh-audit")
            if self.faults:
                self.faults -= 1
                raise RuntimeError("Synthetic isolated worker SQL failure")
            with Session(self.engine, expire_on_commit=False) as session, session.begin():
                yield repository_type(session)

        composition = importlib.import_module("bisheng.dsh.operations_runtime")
        composition.repository_scope = repository_scope
        self.project, self.scan = worker.register_content_safety_tasks(self.app)
        self.direct = {task.name: task.apply_async for task in (self.project, self.scan)}
        for task in (self.project, self.scan):
            task.apply_async = lambda args=(), kwargs=None, _name=task.name, **options: self.jobs.append(
                (_name, list(args), kwargs or {}, options)
            )

        def before_task(sender=None, **_kwargs):
            from bisheng.core.context.tenant import current_tenant_id

            if sender.name in self.direct:
                self.preruns.append(
                    (sender.name, snapshot(), dict(sender.request.headers or {}), current_tenant_id.get())
                )

        self.before_task = before_task
        self.signals.task_prerun.connect(before_task, weak=False)

    def dispatch(self, task, args=(), *, headers=None, kwargs=None):
        return self.direct[task.name](args=list(args), kwargs=kwargs or {}, headers=headers)

    def drain(self, maximum=100):
        for _ in range(maximum):
            if not self.jobs:
                return
            name, args, kwargs, options = self.jobs.pop(0)
            task = self.app.tasks[name]
            if name == self.project.name:
                assert type(args[0]) is int and options.get("headers") == {"tenant_id": args[0]}
                self.required_tenant = args[0]
            else:
                self.required_tenant = None
            self.dispatch(task, args, headers=options.get("headers"), kwargs=kwargs).get(propagate=True)
        raise AssertionError("Finite fixture did not converge within bounded task units")

    def seed(self, *, count=1, tenant=101, status="active"):
        from bisheng.database.models.tenant import Tenant
        from bisheng.dsh.domain.models.model_audit_setting import DshModelAuditSetting
        from bisheng.dsh.domain.repositories import content_safety_projection
        from test.dsh.content_safety_fixtures import SafetyIdentity
        from test.dsh.test_content_safety_merge import committed_merge
        from test.dsh.test_content_safety_repository import tenant_session

        Tenant.__table__.create(self.engine, checkfirst=True)
        with tenant_session(self.engine, tenant) as session, session.begin():
            if session.get(Tenant, tenant) is None:
                session.add(
                    Tenant(id=tenant, tenant_code=f"worker-{tenant}", tenant_name="Synthetic history", status=status)
                )
                session.add(DshModelAuditSetting(tenant_id=tenant, mode="OFF"))
        identity = SafetyIdentity(tenant_id=tenant, user_id=11 if tenant == 101 else 22, model_id=7)
        rows = []
        for _ in range(count):
            _fact, row, _duplicate = committed_merge(
                self.engine, content_safety_projection, self.make(identity=identity), tenant_id=tenant
            )
            rows.append(row)
        return rows

    def ready(self, tenant=101):
        from bisheng.dsh.domain.repositories.model_audit_queries import DshModelAuditQueryRepository
        from bisheng.dsh.domain.services.profile import profile_scope
        from test.dsh.test_content_safety_repository import tenant_session

        before = snapshot()
        with profile_scope(tenant), tenant_session(self.engine, tenant) as session:
            repository = DshModelAuditQueryRepository(session)
            ready = repository.tree_progress()["summary_ready"]
        assert snapshot() == before
        return ready

    def counts(self, tenant=101):
        from sqlmodel import select

        from bisheng.dsh.domain.models.content_safety_event import DshContentSafetyEvent
        from bisheng.dsh.domain.models.model_audit_conversation import DshModelAuditConversation
        from bisheng.dsh.domain.models.model_audit_request import DshModelAuditRequest
        from bisheng.dsh.domain.services.profile import profile_scope
        from test.dsh.test_content_safety_repository import tenant_session

        before = snapshot()
        with profile_scope(tenant), tenant_session(self.engine, tenant) as session:
            requests = session.exec(select(DshModelAuditRequest)).all()
            groups = session.exec(select(DshModelAuditConversation)).all()
            facts = session.exec(select(DshContentSafetyEvent)).all()
            counts = (
                len(requests),
                len(facts),
                sum(group.sensitive_hit_count for group in groups),
                sum(request.group_index_pending for request in requests),
            )
        assert snapshot() == before
        return counts

    def close(self):
        self.signals.task_prerun.disconnect(self.before_task)
        self.app.close()
        self.database.__exit__(None, None, None)
        self.engine.dispose()


def check_registration(runtime):
    from bisheng.worker.dsh.registry import register_dsh_tasks

    register_dsh_tasks(runtime.app)
    for name in ("dsh.project_content_safety", "dsh.scan_content_safety"):
        task = runtime.app.tasks[name]
        assert task.name == name and getattr(task, "queue", None) in (None, "celery")
    assert runtime.app.conf.task_default_queue == "celery"


def check_headers(runtime, scenario):
    from bisheng.core.context import tenant as context

    values = {
        "missing": (101, None),
        "mismatch": (101, {"tenant_id": 202}),
        "string": (101, {"tenant_id": "101"}),
        "boolean": (True, {"tenant_id": True}),
        "zero": (0, {"tenant_id": 0}),
    }
    tenant, headers = values[scenario.removeprefix("headers_")]
    token = context.set_current_tenant_id(None)
    before = snapshot()
    try:
        result = runtime.dispatch(runtime.project, [tenant], headers=headers)
        assert result.failed() and isinstance(result.result, ValueError)
        assert runtime.scopes == [] and runtime.jobs == []
        assert snapshot() == before
    finally:
        token.var.reset(token)


def check_scope(runtime, *, failure=False):
    from bisheng.core.context import tenant as context

    runtime.seed()
    runtime.seed(tenant=202)
    runtime.required_tenant = 101
    tokens = [
        context.set_current_tenant_id(999),
        context.set_admin_scope_tenant_id(202),
        context.set_visible_tenant_ids(frozenset({202, 999})),
        context._bypass_tenant_filter.set(True),
    ]
    before = snapshot()
    if failure:
        runtime.faults = 1
    try:
        result = runtime.dispatch(runtime.project, [101], headers={"tenant_id": 101})
        if not failure:
            result.get(propagate=True)
        assert snapshot() == before
        assert runtime.preruns and runtime.preruns[0][3] == 101
        assert runtime.preruns[0][1] == before
        assert runtime.preruns[0][2] == {"tenant_id": 101}
        assert runtime.scopes
        if failure:
            assert runtime.faults == 0
            if result.successful():
                assert runtime.ready() or runtime.jobs
            runtime.dispatch(runtime.project, [101], headers={"tenant_id": 101}).get(propagate=True)
        runtime.drain()
        assert runtime.ready() and runtime.counts() == (1, 1, 1, 0)
        assert runtime.counts(202) == (1, 1, 0, 1)
        assert snapshot() == before
    finally:
        for token in reversed(tokens):
            token.var.reset(token)


def check_idempotent(runtime):
    runtime.seed()
    runtime.required_tenant = 101
    for _ in range(2):
        runtime.dispatch(runtime.project, [101], headers={"tenant_id": 101}).get(propagate=True)
        runtime.drain()
        assert runtime.ready() and runtime.counts() == (1, 1, 1, 0)


def check_bounded_projection(runtime):
    runtime.seed(count=101)
    runtime.required_tenant = 101
    runtime.dispatch(runtime.project, [101], headers={"tenant_id": 101}).get(propagate=True)
    assert runtime.counts()[3] >= 1 and runtime.jobs
    runtime.drain()
    assert runtime.ready() and runtime.counts() == (101, 101, 101, 0)


def check_disabled(runtime, status):
    runtime.seed(status=status)
    runtime.dispatch(runtime.scan).get(propagate=True)
    assert runtime.jobs and any(
        args[0] == 101 for name, args, _kwargs, _options in runtime.jobs if name == runtime.project.name
    )
    runtime.drain()
    assert runtime.ready() and runtime.counts() == (1, 1, 1, 0)


def check_bounded_scan(runtime):
    from uuid import uuid4

    from bisheng.database.models.tenant import Tenant
    from test.dsh.test_content_safety_repository import tenant_session

    Tenant.__table__.create(runtime.engine, checkfirst=True)
    for tenant in range(101, 202):
        with tenant_session(runtime.engine, tenant) as session, session.begin():
            session.add(
                Tenant(id=tenant, tenant_code=f"scan-{tenant}", tenant_name="Synthetic dirty", status="disabled")
            )
            session.add(
                runtime.State(
                    tenant_id=tenant,
                    active=str(uuid4()),
                    safety_summary_revision=2,
                    published_safety_summary_revision=1,
                )
            )
    runtime.dispatch(runtime.scan).get(propagate=True)
    projects = [job for job in runtime.jobs if job[0] == runtime.project.name]
    scans = [job for job in runtime.jobs if job[0] == runtime.scan.name]
    assert len(projects) == 100 and len(scans) == 1
    assert [job[1][0] for job in projects] == list(range(101, 201))
    assert all(job[3].get("headers") == {"tenant_id": job[1][0]} for job in projects)
    assert scans[0][1] == [200]


def check_lease_recovery(runtime):
    from datetime import UTC, datetime, timedelta

    from bisheng.dsh.domain.repositories.model_audit_queries import DshModelAuditQueryRepository
    from test.dsh.test_content_safety_repository import tenant_session

    row = runtime.seed()[0]
    with tenant_session(runtime.engine) as session, session.begin():
        repository = DshModelAuditQueryRepository(session)
        assert repository.project_request(row.request_id)
        repository.fold_hierarchy_batch()
        first = repository.tree_step(now=datetime.now(UTC))
        old_owner = first["owner"]
        state = repository.tree_state()
        state.lease_until = datetime.now(UTC).replace(tzinfo=None) - timedelta(seconds=1)
        session.add(state)
    runtime.required_tenant = 101
    runtime.dispatch(runtime.project, [101], headers={"tenant_id": 101}).get(propagate=True)
    runtime.drain()
    assert runtime.ready() and runtime.counts() == (1, 1, 1, 0)
    runtime.dispatch(runtime.project, [101], headers={"tenant_id": 101}, kwargs={"owner": old_owner}).get(
        propagate=True
    )
    assert runtime.ready() and runtime.counts() == (1, 1, 1, 0)


def check_late_hit(runtime):
    from bisheng.database.models.tenant import Tenant
    from bisheng.dsh.domain.models.model_audit_request import DshModelAuditRequest
    from bisheng.dsh.domain.models.model_audit_setting import DshModelAuditSetting
    from bisheng.dsh.domain.repositories import content_safety_projection
    from test.dsh.content_safety_fixtures import native_audit_factory
    from test.dsh.test_content_safety_groups import native
    from test.dsh.test_content_safety_merge import committed_merge
    from test.dsh.test_content_safety_repository import tenant_session

    Tenant.__table__.create(runtime.engine, checkfirst=True)
    row = native(native_audit_factory(runtime.clock), session_origin="main")
    with tenant_session(runtime.engine) as session, session.begin():
        session.add(Tenant(id=101, tenant_code="late-hit-101", tenant_name="Synthetic published"))
        session.add(DshModelAuditSetting(tenant_id=101, mode="OFF"))
        session.add(row)
    runtime.required_tenant = 101
    runtime.dispatch(runtime.project, [101], headers={"tenant_id": 101}).get(propagate=True)
    runtime.drain()
    assert runtime.ready() and runtime.counts() == (1, 0, 0, 0)

    def watermarks(state):
        return (
            state.active,
            state.revision,
            state.published_revision,
            state.summary_revision,
            state.published_summary_revision,
            state.safety_summary_revision,
            state.published_safety_summary_revision,
        )

    with tenant_session(runtime.engine) as session:
        published = watermarks(session.get(runtime.State, 101))
    # The native audit can publish before the Gateway's first FINAL report arrives.
    late = runtime.make(
        backend_request_id=row.request_id,
        forwarded=True,
        event_kind="FINAL",
        stage_results={"input": "PASSED", "output": "BLOCKED"},
        stage_versions={"input": 1, "output": 1},
        drain_status="FINISHED",
    )
    committed_merge(runtime.engine, content_safety_projection, late)
    with tenant_session(runtime.engine) as session:
        saved = session.get(DshModelAuditRequest, row.request_id)
        assert saved.hierarchy_indexed and saved.group_index_pending and saved.has_sensitive_hit
        assert watermarks(session.get(runtime.State, 101)) == published
    runtime.required_tenant = None
    runtime.dispatch(runtime.scan).get(propagate=True)
    assert any(name == runtime.project.name and args[0] == 101 for name, args, _kwargs, _options in runtime.jobs)
    runtime.drain()
    assert runtime.ready() and runtime.counts() == (1, 1, 1, 0)
    with tenant_session(runtime.engine) as session:
        state = session.get(runtime.State, 101)
        assert state.safety_summary_revision == state.published_safety_summary_revision > published[-1]


def check_restart_seed(runtime):
    runtime.seed()
    runtime.required_tenant = 101
    runtime.dispatch(runtime.project, [101], headers={"tenant_id": 101}).get(propagate=True)
    assert runtime.jobs and not runtime.ready()
    # Continuations live only in this process and are deliberately not drained.


def check_restart_resume(runtime):
    from datetime import UTC, datetime, timedelta

    from test.dsh.test_content_safety_repository import tenant_session

    assert runtime.counts()[0:2] == (1, 1)
    with tenant_session(runtime.engine) as session, session.begin():
        state = session.get(runtime.State, 101)
        if state is not None:
            state.lease_until = datetime.now(UTC).replace(tzinfo=None) - timedelta(seconds=1)
            session.add(state)
    runtime.dispatch(runtime.scan).get(propagate=True)
    assert runtime.jobs
    runtime.drain()
    assert runtime.ready() and runtime.counts() == (1, 1, 1, 0)


def child_entry():
    scenario, database = sys.argv[1:]
    if scenario == "signal_control":
        signal_control()
    else:
        runtime = Runtime(database)
        try:
            if scenario.startswith("headers_"):
                check_headers(runtime, scenario)
            elif scenario in {"scope", "failure_recovery"}:
                check_scope(runtime, failure=scenario == "failure_recovery")
            elif scenario in {"disabled", "archived"}:
                check_disabled(runtime, scenario)
            else:
                {
                    "registration": check_registration,
                    "idempotent": check_idempotent,
                    "bounded_projection": check_bounded_projection,
                    "bounded_scan": check_bounded_scan,
                    "lease_recovery": check_lease_recovery,
                    "late_hit": check_late_hit,
                    "restart_seed": check_restart_seed,
                    "restart_resume": check_restart_resume,
                }[scenario](runtime)
        finally:
            runtime.close()
    print(json.dumps({"result": "F111_WORKER_PASS", "scenario": scenario}))


if __name__ == "__main__":
    child_entry()

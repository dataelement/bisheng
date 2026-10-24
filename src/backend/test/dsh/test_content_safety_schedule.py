"""Coverage AC: AC-03, AC-39, AC-48, AC-55.

Beat configuration and administration assembly remain real. Child interpreters
exercise genuine Celery dispatch/signals and independent SQLite connections;
this is not a real broker, process-crash or MySQL/DM8 durability acceptance.
Only configuration, isolated SQL and external identity ports are substituted.
"""

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from bisheng.dsh.config import DshSettings

SCAN = "dsh.scan_content_safety"
ROOT = Path(__file__).resolve().parents[2]


def settings(*, enabled=True):
    return DshSettings(enabled=enabled, platform_public_url="https://bisheng.invalid" if enabled else None)


def load_schedule(monkeypatch, *, enabled=True, existing=None):
    from bisheng.common.services import config_service

    configured = {} if existing is None else existing
    synthetic = SimpleNamespace(
        celery_redis_url="redis://127.0.0.1:1/15",
        celery_task=SimpleNamespace(task_routers={}, beat_schedule=configured),
        dsh=settings(enabled=enabled),
    )
    monkeypatch.setattr(config_service, "settings", synthetic)
    spec = importlib.util.spec_from_file_location("f111_actual_beat_config", ROOT / "bisheng/worker/config.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def safety_entries(module):
    return [(name, entry) for name, entry in module.beat_schedule.items() if entry["task"] == SCAN]


def test_enabled_beat_registers_one_bounded_scan_without_mutating_existing_schedule(monkeypatch):
    legacy = {"legacy-maintenance": {"task": "legacy.maintenance", "schedule": 19.0}}
    module = load_schedule(monkeypatch, existing=legacy)
    entries = safety_entries(module)
    assert len(entries) == 1
    _name, entry = entries[0]
    assert entry["schedule"] == settings().audit_state_scan_interval_seconds
    assert entry.get("args", ()) == () and entry.get("kwargs", {}) == {}
    assert entry.get("options", {}).get("queue", "celery") == "celery"
    assert legacy == {"legacy-maintenance": {"task": "legacy.maintenance", "schedule": 19.0}}
    assert module.beat_schedule["legacy-maintenance"] == legacy["legacy-maintenance"]
    assert "dsh.scan_model_audit" in {item["task"] for item in module.beat_schedule.values()}
    assert "dsh.scan_audit_trees" in {item["task"] for item in module.beat_schedule.values()}


def test_beat_reimport_preserves_explicit_schedule_override_without_duplicate_registration(monkeypatch):
    first = load_schedule(monkeypatch)
    entries = safety_entries(first)
    assert len(entries) == 1
    name, _entry = entries[0]
    explicit = {name: {"task": SCAN, "schedule": 137.0}}
    second = load_schedule(monkeypatch, existing=explicit)
    third = load_schedule(monkeypatch, existing=second.beat_schedule)
    assert safety_entries(second) == [(name, explicit[name])]
    assert safety_entries(third) == [(name, explicit[name])]
    assert second.beat_schedule is not third.beat_schedule


def test_disabled_dsh_keeps_legacy_beat_configuration_without_new_dependency(monkeypatch):
    legacy = {"legacy-maintenance": {"task": "legacy.maintenance", "schedule": 19.0}}
    module = load_schedule(monkeypatch, enabled=False, existing=legacy)
    assert module.beat_schedule == legacy and not safety_entries(module)


def run_process(tmp_path, scenario, database):
    config = tmp_path / "synthetic-config.yaml"
    config.write_text("{}\n")
    environment = {key: value for key, value in os.environ.items() if not key.startswith("BS_")}
    environment.update(config=str(config), PYTHONDONTWRITEBYTECODE="1", PYTHONPATH=str(ROOT))
    result = subprocess.run(
        [sys.executable, str(Path(__file__).resolve()), scenario, str(database)],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        timeout=45,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    lines = [line for line in result.stdout.splitlines() if line.startswith("F111_SCHEDULE ")]
    assert len(lines) == 1, result.stdout + result.stderr
    return json.loads(lines[0].removeprefix("F111_SCHEDULE "))


def test_actual_beat_dispatches_dirty_tenants_with_real_headers_signals_and_strict_sql(tmp_path):
    run_process(tmp_path, "beat", tmp_path / "beat.sqlite")


def test_administration_process_reads_worker_watermarks_and_later_dirty_state_from_sql(tmp_path):
    database = tmp_path / "shared.sqlite"
    run_process(tmp_path, "seed", database)
    waiting = run_process(tmp_path, "read", database)
    assert waiting["phase"] == "PREPARING" and not waiting["safety_ready"]
    assert waiting["safety_summary_version"] == 0 and waiting["safety_summary_as_of"] is None
    run_process(tmp_path, "project", database)
    published = run_process(tmp_path, "read", database)
    assert published["phase"] == "READY" and published["safety_ready"]
    assert published["safety_summary_version"] > 0 and published["safety_summary_as_of"] is not None
    run_process(tmp_path, "seed_two", database)
    pending = run_process(tmp_path, "read", database)
    assert not pending["safety_ready"] and pending["phase"] == "UPDATING"
    assert pending["safety_summary_version"] == published["safety_summary_version"]
    assert pending["safety_summary_as_of"] == published["safety_summary_as_of"]
    run_process(tmp_path, "project", database)
    republished = run_process(tmp_path, "read", database)
    assert republished["safety_ready"] and republished["phase"] == "READY"
    assert republished["safety_summary_version"] > published["safety_summary_version"]
    run_process(tmp_path, "project", database)
    assert run_process(tmp_path, "read", database) == republished


@pytest.mark.parametrize("with_empty_key", [False, True])
def test_native_model_and_audit_assembly_need_no_gateway_or_safety_receiver_key(tmp_path, with_empty_key):
    run_process(tmp_path, "runtime_empty" if with_empty_key else "runtime_absent", tmp_path / "unused.sqlite")


def read_administration(database):
    import asyncio
    import threading
    from contextlib import contextmanager
    from unittest.mock import AsyncMock

    from sqlalchemy import create_engine
    from sqlmodel import Session

    from bisheng.core.context import tenant as context
    from bisheng.database.models.tenant import UserTenantDao
    from bisheng.dsh import audit_admin_runtime as composition
    from bisheng.dsh.domain.services.profile import profile_scope
    from bisheng.permission import application as permissions
    from bisheng.user.domain.models.user import UserDao
    from test.dsh.content_safety_fixtures import safety_database

    engine = create_engine("sqlite:///" + database, connect_args={"check_same_thread": False})
    observations = []

    @contextmanager
    def scope(repository_type):
        observations.append((context.get_current_tenant_id(), threading.current_thread().name))
        assert context.get_admin_scope_tenant_id() is None
        assert context.get_visible_tenant_ids() == frozenset({101}) and not context.is_tenant_filter_bypassed()
        with Session(engine, expire_on_commit=False) as session:
            yield repository_type(session)

    async def super_admin(**query):
        return query["subject"].subject_id == "1" and query["relation"] == "super_admin"

    try:
        with safety_database(engine=engine), pytest.MonkeyPatch.context() as patch:
            patch.setattr(composition, "repository_scope", scope)
            patch.setattr(UserDao, "aget_user", AsyncMock(return_value=SimpleNamespace(user_id=1, delete=0)))
            patch.setattr(
                UserTenantDao, "aget_active_user_tenant", AsyncMock(return_value=SimpleNamespace(tenant_id=1))
            )
            patch.setattr(
                permissions,
                "get_permission_relation_api",
                AsyncMock(return_value=SimpleNamespace(check=super_admin)),
            )
            administration = composition.build_audit_administration(settings())
            with profile_scope(1):
                result = asyncio.run(administration.queries.readiness(1, 101))
                assert context.get_current_tenant_id() == 1
            assert context.get_current_tenant_id() is None
            assert observations and all(tenant == 101 and name.startswith("dsh-audit") for tenant, name in observations)
            return result
    finally:
        engine.dispose()


def runtime_without_receiver(*, empty_key):
    import asyncio
    import builtins
    import socket
    from unittest.mock import patch

    from bisheng.common.services import config_service
    from bisheng.dsh.audit_admin_runtime import build_audit_administration
    from bisheng.dsh.runtime import get_model_runtime

    ordinary = SimpleNamespace(redis_url="redis://127.0.0.1:1/15")
    if empty_key:
        ordinary.sso_sync = SimpleNamespace(gateway_hmac_secret="", enabled=False)
    original_import = builtins.__import__

    def import_without_receiver(name, *args, **kwargs):
        assert name not in {"bisheng.dsh.content_safety_runtime", "bisheng.sso_sync.domain.services.hmac_auth"}
        return original_import(name, *args, **kwargs)

    async def construct():
        with (
            patch.object(config_service, "settings", ordinary),
            patch.object(builtins, "__import__", import_without_receiver),
            patch.object(socket.socket, "connect", side_effect=AssertionError("Assembly must not perform network I/O")),
        ):
            holder = SimpleNamespace(settings=settings())
            model = await get_model_runtime(holder)
            assert holder.models is model and await get_model_runtime(holder) is model
            assert model.audit is not None and not model.quota.topology.ready
            administration = build_audit_administration(holder.settings)
            assert administration.queries is not None and administration.bodies is not None
            assert administration.modes is not None and holder.settings.gateway_internal_url is None
            await model.close()

    asyncio.run(construct())
    return {"constructed": True}


def worker_process(scenario, database):
    from test.dsh.test_content_safety_worker import Runtime

    runtime = Runtime(database)
    try:
        if scenario in {"seed", "seed_two"}:
            runtime.seed(count=2 if scenario == "seed_two" else 1)
        elif scenario == "project":
            runtime.dispatch(runtime.scan).get(propagate=True)
            runtime.drain()
            assert runtime.ready()
        elif scenario == "beat":
            from celery.beat import Scheduler

            runtime.seed()
            runtime.seed(tenant=202, status="disabled")
            with pytest.MonkeyPatch.context() as patch:
                configured = load_schedule(patch)
            entries = safety_entries(configured)
            assert len(entries) == 1
            name, _entry = entries[0]
            scheduler = Scheduler(app=runtime.app, schedule={}, lazy=True)
            scheduler.update_from_dict(configured.beat_schedule)
            scheduler.apply_async(scheduler.schedule[name], advance=False)
            assert len(runtime.jobs) == 1 and runtime.jobs[0][0] == SCAN
            runtime.drain()
            assert runtime.ready(101) and runtime.ready(202)
            assert runtime.counts(101) == runtime.counts(202) == (1, 1, 1, 0)
            project_runs = [row for row in runtime.preruns if row[0] == runtime.project.name]
            assert {row[2]["tenant_id"] for row in project_runs} == {101, 202}
            assert all(row[3] == row[2]["tenant_id"] for row in project_runs)
        else:
            raise AssertionError("Unknown isolated worker scenario")
        return {"scenario": scenario}
    finally:
        runtime.close()


if __name__ == "__main__":
    scenario, database = sys.argv[1:]
    if scenario == "read":
        value = read_administration(database)
    elif scenario.startswith("runtime_"):
        value = runtime_without_receiver(empty_key=scenario == "runtime_empty")
    else:
        value = worker_process(scenario, database)
    print("F111_SCHEDULE " + json.dumps(value, default=str))

"""F022 visibility for enterprise market plugins and workbenches.

覆盖 AC: AC-03, AC-07, AC-08, AC-14, AC-17, AC-18.
"""

from contextlib import contextmanager
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from bisheng.common.errcode.permission import PermissionInvalidResourceError
from bisheng.dsh_market.domain import permission as market_permission
from bisheng.dsh_market.domain.models import (
    MarketImport,
    MarketPlugin,
    MarketVersion,
    MarketWorkbench,
    MarketWorkbenchImport,
    MarketWorkbenchVersion,
)
from bisheng.dsh_market.domain.repository import MarketRepository
from bisheng.dsh_market.domain.workbench_repository import WorkbenchRepository
from bisheng.permission.domain.services.permission_action_service import PermissionActor

# Exercise the real decision path; see conftest.market_items_visible.
REAL_MARKET_PERMISSION = True
PLUGIN = market_permission.PLUGIN_RESOURCE_TYPE
WORKBENCH = market_permission.WORKBENCH_RESOURCE_TYPE
EMPLOYEE = SimpleNamespace(tenant_id=2, user_id=30, global_super=False)


def hex_id(number):
    return f"{number:032x}"


@pytest.fixture
def sessions():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(
        engine, tables=[table for name, table in SQLModel.metadata.tables.items() if name.startswith("dsh_market_")]
    )

    @contextmanager
    def factory():
        with Session(engine) as session:
            yield session

    return factory


@pytest.fixture
def plugins(sessions):
    return MarketRepository(sessions)


@pytest.fixture
def workbenches(sessions):
    return WorkbenchRepository(sessions)


def add_plugin(sessions, number, tenant=2, *, deleted=False, disabled=False, published=True, age=0):
    plugin_id, version_id = hex_id(number), hex_id(1000 + number)
    with sessions() as db:
        db.add(
            MarketPlugin(
                id=plugin_id,
                tenant_id=tenant,
                name=f"plugin-{number}",
                display_name=f"Plugin {number}",
                description="",
                current_version_id=version_id if published and not deleted else None,
                deleted=deleted,
                disabled=disabled,
                revision=number,
                updated_at=datetime(2026, 11, 1) - timedelta(minutes=age),
            )
        )
        db.add(
            MarketVersion(
                id=version_id,
                tenant_id=tenant,
                plugin_id=plugin_id,
                version="1.0.0",
                digest="a" * 64,
                size=1,
                manifest={"plugin": {}, "targets": {"darwin-arm64": {}}},
                published_once=True,
            )
        )
        db.commit()
    return plugin_id


def add_workbench(sessions, number, tenant=2, *, deleted=False, age=0):
    workbench_id, version_id = hex_id(2000 + number), hex_id(3000 + number)
    with sessions() as db:
        db.add(
            MarketWorkbench(
                id=workbench_id,
                tenant_id=tenant,
                identity_key=f"legacy:{number}",
                identity_kind="legacy",
                legacy_id=f"wb-{number}",
                package_name=f"workbench-{number}",
                display_name=f"Workbench {number}",
                description="",
                current_version_id=None if deleted else version_id,
                revision=number,
                updated_at=datetime(2026, 11, 1) - timedelta(minutes=age),
            )
        )
        db.add(
            MarketWorkbenchVersion(
                id=version_id,
                tenant_id=tenant,
                workbench_id=workbench_id,
                version="1.0.0",
                digest="b" * 64,
                size=1,
                manifest={"screenshots": [], "package_metadata": {}},
            )
        )
        db.commit()
    return workbench_id


class FakeAuthorization:
    """Registered, visible resources stand in for F048 state."""

    def __init__(self, monkeypatch, *, registered=None, visible=()):
        self.registered = registered
        self.visible = set(visible)
        self.snapshot_requests = []
        self.checked = []
        self.reconciled = []
        runtime = SimpleNamespace(get_permission_snapshots=self.snapshots)
        monkeypatch.setattr(market_permission, "resolve_permission_actor", self.actor)
        monkeypatch.setattr(market_permission, "get_f048_runtime", self.runtime(runtime))
        monkeypatch.setattr(market_permission, "batch_check_verified_business_visible", self.check)
        monkeypatch.setattr(market_permission, "get_f048_process_runtime", self.process_runtime)
        monkeypatch.setattr(market_permission, "reconcile_system_owned_resources", self.reconcile)

    @staticmethod
    async def actor(identity):
        return PermissionActor(user_id=identity.user_id, current_tenant_id=identity.tenant_id)

    @staticmethod
    def runtime(value):
        async def get():
            return value

        return get

    async def snapshots(self, resources):
        self.snapshot_requests.append(resources)
        return {
            key: SimpleNamespace(version=3, context_version="current")
            for key in resources
            if self.registered is None or key[2] in self.registered
        }

    async def check(self, *, actor, targets):
        targets = tuple(targets)
        self.checked.append(targets)
        return {(t.resource_type, t.resource_id): t.resource_id in self.visible for t in targets}

    async def process_runtime(self):
        return SimpleNamespace(components=SimpleNamespace(facade="facade"))

    async def reconcile(self, runtime, resources, *, apply, operator_id):
        self.reconciled.append((runtime, resources, apply, operator_id))
        return SimpleNamespace(missing_count=len(resources))


# --- adapter -----------------------------------------------------------------


class Versions:
    def __init__(self):
        self.calls = []

    async def get_permission_version(self, *, tenant_id, resource_type, resource_id):
        self.calls.append((tenant_id, resource_type, resource_id))
        return 4, "current"


@pytest.mark.parametrize("resource_type", [PLUGIN, WORKBENCH])
async def test_adapter_targets_existing_records_including_deleted_ones(sessions, plugins, workbenches, resource_type):
    if resource_type == PLUGIN:
        resource_id = add_plugin(sessions, 1, deleted=True)
        load = plugins.permission_record
    else:
        resource_id = add_workbench(sessions, 1, deleted=True)
        load = workbenches.permission_record
    versions = Versions()
    adapter = market_permission.MarketPermissionAdapter(versions, resource_type, load)
    target = await adapter.resolve_permission_target(
        resource_id=resource_id, actor=PermissionActor(user_id=30, current_tenant_id=2), action="visible"
    )
    assert (target.tenant_id, target.resource_type, target.resource_id) == (2, resource_type, resource_id)
    assert target.resource_version == 4
    assert versions.calls == [(2, resource_type, resource_id)]


@pytest.mark.parametrize("resource_id", ["missing", hex_id(999), "../" + hex_id(1)])
async def test_adapter_rejects_unknown_or_malformed_ids(sessions, plugins, resource_id):
    add_plugin(sessions, 1)
    versions = Versions()
    adapter = market_permission.MarketPermissionAdapter(versions, PLUGIN, plugins.permission_record)
    with pytest.raises(PermissionInvalidResourceError):
        await adapter.resolve_permission_target(
            resource_id=resource_id, actor=PermissionActor(user_id=30, current_tenant_id=2), action="visible"
        )
    assert versions.calls == []


async def test_adapter_rejects_another_tenants_record(sessions, plugins):
    resource_id = add_plugin(sessions, 1, tenant=3)
    versions = Versions()
    adapter = market_permission.MarketPermissionAdapter(versions, PLUGIN, plugins.permission_record)
    with pytest.raises(PermissionInvalidResourceError):
        await adapter.resolve_permission_target(
            resource_id=resource_id, actor=PermissionActor(user_id=30, current_tenant_id=2), action="visible"
        )
    assert versions.calls == []


# --- employee lists ------------------------------------------------------------


async def test_plugin_catalog_filters_before_paginating(monkeypatch, sessions, plugins):
    ids = [add_plugin(sessions, number, age=number) for number in range(1, 8)]
    add_plugin(sessions, 20, deleted=True)
    add_plugin(sessions, 21, disabled=True)
    add_plugin(sessions, 22, tenant=3)
    visible = [ids[0], ids[3], ids[4], ids[6]]
    auth = FakeAuthorization(monkeypatch, visible=visible)

    first = await market_permission.employee_plugins(EMPLOYEE, plugins, "", page=1, size=3)
    second = await market_permission.employee_plugins(EMPLOYEE, plugins, "", page=2, size=3)

    assert [row["id"] for row in first["data"]] == visible[:3]
    assert [row["id"] for row in second["data"]] == visible[3:]
    assert first["total"] == second["total"] == 4
    # Only employee-listable rows of the caller's tenant are ever authorized.
    checked = {target.resource_id for batch in auth.checked for target in batch}
    assert checked == set(ids)


async def test_plugin_catalog_search_and_unregistered_rows_stay_hidden(monkeypatch, sessions, plugins):
    first, second = add_plugin(sessions, 1), add_plugin(sessions, 2)
    FakeAuthorization(monkeypatch, registered={second}, visible={first, second})
    result = await market_permission.employee_plugins(EMPLOYEE, plugins, "Plugin", page=1, size=20)
    assert [row["id"] for row in result["data"]] == [second]
    assert result["total"] == 1


async def test_workbench_list_filters_before_paginating(monkeypatch, sessions, workbenches):
    ids = [add_workbench(sessions, number, age=number) for number in range(1, 6)]
    add_workbench(sessions, 9, deleted=True)
    FakeAuthorization(monkeypatch, visible=[ids[1], ids[2], ids[4]])
    page = await market_permission.employee_workbenches(EMPLOYEE, workbenches, page=2, size=2)
    assert [row["id"] for row in page["data"]] == [ids[4]]
    assert page["total"] == 3


async def test_global_super_admin_sees_every_listable_item_like_skills(monkeypatch, sessions, plugins):
    ids = [add_plugin(sessions, number, age=number) for number in range(1, 4)]
    auth = FakeAuthorization(monkeypatch, visible=())

    async def super_admin(identity):
        return PermissionActor(user_id=identity.user_id, current_tenant_id=identity.tenant_id, super_admin=True)

    monkeypatch.setattr(market_permission, "resolve_permission_actor", super_admin)
    result = await market_permission.employee_plugins(EMPLOYEE, plugins, "", page=1, size=20)
    assert [row["id"] for row in result["data"]] == ids
    # Same short-cut as batch_check_business_actions: no per-item decision is made.
    assert auth.checked == []


async def test_tenant_admins_follow_grants_on_the_employee_side(monkeypatch, sessions, plugins):
    shown = add_plugin(sessions, 1)
    add_plugin(sessions, 2)  # granted to nobody
    FakeAuthorization(monkeypatch, visible={shown})

    async def tenant_admin(identity):
        return PermissionActor(
            user_id=identity.user_id, current_tenant_id=identity.tenant_id, tenant_admin_tenant_ids=frozenset({2})
        )

    monkeypatch.setattr(market_permission, "resolve_permission_actor", tenant_admin)
    result = await market_permission.employee_plugins(EMPLOYEE, plugins, "", page=1, size=20)
    assert [row["id"] for row in result["data"]] == [shown]


# --- single items -----------------------------------------------------------------


@pytest.mark.parametrize("resource_type", [PLUGIN, WORKBENCH])
async def test_hidden_and_missing_items_raise_the_same_error(
    monkeypatch, sessions, plugins, workbenches, resource_type
):
    if resource_type == PLUGIN:
        repository, hidden = plugins, add_plugin(sessions, 1)
    else:
        repository, hidden = workbenches, add_workbench(sessions, 1)
    FakeAuthorization(monkeypatch, visible=())
    errors = []
    for resource_id in (hidden, hex_id(999), "not-an-id"):
        with pytest.raises(LookupError) as raised:
            await market_permission.require_visible(EMPLOYEE, resource_type, repository, resource_id)
        errors.append((type(raised.value), str(raised.value)))
    assert len(set(errors)) == 1


async def test_visible_item_passes(monkeypatch, sessions, workbenches):
    workbench_id = add_workbench(sessions, 1)
    FakeAuthorization(monkeypatch, visible={workbench_id})
    await market_permission.require_visible(EMPLOYEE, WORKBENCH, workbenches, workbench_id)


# --- synchronization and installed-item access --------------------------------------


async def test_sync_policies_keep_only_visible_plugins_including_deleted_ones(monkeypatch, sessions, plugins):
    shown, deleted, hidden = add_plugin(sessions, 1), add_plugin(sessions, 2, deleted=True), add_plugin(sessions, 3)
    FakeAuthorization(monkeypatch, visible={shown, deleted})
    policies = plugins.policies(2)
    assert {row["plugin_id"] for row in policies} == {shown, deleted, hidden}
    result = await market_permission.visible_policies(EMPLOYEE, policies)
    assert [row["plugin_id"] for row in result] == [row["plugin_id"] for row in policies if row["plugin_id"] != hidden]


async def test_sync_policies_batch_their_permission_reads(monkeypatch, sessions, plugins):
    for number in range(1, 6):
        add_plugin(sessions, number)
    auth = FakeAuthorization(monkeypatch, visible=())
    await market_permission.visible_policies(EMPLOYEE, plugins.policies(2))
    assert len(auth.snapshot_requests) == 1
    assert len(auth.checked) == 1


async def test_workbench_access_answers_only_booleans(monkeypatch, sessions, workbenches):
    shown = add_workbench(sessions, 1)
    deleted = add_workbench(sessions, 2, deleted=True)
    hidden = add_workbench(sessions, 3)
    foreign = add_workbench(sessions, 4, tenant=3)
    # Even a grant on another tenant's id must not leak through this endpoint.
    FakeAuthorization(monkeypatch, visible={shown, deleted, foreign})
    result = await market_permission.workbench_access(
        EMPLOYEE, workbenches, [shown, deleted, hidden, foreign, hex_id(1)]
    )
    assert result == {shown: True, deleted: True, hidden: False, foreign: False, hex_id(1): False}


async def test_workbench_access_while_permission_runtime_is_down_raises(monkeypatch, sessions, workbenches):
    shown = add_workbench(sessions, 1)
    auth = FakeAuthorization(monkeypatch, visible={shown})

    async def unavailable(*, actor, targets):
        raise RuntimeError("permission runtime unavailable")

    monkeypatch.setattr(market_permission, "batch_check_verified_business_visible", unavailable)
    # The client keeps its last confirmed state on any failure (AC-14); the
    # server must never turn an outage into "not visible".
    with pytest.raises(RuntimeError):
        await market_permission.workbench_access(EMPLOYEE, workbenches, [shown])
    assert auth.snapshot_requests


# --- registration ----------------------------------------------------------------------


async def test_ensure_registered_reconciles_a_system_owned_visible_resource(monkeypatch):
    auth = FakeAuthorization(monkeypatch)
    await market_permission.ensure_registered(PLUGIN, tenant_id=2, resource_id=hex_id(1), operator_id=20)
    runtime, resources, apply, operator_id = auth.reconciled[0]
    assert (runtime, apply, operator_id) == ("facade", True, 20)
    assert [(r.tenant_id, r.resource_type, r.resource_id, r.action_codes) for r in resources] == [
        (2, PLUGIN, hex_id(1), ("visible",))
    ]


async def test_completed_imports_register_the_imported_item(monkeypatch, sessions, plugins, workbenches):
    plugin_id = add_plugin(sessions, 1, deleted=True)
    workbench_id = add_workbench(sessions, 1)
    auth = FakeAuthorization(monkeypatch)
    plugin_task = MarketImport(tenant_id=2, actor_id=20, digest="c" * 64, status="completed", version_id=hex_id(1001))
    workbench_task = MarketWorkbenchImport(
        tenant_id=2, actor_id=20, digest="d" * 64, status="completed", version_id=hex_id(3001)
    )
    await market_permission.ensure_import_registered(PLUGIN, plugins, 2, plugin_task.model_dump(), operator_id=20)
    await market_permission.ensure_import_registered(
        WORKBENCH, workbenches, 2, workbench_task.model_dump(), operator_id=20
    )
    assert [resources[0].resource_id for _, resources, _, _ in auth.reconciled] == [plugin_id, workbench_id]


@pytest.mark.parametrize("status", ["failed", "validating"])
async def test_unfinished_imports_register_nothing(monkeypatch, plugins, status):
    auth = FakeAuthorization(monkeypatch)
    task = MarketImport(tenant_id=2, actor_id=20, digest="c" * 64, status=status, version_id=None)
    await market_permission.ensure_import_registered(PLUGIN, plugins, 2, task.model_dump(), operator_id=20)
    assert auth.reconciled == []


async def test_system_owned_inventory_covers_every_tenant_and_deleted_rows(sessions, plugins, workbenches):
    first, deleted, foreign = add_plugin(sessions, 1), add_plugin(sessions, 2, deleted=True), add_plugin(sessions, 3, 3)
    workbench = add_workbench(sessions, 1, deleted=True)
    specs = await market_permission.system_owned_inventory((PLUGIN, WORKBENCH), plugins, workbenches)
    assert {(s.tenant_id, s.resource_type, s.resource_id) for s in specs} == {
        (2, PLUGIN, first),
        (2, PLUGIN, deleted),
        (3, PLUGIN, foreign),
        (2, WORKBENCH, workbench),
    }
    assert all(s.action_codes == ("visible",) for s in specs)
    only_plugins = await market_permission.system_owned_inventory((PLUGIN,), plugins, workbenches)
    assert {s.resource_type for s in only_plugins} == {PLUGIN}

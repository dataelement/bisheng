"""T061 — ``precheck_schema``: structure evolution of the declared tables (AC-09 / AC-24 / AC-61).

What is being protected, and why each part is a separate test:

* **The verdict is a pure diff of two declarations.** ``diff_tables`` takes
  two lists and nothing else, so "what counts as breaking" is asserted with
  no database at all — adding is additive, dropping and modifying are not,
  and a case-only change of the SQL type is *not* a modification.
* **The reference is the online version.** A rejected or withdrawn iteration
  never reached the database; diffing against it would confirm changes that
  were never applied. ``evaluate`` reads ``app.current_version_id`` and
  answers ``None`` for a first publish.
* **The gate answers the upload itself.** 16229 is raised inside
  ``accept()`` — no deployment row, no object, nothing enqueued — because that
  is the only place the CLI can turn it into a question and re-send. A
  confirmed submission passes and records what was confirmed on the audit
  row; an additive change is never asked.
* **The worker never asks twice.** The ``precheck_schema`` stage derives the
  same summary and hands it to the approval port, so the card shows what the
  gate saw without a third implementation of the diff.
* **Both surfaces carry the same shape.** ``payload_snapshot`` /
  ``detail_snapshot`` (the approval card) and ``GET /publish-status`` (the
  publish face) both emit ``{has_breaking, items[{table, column, op}]}`` or
  ``null`` — design §4.2 ② / ④ verbatim.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from .conftest import OWNER_USER_ID, ROOT_TENANT_ID

# No module-level ``pytestmark = asyncio``: half the file is synchronous
# (the pure diff), and ``asyncio_mode=auto`` already picks up the coroutines.

BASE_MANIFEST = "name: minimal-app\nruntime: python3.11\nport: 8080\n"

ONLINE_TABLES = [
    {
        "name": "orders",
        "columns": [
            {"name": "id", "type": "INTEGER", "nullable": False},
            {"name": "amount", "type": "REAL"},
            {"name": "note", "type": "TEXT", "nullable": True},
        ],
    },
    {"name": "audit", "columns": ["id", "who"]},
]


def _svc():
    from bisheng.app_publish.domain.services import schema_evolution_service

    return schema_evolution_service


def _tables(*declarations: dict):
    from bisheng.app_publish.domain.schemas.app_manifest import DatabaseTable

    return [DatabaseTable.model_validate(item) for item in declarations]


def _yaml_with_tables(tables: str) -> str:
    return BASE_MANIFEST + "database:\n  tables:\n" + tables


#: Drops ``note`` and turns ``amount`` into an INTEGER — two breaking items.
BREAKING_YAML = _yaml_with_tables(
    "    - name: orders\n"
    "      columns:\n"
    "        - {name: id, type: INTEGER, nullable: false}\n"
    "        - {name: amount, type: INTEGER}\n"
    "    - name: audit\n"
    "      columns: [id, who]\n"
)

#: Adds a column and a table — additive only.
ADDITIVE_YAML = _yaml_with_tables(
    "    - name: orders\n"
    "      columns:\n"
    "        - {name: id, type: integer, nullable: false}\n"
    "        - {name: amount, type: REAL}\n"
    "        - {name: note, type: TEXT, nullable: true}\n"
    "        - {name: created_at, type: TEXT}\n"
    "    - name: audit\n"
    "      columns: [id, who]\n"
    "    - name: settings\n"
    "      columns: [key, value]\n"
)


async def _set_online_tables(publish_db, app, version, tables=ONLINE_TABLES) -> None:
    """Freeze ``database.tables`` on the version the application is running."""
    from bisheng.database.models.app_version import AppVersionDao

    async with publish_db() as session:
        row = await AppVersionDao.aget(session, app.id, version.id)
        row.manifest = {**(row.manifest or {}), "database": {"tables": tables}}
        session.add(row)
        await session.commit()


# ---------------------------------------------------------------------------
# The pure diff
# ---------------------------------------------------------------------------


def test_diff_classifies_add_drop_and_modify():
    svc = _svc()
    previous = _tables(
        {"name": "orders", "columns": [{"name": "id"}, {"name": "amount", "type": "REAL"}, {"name": "note"}]},
        {"name": "gone"},
    )
    current = _tables(
        {"name": "orders", "columns": [{"name": "id"}, {"name": "amount", "type": "INTEGER"}, {"name": "extra"}]},
        {"name": "fresh"},
    )

    change = svc.diff_tables(previous, current)

    assert change.to_dict() == {
        "has_breaking": True,
        "items": [
            {"table": "orders", "column": "amount", "op": "modify_column"},
            {"table": "orders", "column": "extra", "op": "add_column"},
            {"table": "orders", "column": "note", "op": "drop_column"},
            {"table": "fresh", "column": None, "op": "add_table"},
            {"table": "gone", "column": None, "op": "drop_table"},
        ],
    }
    assert [item.op for item in change.breaking_items()] == ["modify_column", "drop_column", "drop_table"]


def test_additive_changes_are_never_breaking():
    svc = _svc()
    previous = _tables({"name": "orders", "columns": ["id"]})
    current = _tables({"name": "orders", "columns": ["id", "amount"]}, {"name": "settings", "columns": ["key"]})

    change = svc.diff_tables(previous, current)

    assert not change.has_breaking
    assert {item.op for item in change.items} == {"add_column", "add_table"}
    svc.require_confirmation(change, confirmed=False)  # additive: no question asked


def test_type_case_and_whitespace_do_not_count_as_a_modification():
    svc = _svc()
    previous = _tables({"name": "t", "columns": [{"name": "c", "type": "TEXT"}]})
    current = _tables({"name": "t", "columns": [{"name": "c", "type": " text "}]})

    assert svc.diff_tables(previous, current).is_empty


@pytest.mark.parametrize(
    "before, after",
    [
        ({"name": "c", "nullable": True}, {"name": "c", "nullable": False}),
        ({"name": "c", "default": 0}, {"name": "c", "default": 1}),
        ({"name": "c", "type": "TEXT"}, {"name": "c"}),
    ],
)
def test_nullable_default_and_type_changes_are_modifications(before, after):
    svc = _svc()
    change = svc.diff_tables(_tables({"name": "t", "columns": [before]}), _tables({"name": "t", "columns": [after]}))
    assert [item.to_dict() for item in change.items] == [{"table": "t", "column": "c", "op": "modify_column"}]
    assert change.has_breaking


def test_identical_declarations_produce_no_items_and_no_payload():
    svc = _svc()
    tables = _tables(*ONLINE_TABLES)
    change = svc.diff_tables(tables, _tables(*ONLINE_TABLES))
    assert change.is_empty and change.to_payload() is None


def test_tables_of_accepts_stored_dicts_and_legacy_name_only_columns():
    """``app_version.manifest`` is ``model_dump()`` output; older rows may hold bare column names."""
    svc = _svc()
    tables = svc.tables_of({"database": {"tables": [{"name": "audit", "columns": ["id", {"name": "who"}]}]}})
    assert [column.name for column in tables[0].columns] == ["id", "who"]
    assert svc.tables_of(None) == []
    assert svc.tables_of({"database": {"tables": "nonsense"}}) == []
    assert svc.tables_of({}) == []


def test_require_confirmation_raises_16229_with_every_item_and_the_breaking_subset():
    from bisheng.common.errcode.app_publish import AppSchemaChangeUnconfirmedError

    svc = _svc()
    change = svc.diff_tables(_tables(*ONLINE_TABLES), _tables({"name": "orders", "columns": ["id", "amount"]}))

    with pytest.raises(AppSchemaChangeUnconfirmedError) as excinfo:
        svc.require_confirmation(change, confirmed=False)

    assert excinfo.value.code == 16229
    details = excinfo.value.kwargs["details"]
    assert details["reason"] == "schema_change_unconfirmed" and details["has_breaking"] is True
    assert {item["op"] for item in details["items"]} == {"modify_column", "drop_column", "drop_table"}
    assert all(item["op"] in {"modify_column", "drop_column", "drop_table"} for item in details["breaking"])
    assert excinfo.value.kwargs["stage"] == "precheck_schema"
    assert any("--confirm-schema-change" in hint for hint in excinfo.value.kwargs["hints"])

    svc.require_confirmation(change, confirmed=True)  # the answer the CLI re-sends
    svc.require_confirmation(None, confirmed=False)  # a first publish has nothing to confirm


# ---------------------------------------------------------------------------
# The reference: the online version, or nothing
# ---------------------------------------------------------------------------


async def test_evaluate_returns_none_without_an_online_version(publish_db, app_factory):
    from bisheng.app_publish.domain.schemas.app_manifest import AppManifest

    manifest = AppManifest.model_validate({"name": "x", "runtime": "python3.11", "port": 1})
    assert await _svc().evaluate(None, manifest) is None
    draft, _ = await app_factory(with_version=False)
    assert await _svc().evaluate(draft.id, manifest) is None


async def test_evaluate_diffs_against_the_current_version_manifest(publish_db, app_factory):
    app, version = await app_factory(with_version=True, state="online")
    await _set_online_tables(publish_db, app, version)

    change = await _svc().evaluate(app.id, {"database": {"tables": [{"name": "orders", "columns": ["id"]}]}})

    assert change is not None and change.has_breaking
    # ``id`` lost its declared type — a modification, not a no-op.
    assert {(item.table, item.column, item.op) for item in change.items} == {
        ("orders", "id", "modify_column"),
        ("orders", "amount", "drop_column"),
        ("orders", "note", "drop_column"),
        ("audit", None, "drop_table"),
    }


# ---------------------------------------------------------------------------
# The gate on the receive leg (AC-09)
# ---------------------------------------------------------------------------


@pytest.fixture()
def _receive_leg(app_runtime_settings, monkeypatch):
    """Runtime layer on, tenant seeded, Celery hand-off captured — as ``test_pipeline_accept`` does."""
    from bisheng.app_publish.domain.services import publish_pipeline_service
    from bisheng.core.context.tenant import set_current_tenant_id

    set_current_tenant_id(ROOT_TENANT_ID)
    app_runtime_settings(enabled=True)
    enqueued: list[str] = []

    async def _capture(deployment_id: str) -> None:
        enqueued.append(deployment_id)

    monkeypatch.setattr(publish_pipeline_service, "enqueue_pipeline", _capture)
    return enqueued


async def _accept(package, principal, **kwargs):
    from bisheng.app_publish.domain.services.publish_pipeline_service import PublishPipelineService

    return await PublishPipelineService.accept(package_path=package, principal=principal, **kwargs)


async def _online_app(publish_db, app_factory):
    app, version = await app_factory(with_version=True, state="online")
    await _set_online_tables(publish_db, app, version)
    return app


async def test_breaking_change_without_confirmation_is_16229_and_leaves_nothing_behind(
    publish_db,
    tier_seed,
    tarball_factory,
    fake_minio,
    app_factory,
    service_account_principal,
    fake_f054_services,
    fake_publish_approval,
    fake_orchestrator,
    audit_sink,
    _receive_leg,
):
    from bisheng.app_publish.domain.models.app_deployment import AppDeploymentDao
    from bisheng.common.errcode.app_publish import AppSchemaChangeUnconfirmedError

    app = await _online_app(publish_db, app_factory)

    with pytest.raises(AppSchemaChangeUnconfirmedError) as excinfo:
        await _accept(tarball_factory(manifest=BREAKING_YAML), service_account_principal(), app_id=app.id)

    assert excinfo.value.code == 16229
    breaking = {(item["column"], item["op"]) for item in excinfo.value.kwargs["details"]["breaking"]}
    assert breaking == {("amount", "modify_column"), ("note", "drop_column")}
    async with publish_db() as session:
        assert await AppDeploymentDao.alist_by_app(session, app.id) == []
    assert fake_minio.list_object_names("bisheng-apps") == []
    assert _receive_leg == [] and fake_orchestrator.calls == []
    assert "app.release.submit" not in {call["action"] for call in audit_sink}


async def test_confirmed_breaking_change_is_accepted_and_recorded_once(
    publish_db,
    tier_seed,
    tarball_factory,
    fake_minio,
    app_factory,
    service_account_principal,
    fake_f054_services,
    fake_publish_approval,
    audit_sink,
    _receive_leg,
):
    app = await _online_app(publish_db, app_factory)

    result = await _accept(
        tarball_factory(manifest=BREAKING_YAML),
        service_account_principal(),
        app_id=app.id,
        confirm_schema_change=True,
    )

    assert _receive_leg == [result.deployment_id]
    submit = next(call for call in audit_sink if call["action"] == "app.release.submit")
    assert submit["metadata"]["confirm_schema_change"] is True
    assert submit["metadata"]["schema_change"]["has_breaking"] is True
    assert {item["op"] for item in submit["metadata"]["schema_change"]["items"]} == {"modify_column", "drop_column"}


async def test_additive_change_needs_no_confirmation(
    publish_db,
    tier_seed,
    tarball_factory,
    fake_minio,
    app_factory,
    service_account_principal,
    fake_f054_services,
    fake_publish_approval,
    audit_sink,
    _receive_leg,
):
    app = await _online_app(publish_db, app_factory)

    result = await _accept(tarball_factory(manifest=ADDITIVE_YAML), service_account_principal(), app_id=app.id)

    assert _receive_leg == [result.deployment_id]
    submit = next(call for call in audit_sink if call["action"] == "app.release.submit")
    assert submit["metadata"]["schema_change"]["has_breaking"] is False
    assert {item["op"] for item in submit["metadata"]["schema_change"]["items"]} == {"add_column", "add_table"}


async def test_first_publish_is_never_asked(
    publish_db,
    tier_seed,
    tarball_factory,
    fake_minio,
    service_account_principal,
    fake_f054_services,
    fake_publish_approval,
    audit_sink,
    _receive_leg,
):
    """No online version means nothing to evolve from — even a manifest full of tables passes."""
    fake_f054_services.responses["create_draft"] = "app-first"

    result = await _accept(tarball_factory(manifest=BREAKING_YAML), service_account_principal())

    assert result.app_id == "app-first" and _receive_leg == [result.deployment_id]
    submit = next(call for call in audit_sink if call["action"] == "app.release.submit")
    assert submit["metadata"]["schema_change"] is None


# ---------------------------------------------------------------------------
# The worker stage: record, never re-ask
# ---------------------------------------------------------------------------


async def test_pipeline_stage_hands_the_summary_to_the_approval_port(
    publish_db,
    tier_seed,
    tarball_factory,
    fake_minio,
    app_factory,
    service_account_principal,
    fake_f054_services,
    fake_publish_approval,
    fake_orchestrator,
    audit_sink,
    _receive_leg,
):
    from bisheng.app_publish.domain.models.app_deployment import STAGE_APPROVAL_CREATED, AppDeploymentDao
    from bisheng.app_publish.domain.services.publish_pipeline_service import PublishPipelineService

    app = await _online_app(publish_db, app_factory)
    result = await _accept(
        tarball_factory(manifest=BREAKING_YAML),
        service_account_principal(),
        app_id=app.id,
        confirm_schema_change=True,
    )

    await PublishPipelineService.run_pipeline(result.deployment_id)

    async with publish_db() as session:
        row = await AppDeploymentDao.aget(session, result.deployment_id)
    assert row.stage == STAGE_APPROVAL_CREATED and row.failure is None, "confirmed → no second gate on the worker"
    submit = next(call for name, call in fake_publish_approval.calls if name == "submit")
    assert submit["schema_change"]["has_breaking"] is True
    assert {item["op"] for item in submit["schema_change"]["items"]} == {"modify_column", "drop_column"}


# ---------------------------------------------------------------------------
# The two surfaces: approval card and publish face
# ---------------------------------------------------------------------------


async def test_approval_payload_carries_the_change_when_submit_derives_it_itself(
    publish_db, app_factory, deployment_factory, approval_env, audit_sink, approval_notifications, super_admin_user
):
    """A caller that skipped the stage still gets the card filled — one diff, derived on demand."""
    from bisheng.app_publish.domain.models.app_deployment import STAGE_PRECHECK_PROBE, STATUS_RUNNING
    from bisheng.app_publish.domain.services import publish_approval_service
    from bisheng.approval.domain.repositories.approval_instance_repository import ApprovalInstanceRepository

    app = await _online_app(publish_db, app_factory)
    deployment = await deployment_factory(
        app_id=app.id,
        stage=STAGE_PRECHECK_PROBE,
        status=STATUS_RUNNING,
        version_id="ver-2",
        tier_code="light",
        manifest={
            "name": app.name,
            "runtime": "python3.11",
            "port": 8080,
            "database": {"tables": [{"name": "orders", "columns": ["id", "amount", "note"]}]},
        },
    )

    result = await publish_approval_service.submit(deployment)

    instance = await ApprovalInstanceRepository.get_instance(result.instance_id)
    for snapshot in (instance.payload_snapshot, instance.detail_snapshot):
        assert snapshot["schema_change"]["has_breaking"] is True
        assert {(item["table"], item["column"], item["op"]) for item in snapshot["schema_change"]["items"]} == {
            ("orders", "id", "modify_column"),
            ("orders", "amount", "modify_column"),
            ("orders", "note", "modify_column"),
            ("audit", None, "drop_table"),
        }


async def test_detail_snapshot_passes_the_summary_through_verbatim(publish_db):
    from bisheng.app_publish.domain.services.app_publish_scenario_handler import AppPublishScenarioHandler

    summary = {"has_breaking": True, "items": [{"table": "orders", "column": "note", "op": "drop_column"}]}
    req = SimpleNamespace(
        business_name="x",
        business_resource_id="app-1",
        payload_snapshot={"app_name": "x", "release_kind": "iteration", "tier": {}, "schema_change": summary},
    )
    detail = await AppPublishScenarioHandler().build_detail(req)
    assert detail["schema_change"] == summary


async def test_publish_status_shows_the_pending_change_and_hides_it_once_settled(
    publish_db, app_factory, deployment_factory, tier_seed
):
    from bisheng.app_publish.domain.models.app_deployment import (
        STAGE_APPROVAL_CREATED,
        STATUS_FAILED,
        STATUS_WAITING_APPROVAL,
    )
    from bisheng.app_publish.domain.services.publish_status_service import PublishStatusService

    app = await _online_app(publish_db, app_factory)
    actor = SimpleNamespace(user_id=OWNER_USER_ID, tenant_id=ROOT_TENANT_ID, is_global_super=False)
    manifest = {
        "name": app.name,
        "runtime": "python3.11",
        "port": 8080,
        "database": {"tables": [{"name": "orders", "columns": ["id", "amount", "note"]}, {"name": "audit"}]},
    }

    await deployment_factory(
        app_id=app.id,
        stage=STAGE_APPROVAL_CREATED,
        status=STATUS_WAITING_APPROVAL,
        version_id="ver-2",
        tier_code="light",
        manifest=manifest,
    )
    status = await PublishStatusService.get_publish_status(app.id, actor=actor)
    assert status["schema_change"]["has_breaking"] is True
    ops = {(item["table"], item["column"], item["op"]) for item in status["schema_change"]["items"]}
    assert ("audit", "id", "drop_column") in ops and ("orders", "id", "modify_column") in ops

    # A failed attempt changed nothing on the online tables — nothing to
    # announce. A second application rather than a second row on the first:
    # two rows minted within one second have no deterministic "latest".
    other = await _online_app(publish_db, app_factory)
    await deployment_factory(
        app_id=other.id,
        stage=STAGE_APPROVAL_CREATED,
        status=STATUS_FAILED,
        version_id="ver-3",
        tier_code="light",
        manifest={**manifest, "name": other.name},
    )
    status = await PublishStatusService.get_publish_status(other.id, actor=actor)
    assert status["schema_change"] is None

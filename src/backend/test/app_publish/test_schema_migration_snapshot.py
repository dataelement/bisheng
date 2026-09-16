"""T062 — the platform builds the declared tables, and snapshots before it breaks one (AC-42).

T061 decided *whether* a release may proceed; this is what happens when it
does. Two halves, tested at the level each one lives at:

* :func:`migration_plan` is pure — two declarations in, a per-table plan out.
  Every assertion about *what* the platform will do to a database is here,
  where no orchestrator, no database and no release are involved.
* :func:`migrate_for_release` and the go-live call are about *when* and *with
  what*: the reference is the online version, the plan reaches runtime-manager
  through the intent facade, and a refusal stops the release before anything is
  started.

Three things this file is really guarding, all of which are silent failures:

* **The DDL is not here.** The backend must not open the application's SQLite
  file — it is on the manager's host and in the multi-node shape not even on
  the same machine (F054 K1 / D10-C). A test greps for it, because "we moved
  the statement building into the backend for convenience" is a one-line change
  that nothing else would notice.
* **The snapshot flag follows the plan, not the caller.** A destructive plan
  asks for a snapshot every time; the manager also decides this for itself, and
  the two agreeing is what makes AC-42 hold no matter which side is wrong.
* **A refused migration never starts the version.** If the start ran anyway,
  the new code would meet the old schema, which is the one outcome worse than
  not publishing.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

# No module-level ``asyncio`` mark: half the file is the pure planner and runs
# synchronously. ``asyncio_mode=auto`` picks up the async tests on its own.


def _service():
    from bisheng.app_publish.domain.services import schema_evolution_service

    return schema_evolution_service


def _tables(declaration: dict[str, list]) -> list:
    """``{"orders": [{"name": "id", ...}, "note"]}`` → validated ``DatabaseTable``s."""
    from bisheng.app_publish.domain.schemas.app_manifest import DatabaseTable

    return [DatabaseTable.model_validate({"name": name, "columns": columns}) for name, columns in declaration.items()]


def _manifest(declaration: dict[str, list]) -> dict:
    return {
        "name": "Orders",
        "runtime": "python3.11",
        "port": 8080,
        "database": {"tables": [{"name": name, "columns": columns} for name, columns in declaration.items()]},
    }


# ---------------------------------------------------------------------------
# the plan (pure)
# ---------------------------------------------------------------------------


class TestMigrationPlan:
    def test_first_release_creates_every_declared_table(self):
        """DEV-07 ② in one line: with no reference, every table is an addition.

        No branch for "first publish" anywhere — that case is just an empty
        ``previous``, which is what keeps it from drifting away from the
        iteration path.
        """
        plan = _service().migration_plan([], _tables({"orders": [{"name": "id", "type": "INTEGER"}, "buyer"]}))

        assert plan == [
            {
                "op": "create_table",
                "table": "orders",
                "columns": [
                    {"name": "id", "type": "INTEGER", "nullable": None, "default": None, "primary_key": False},
                    {"name": "buyer", "type": None, "nullable": None, "default": None, "primary_key": False},
                ],
            }
        ]

    def test_a_new_column_carries_only_that_column(self):
        """An additive plan names what is new; sending the whole table would make
        the executor's "skip what exists" the only thing keeping data safe."""
        previous = _tables({"orders": ["id"]})
        current = _tables({"orders": ["id", {"name": "channel", "type": "TEXT", "default": "web"}]})

        plan = _service().migration_plan(previous, current)

        assert [item["op"] for item in plan] == ["add_columns"]
        assert [column["name"] for column in plan[0]["columns"]] == ["channel"]
        assert plan[0]["columns"][0]["default"] == "web"

    @pytest.mark.parametrize(
        ("previous", "current"),
        [
            ({"orders": ["id", "note"]}, {"orders": ["id"]}),
            ({"orders": [{"name": "id", "type": "TEXT"}]}, {"orders": [{"name": "id", "type": "INTEGER"}]}),
            ({"orders": [{"name": "id", "nullable": True}]}, {"orders": [{"name": "id", "nullable": False}]}),
        ],
        ids=["dropped column", "changed type", "changed nullability"],
    )
    def test_a_breaking_change_rebuilds_the_table_with_the_target_shape(self, previous, current):
        """SQLite drops and retypes a column by rebuilding, so the executor needs
        the **destination**, not the delta — the plan carries every target column."""
        plan = _service().migration_plan(_tables(previous), _tables(current))

        assert [item["op"] for item in plan] == ["rebuild_table"]
        assert [column["name"] for column in plan[0]["columns"]] == [
            column["name"] if isinstance(column, dict) else column for column in next(iter(current.values()))
        ]

    def test_a_table_that_gains_and_loses_a_column_is_one_rebuild(self):
        """Not a rebuild *and* an add: the plan is keyed by table, and two entries
        for one table would leave the order deciding the outcome."""
        previous = _tables({"orders": ["id", "note"]})
        current = _tables({"orders": ["id", "channel"]})

        plan = _service().migration_plan(previous, current)

        assert [item["op"] for item in plan] == ["rebuild_table"]
        assert [column["name"] for column in plan[0]["columns"]] == ["id", "channel"]

    def test_a_removed_table_becomes_a_drop(self):
        plan = _service().migration_plan(_tables({"orders": ["id"], "audit": ["id"]}), _tables({"orders": ["id"]}))

        assert plan == [{"op": "drop_table", "table": "audit"}]

    def test_an_unchanged_declaration_produces_no_plan(self):
        declaration = {"orders": [{"name": "id", "type": "INTEGER"}]}

        assert _service().migration_plan(_tables(declaration), _tables(declaration)) == []

    def test_primary_key_travels_although_it_is_not_part_of_the_change_signature(self):
        """``primary_key`` is an *extra* manifest key: it has to reach the DDL,
        and it must not be able to fail a publish (T061 judges three attributes,
        and this is not one of them)."""
        current = _tables({"orders": [{"name": "id", "type": "INTEGER", "primary_key": True}]})

        plan = _service().migration_plan([], current)
        assert plan[0]["columns"][0]["primary_key"] is True

        changed = _tables({"orders": [{"name": "id", "type": "INTEGER", "primary_key": False}]})
        assert _service().migration_plan(current, changed) == []


class TestTheBackendWritesNoDdl:
    def test_the_module_contains_no_sql(self):
        """F054 K1 / D10-C — the file is on the manager's host, not ours.

        Grep rather than architecture prose: moving statement building in here
        would work perfectly on a single-host compose and fail on every
        multi-node deployment, which is the failure this repo has already had
        once with log files.
        """
        import re
        from pathlib import Path

        source = Path(_service().__file__).read_text(encoding="utf-8")
        body = "\n".join(line for line in source.splitlines() if not line.lstrip().startswith(("#", "*")))
        banned = re.compile(r"\b(CREATE TABLE|ALTER TABLE|DROP TABLE|INSERT INTO|sqlite3)\b")

        assert not banned.findall(body)


# ---------------------------------------------------------------------------
# the release call
# ---------------------------------------------------------------------------


async def _set_manifest(publish_db, version_id: str, manifest: dict) -> None:
    from sqlmodel import select

    from bisheng.database.models.app_version import AppVersion

    async with publish_db() as session:
        row = (await session.execute(select(AppVersion).where(AppVersion.id == version_id))).scalars().first()
        row.manifest = manifest
        session.add(row)
        await session.commit()


class TestMigrateForRelease:
    async def test_first_release_asks_for_no_snapshot(self, publish_db, app_factory, fake_orchestrator):
        """Nothing is at risk: there is no online version and therefore no data."""
        app, _ = await app_factory(with_version=False)

        await _service().migrate_for_release(app.id, _manifest({"orders": ["id"]}))

        (name, kwargs) = fake_orchestrator.calls[-1]
        assert name == "schema_migrate"
        assert kwargs["snapshot"] is False
        assert [item["op"] for item in kwargs["plan"]] == ["create_table"]

    async def test_the_reference_is_the_online_version(self, publish_db, app_factory, fake_orchestrator):
        """Diffing against the previous *submission* would confirm changes that
        never reached the database — the online version is the only declaration
        the live schema was built from."""
        app, version = await app_factory(with_version=True)
        await _set_manifest(publish_db, version.id, _manifest({"orders": ["id"]}))

        await _service().migrate_for_release(app.id, _manifest({"orders": ["id", "channel"]}))

        (_, kwargs) = fake_orchestrator.calls[-1]
        assert [item["op"] for item in kwargs["plan"]] == ["add_columns"]
        assert [column["name"] for column in kwargs["plan"][0]["columns"]] == ["channel"]

    async def test_a_breaking_plan_asks_for_the_snapshot(self, publish_db, app_factory, fake_orchestrator):
        app, version = await app_factory(with_version=True)
        await _set_manifest(publish_db, version.id, _manifest({"orders": ["id", "note"]}))

        await _service().migrate_for_release(app.id, _manifest({"orders": ["id"]}))

        (_, kwargs) = fake_orchestrator.calls[-1]
        assert kwargs["snapshot"] is True

    async def test_an_unchanged_declaration_costs_no_rpc(self, publish_db, app_factory, fake_orchestrator):
        """The common case by a wide margin: most releases change code, not tables."""
        app, version = await app_factory(with_version=True)
        await _set_manifest(publish_db, version.id, _manifest({"orders": ["id"]}))

        assert await _service().migrate_for_release(app.id, _manifest({"orders": ["id"]})) is None
        assert [name for name, _ in fake_orchestrator.calls] == []

    async def test_a_release_declaring_no_tables_costs_no_rpc(self, publish_db, app_factory, fake_orchestrator):
        app, _ = await app_factory(with_version=True)

        assert (
            await _service().migrate_for_release(app.id, {"name": "x", "runtime": "python3.11", "port": 8080}) is None
        )
        assert fake_orchestrator.calls == []


# ---------------------------------------------------------------------------
# go-live
# ---------------------------------------------------------------------------


def _action_result(*, state: str, ok: bool = True, reason: str = "", detail=None):
    from bisheng.app_runtime.domain.services.app_state_service import ActionResult

    return ActionResult(app_id="app", state=state, ok=ok, reason=reason, version_id=None, detail=detail or {})


@pytest.fixture()
def start_attempt(monkeypatch):
    """Record whether — and when — the version was actually started."""
    from bisheng.app_runtime.domain.services.app_state_service import AppStateService

    calls: list[str] = []

    async def _stage(app_id, version_id):
        calls.append("stage_version")

    async def _publish(app_id, *, actor=None):
        calls.append("publish")
        return _action_result(state="online")

    monkeypatch.setattr(AppStateService, "stage_version", staticmethod(_stage))
    monkeypatch.setattr(AppStateService, "publish", staticmethod(_publish))
    return SimpleNamespace(calls=calls)


async def _release(publish_db, app_factory, deployment_factory, *, state: str, declaration: dict[str, list]):
    """An approved release of ``declaration``, on an app whose online version declares nothing."""
    from datetime import datetime

    from bisheng.app_publish.domain.models.app_deployment import STAGE_APPROVAL_CREATED, STATUS_WAITING_APPROVAL
    from bisheng.database.models.app_version import VERSION_KIND_ITERATION, AppVersion, AppVersionDao

    app, online = await app_factory(state=state, with_version=True)
    async with publish_db() as session:
        pending = AppVersion(
            app_id=app.id,
            version_no=2,
            kind=VERSION_KIND_ITERATION,
            code_object_key=f"apps/{app.id}/versions/v2/code.tar.gz",
            manifest=_manifest(declaration),
            capabilities={},
            injections={},
            tier_id="light",
            runtime="python3.11",
            submitted_at=datetime.now(),
        )
        await AppVersionDao.ainsert(session, pending)
        await session.commit()
    deployment = await deployment_factory(
        app_id=app.id,
        stage=STAGE_APPROVAL_CREATED,
        status=STATUS_WAITING_APPROVAL,
        version_id=pending.id,
        tier_code="light",
        manifest=_manifest(declaration),
    )
    payload = {
        "app_id": app.id,
        "app_name": app.name,
        "version_id": pending.id,
        "version_no": pending.version_no,
        "deployment_id": deployment.id,
        "owner_user_id": app.owner_user_id,
        "tenant_id": app.tenant_id,
    }
    return app, online, pending, deployment, payload


def _online_service():
    from bisheng.app_publish.domain.services.publish_online_service import PublishOnlineService

    return PublishOnlineService


async def _deployment_row(publish_db, deployment_id: str):
    from bisheng.app_publish.domain.models.app_deployment import AppDeploymentDao

    async with publish_db() as session:
        return await AppDeploymentDao.aget(session, deployment_id)


class TestGoLive:
    async def test_the_migration_runs_before_the_version_is_started(
        self, publish_db, app_factory, deployment_factory, fake_orchestrator, start_attempt, audit_sink
    ):
        """Order is the whole safety property (AC-42).

        Migrating after the start would hand the new code an old schema for as
        long as the migration takes; migrating after a *failed* start would
        change the schema under the version that is still serving.
        """
        _, _, pending, _, payload = await _release(
            publish_db, app_factory, deployment_factory, state="online", declaration={"orders": ["id"]}
        )

        result = await _online_service().bring_online(1, payload)

        assert result["status"] == "online"
        assert [name for name, _ in fake_orchestrator.calls] == ["schema_migrate"]
        assert start_attempt.calls == ["stage_version", "publish"]

    async def test_a_refused_migration_never_starts_the_version(
        self, publish_db, app_factory, deployment_factory, fake_orchestrator, start_attempt, audit_sink
    ):
        """And it is recorded as a **failed run**, not as 待上线.

        Parked means "one click or one free gigabyte away"; this one is waiting
        on a different manifest, and parking it would refuse the very
        resubmission that carries the fix (16252).
        """
        from bisheng.common.errcode.app_publish import AppSchemaMigrationFailedError

        _, _, _, deployment, payload = await _release(
            publish_db, app_factory, deployment_factory, state="online", declaration={"orders": ["id"]}
        )
        fake_orchestrator.responses["schema_migrate"] = AppSchemaMigrationFailedError(
            msg="column 'owner' of table 'orders' is declared NOT NULL without a default",
            manager_code="schema_migration_failed",
            reason="notnull_without_default",
            table="orders",
            column="owner",
        )

        result = await _online_service().bring_online(1, payload)

        assert result["status"] == "schema_migration_failed"
        assert "publish" not in start_attempt.calls, "the new version must not meet the old schema"

        row = await _deployment_row(publish_db, deployment.id)
        assert row.status == "failed"
        assert row.failure["code"] == AppSchemaMigrationFailedError.Code
        assert row.failure["details"]["column"] == "owner"
        assert "bisheng deploy" in " ".join(row.failure["hints"])

    async def test_a_refused_migration_is_audited_under_its_own_action(
        self, publish_db, app_factory, deployment_factory, fake_orchestrator, start_attempt, audit_sink
    ):
        """Not ``iteration_failed``: that one says the start failed, and would
        send an operator to runtime logs that have nothing in them."""
        from bisheng.common.errcode.app_publish import AppSchemaMigrationFailedError

        _, _, _, _, payload = await _release(
            publish_db, app_factory, deployment_factory, state="online", declaration={"orders": ["id"]}
        )
        fake_orchestrator.responses["schema_migrate"] = AppSchemaMigrationFailedError(
            msg="rejected by SQLite", reason="sqlite_error"
        )

        await _online_service().bring_online(1, payload)

        actions = [getattr(one, "action", None) or one.get("action") for one in audit_sink]
        assert "app.release.schema_migration_failed" in actions

    async def test_a_manual_publish_retries_the_same_migration(
        self, publish_db, app_factory, deployment_factory, fake_orchestrator, monkeypatch, audit_sink
    ):
        """The plan is idempotent by construction, so the retry path needs no
        special case — but it must still run: a release parked before its
        tables were built would otherwise start against a database without them.
        """
        from bisheng.app_runtime.domain.services.app_state_service import AppStateService

        app, _, pending, _, _ = await _release(
            publish_db, app_factory, deployment_factory, state="pending_online", declaration={"orders": ["id"]}
        )
        async with publish_db() as session:
            from bisheng.database.models.app import AppDao

            row = await AppDao.aget(session, app.id)
            row.pending_version_id = pending.id
            session.add(row)
            await session.commit()

        async def _manual(app_id, *, actor=None):
            return _action_result(state="online")

        monkeypatch.setattr(AppStateService, "manual_publish", staticmethod(_manual))

        await _online_service().manual_publish(app.id, actor=SimpleNamespace(user_id=1, tenant_id=1))

        assert [name for name, _ in fake_orchestrator.calls] == ["schema_migrate"]

    async def test_a_stopped_application_migrates_nothing(
        self, publish_db, app_factory, deployment_factory, fake_orchestrator, start_attempt, audit_sink
    ):
        """AC-36 stages the version and starts nothing, so there is nothing to
        migrate *for* — and changing the schema under the version that will
        resume later is exactly the accident the ordering rule exists to stop."""
        _, _, _, _, payload = await _release(
            publish_db, app_factory, deployment_factory, state="stopped", declaration={"orders": ["id"]}
        )

        result = await _online_service().bring_online(1, payload)

        assert result["status"] == "staged_only"
        assert fake_orchestrator.calls == []

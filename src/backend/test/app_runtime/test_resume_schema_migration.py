"""AC-36 with AC-42 — the staged release's tables are built when it resumes.

The hole this file exists to keep shut: an approval that lands while the
application is **stopped** does not start anything (AC-36). F055's go-live path
returns ``staged_only`` and the declared-table migration it owns never runs —
correctly, because changing the schema under a version that is not going to run
is exactly the accident the ordering rule forbids. What makes that safe is that
the *next* start pays the bill, and the next start is ``resume``, which lives
here rather than in the publish pipeline.

Without this, an application could go from a manifest declaring ``orders`` to a
running instance whose database has never heard of it, with every test in
``test_schema_migration_snapshot.py`` still green: that file only ever watches
the publish path.
"""

from __future__ import annotations

import pytest

from bisheng.app_runtime.domain.constants import AppState


async def _staged_second_version(app_db, app_factory, *, tables: list[dict] | None):
    """A stopped application whose approved-but-unstarted version declares ``tables``."""
    from bisheng.app_runtime.domain.services.app_state_service import AppStateService
    from bisheng.database.models.app_version import VERSION_KIND_ITERATION, AppVersion, AppVersionDao

    app, _first = await app_factory(state=AppState.STOPPED.value)
    manifest: dict = {"name": "Orders", "runtime": "python3.11", "port": 8080}
    if tables is not None:
        manifest["database"] = {"tables": tables}
    async with app_db() as session:
        second = AppVersion(
            app_id=app.id,
            version_no=2,
            kind=VERSION_KIND_ITERATION,
            code_object_key="apps/x/v2/code.tar.gz",
            manifest=manifest,
            capabilities={},
            injections={},
            tier_id="standard",
            runtime="python3.11",
        )
        await AppVersionDao.ainsert(session, second)
        await session.commit()
        second_id = second.id
    await AppStateService.stage_version(app.id, second_id)
    return app, second_id


class TestResumeBuildsTheStagedVersionsTables:
    async def test_resume_migrates_before_the_instance_is_deployed(
        self, app_db, app_factory, app_owner, fake_orchestrator
    ):
        """Order is the property, as it is on the publish path: a refusal must
        cost the application nothing, and an instance must never be handed a
        database that is a release behind its code."""
        from bisheng.app_runtime.domain.services.app_state_service import AppStateService

        app, _ = await _staged_second_version(
            app_db, app_factory, tables=[{"name": "orders", "columns": [{"name": "id", "type": "INTEGER"}]}]
        )

        result = await AppStateService.resume(app.id, actor=app_owner.payload)

        assert result.ok is True
        names = [name for name, _ in fake_orchestrator.calls]
        assert "schema_migrate" in names, "the staged version's declared tables were never built"
        assert names.index("schema_migrate") < names.index("deploy")
        (_, kwargs) = fake_orchestrator.calls[names.index("schema_migrate")]
        assert [item["op"] for item in kwargs["plan"]] == ["create_table"]

    async def test_a_refused_migration_leaves_the_application_stopped(
        self, app_db, app_factory, app_owner, fake_orchestrator
    ):
        """16259 out of ``resume`` rather than a started instance.

        The owner pressed a button and gets told why it did not happen; the
        application stays where it was, on a database nobody touched.
        """
        from bisheng.app_runtime.domain.services.app_state_service import AppStateService
        from bisheng.common.errcode.app_publish import AppSchemaMigrationFailedError
        from bisheng.database.models.app import AppDao

        app, _ = await _staged_second_version(
            app_db,
            app_factory,
            tables=[{"name": "orders", "columns": [{"name": "owner", "type": "TEXT", "nullable": False}]}],
        )
        fake_orchestrator.responses["schema_migrate"] = AppSchemaMigrationFailedError(
            msg="column 'owner' is declared NOT NULL without a default",
            manager_code="schema_migration_failed",
            reason="notnull_without_default",
        )

        with pytest.raises(AppSchemaMigrationFailedError):
            await AppStateService.resume(app.id, actor=app_owner.payload)

        assert "deploy" not in [name for name, _ in fake_orchestrator.calls]
        async with app_db() as session:
            row = await AppDao.aget(session, app.id)
        assert row.state == AppState.STOPPED.value

    async def test_a_resume_with_nothing_staged_costs_no_rpc(self, app_db, app_factory, app_owner, fake_orchestrator):
        """Restarting the version that is already current changed no declaration,
        so there is nothing to migrate and nothing to ask the manager about."""
        from bisheng.app_runtime.domain.services.app_state_service import AppStateService

        app, _ = await app_factory(state=AppState.STOPPED.value)

        await AppStateService.resume(app.id, actor=app_owner.payload)

        assert "schema_migrate" not in [name for name, _ in fake_orchestrator.calls]

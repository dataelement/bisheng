"""F112: validate before side effects and retain the accepted text across sessions."""

from unittest.mock import AsyncMock

import pytest


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (None, None),
        ("", None),
        (" \r\n\t", None),
        ("  First\r\n  Second\rThird  ", "First\n  Second\nThird"),
        ("新功能😀" * 400, "新功能😀" * 400),
        ("x" * 2000, "x" * 2000),
        ("😀" * 2000, "😀" * 2000),
    ],
    ids=["null", "empty", "whitespace", "newlines", "unicode", "limit", "emoji-limit"],
)
def test_normalizes_without_changing_internal_text(raw, expected):
    from bisheng.app_publish.domain.release_notes import normalize_release_notes

    assert normalize_release_notes(raw) == expected


@pytest.mark.parametrize("raw", ["x" * 2001, "😀" * 2001], ids=["ascii", "emoji"])
def test_too_long_never_echoes_text(raw):
    from bisheng.app_publish.domain.release_notes import normalize_release_notes
    from bisheng.common.errcode.app_publish import AppReleaseNotesInvalidError

    with pytest.raises(AppReleaseNotesInvalidError) as caught:
        normalize_release_notes(raw)
    assert caught.value.code == 16233
    assert caught.value.kwargs["details"] == {"reason": "too_long", "max_codepoints": 2000}
    assert raw not in str(caught.value)


async def test_rejects_before_creating_app_storing_package_or_scheduling(app_runtime_settings, monkeypatch, tmp_path):
    from bisheng.app_publish.domain.services import publish_pipeline_service as pipeline
    from bisheng.common.errcode.app_publish import AppReleaseNotesInvalidError

    app_runtime_settings(enabled=True)
    create = AsyncMock()
    store = AsyncMock()
    schedule = AsyncMock()
    monkeypatch.setattr(pipeline.PublishPipelineService, "_create_draft", create)
    monkeypatch.setattr(pipeline.package_service, "store_package", store)
    monkeypatch.setattr(pipeline, "enqueue_pipeline", schedule)
    with pytest.raises(AppReleaseNotesInvalidError):
        await pipeline.PublishPipelineService.accept(
            package_path=tmp_path / "absent", principal=None, release_notes="x" * 2001
        )
    create.assert_not_called()
    store.assert_not_called()
    schedule.assert_not_called()


@pytest.mark.parametrize("notes", [None, "  New feature\r\n  Fixed issue  "])
async def test_accept_persists_notes_for_a_separate_worker_session(
    notes,
    publish_db,
    tier_seed,
    tarball_factory,
    fake_minio,
    service_account_principal,
    fake_f054_services,
    audit_sink,
    app_runtime_settings,
    monkeypatch,
):
    from bisheng.app_publish.domain.models.app_deployment import AppDeploymentDao
    from bisheng.app_publish.domain.services import publish_pipeline_service as pipeline
    from bisheng.core.context.tenant import set_current_tenant_id

    set_current_tenant_id(1)
    app_runtime_settings(enabled=True)
    schedule = AsyncMock()
    monkeypatch.setattr(pipeline, "enqueue_pipeline", schedule)
    result = await pipeline.PublishPipelineService.accept(
        package_path=tarball_factory(), principal=service_account_principal(), release_notes=notes
    )
    async with publish_db() as session:
        row = await AppDeploymentDao.aget(session, result.deployment_id)
        assert row.release_notes == ("New feature\n  Fixed issue" if notes else None)
    schedule.assert_awaited_once_with(result.deployment_id)


def test_migration_is_idempotent_and_keeps_old_rows_null():
    import importlib

    import sqlalchemy as sa
    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    migration = importlib.import_module("bisheng.core.database.alembic.versions.v3_0_0_f112_release_notes")
    engine = sa.create_engine("sqlite://")
    with engine.begin() as connection:
        for table in ("app_deployment", "app_version"):
            connection.execute(sa.text(f"CREATE TABLE {table} (id INTEGER PRIMARY KEY)"))
            connection.execute(sa.text(f"INSERT INTO {table} (id) VALUES (1)"))
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
            migration.upgrade()
            for table in ("app_deployment", "app_version"):
                assert connection.execute(sa.text(f"SELECT release_notes FROM {table}")).scalar() is None
            migration.downgrade()
            migration.downgrade()
        for table in ("app_deployment", "app_version"):
            assert "release_notes" not in {column["name"] for column in sa.inspect(connection).get_columns(table)}
    engine.dispose()

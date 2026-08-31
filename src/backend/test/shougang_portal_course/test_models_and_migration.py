from __future__ import annotations

import importlib
import inspect

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import UniqueConstraint, create_engine
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.dialects import mysql, sqlite
from sqlalchemy.schema import CreateTable
from sqlalchemy.types import Text

from bisheng.core.database.dialect_helpers import LargeText

F062_TABLES = {
    "portal_course",
    "portal_course_video",
    "portal_course_video_progress",
    "portal_course_media_cleanup",
}

EXPECTED_TABLES = {
    *F062_TABLES,
    "portal_course_catalog",
}


def _models():
    module = importlib.import_module("bisheng.shougang_portal_course.domain.models.portal_course")
    return (
        module.PortalCourse,
        module.PortalCourseVideo,
        module.PortalCourseVideoProgress,
        module.PortalCourseMediaCleanup,
        module.PortalCourseCatalog,
    )


def test_course_models_define_exactly_five_tenant_aware_tables():
    models = _models()

    assert {model.__tablename__ for model in models} == EXPECTED_TABLES
    assert "portal_course_tag" not in models[0].metadata.tables
    for model in models:
        tenant = model.__table__.c.tenant_id
        assert tenant.nullable is False


def test_course_tags_use_non_nullable_large_text_and_preserve_order():
    PortalCourse, *_ = _models()
    tags_column = PortalCourse.__table__.c.tags_json

    assert isinstance(tags_column.type, LargeText)
    assert tags_column.nullable is False
    course = PortalCourse(
        tenant_id=1,
        name="安全生产",
        create_user=7,
        tags_json=('[{"label":"炼钢","display_type":"domain"},{"label":"初级","display_type":"level"}]'),
    )
    assert course.tags_json.index("炼钢") < course.tags_json.index("初级")


def test_progress_has_tenant_user_video_unique_constraint():
    _, _, PortalCourseVideoProgress, *_ = _models()
    matching = []
    for constraint in PortalCourseVideoProgress.__table__.constraints:
        if isinstance(constraint, UniqueConstraint):
            columns = tuple(column.name for column in constraint.columns)
            if columns == ("tenant_id", "user_id", "video_id"):
                matching.append(constraint)

    assert len(matching) == 1


def test_course_tables_compile_without_native_json_or_database_enum():
    for model in _models():
        mysql_sql = str(CreateTable(model.__table__).compile(dialect=mysql.dialect()))
        sqlite_sql = str(CreateTable(model.__table__).compile(dialect=sqlite.dialect()))
        combined = f"{mysql_sql}\n{sqlite_sql}".upper()

        assert " ENUM(" not in combined
        assert " JSON " not in combined
        assert "ON DELETE CASCADE" not in combined

    PortalCourse, *_ = _models()
    course_mysql_sql = str(CreateTable(PortalCourse.__table__).compile(dialect=mysql.dialect())).upper()
    assert "DESCRIPTION TEXT NOT NULL DEFAULT" not in course_mysql_sql
    assert "TAGS_JSON LONGTEXT NOT NULL DEFAULT" not in course_mysql_sql
    assert isinstance(
        PortalCourse.__table__.c.tags_json.type.load_dialect_impl(sqlite.dialect()),
        Text,
    )


def test_f062_migration_has_parent_first_upgrade_and_child_first_downgrade():
    migration = importlib.import_module("bisheng.core.database.alembic.versions.v2_6_0_f062_add_portal_course_tables")
    source = inspect.getsource(migration)

    assert migration.revision == "f062_add_portal_course_tables"
    assert migration.down_revision == "f060_department_multiple_spaces"
    assert "portal_course_tag" not in source

    upgrade_source = inspect.getsource(migration.upgrade)
    assert upgrade_source.index('"portal_course"') < upgrade_source.index('"portal_course_video"')
    assert upgrade_source.index('"portal_course_video"') < upgrade_source.index('"portal_course_video_progress"')

    downgrade_source = inspect.getsource(migration.downgrade)
    assert downgrade_source.index('"portal_course_video_progress"') < downgrade_source.index('"portal_course_video"')
    assert downgrade_source.index('"portal_course_video"') < downgrade_source.index('"portal_course"')


def test_f062_migration_upgrade_and_downgrade_on_disposable_database():
    migration = importlib.import_module("bisheng.core.database.alembic.versions.v2_6_0_f062_add_portal_course_tables")
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        original_op = migration.op
        migration.op = Operations(MigrationContext.configure(connection))
        try:
                migration.upgrade()
                assert F062_TABLES <= set(sa_inspect(connection).get_table_names())
                migration.downgrade()
                assert F062_TABLES.isdisjoint(sa_inspect(connection).get_table_names())
        finally:
            migration.op = original_op
    engine.dispose()


def test_tenant_filter_force_imports_course_models():
    from bisheng.core.database import tenant_filter

    assert "bisheng.shougang_portal_course.domain.models.portal_course" in tenant_filter._TENANT_AWARE_MODEL_MODULES


def test_f102_migration_adds_catalog_table_and_course_catalog_id():
    migration = importlib.import_module("bisheng.core.database.alembic.versions.v2_6_0_f102_portal_course_catalog")
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        original_op = migration.op
        migration.op = Operations(MigrationContext.configure(connection))
        try:
            connection.exec_driver_sql("CREATE TABLE portal_course (id CHAR(32) PRIMARY KEY, tenant_id INTEGER)")
            migration.upgrade()
            tables = set(sa_inspect(connection).get_table_names())
            assert "portal_course_catalog" in tables
            columns = {item["name"] for item in sa_inspect(connection).get_columns("portal_course")}
            assert "catalog_id" in columns
            migration.downgrade()
            tables = set(sa_inspect(connection).get_table_names())
            assert "portal_course_catalog" not in tables
        finally:
            migration.op = original_op
    engine.dispose()


def test_f103_migration_adds_course_type_and_external_url():
    migration = importlib.import_module(
        "bisheng.core.database.alembic.versions.v2_6_0_f103_portal_course_external_type"
    )
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        original_op = migration.op
        migration.op = Operations(MigrationContext.configure(connection))
        try:
            connection.exec_driver_sql(
                "CREATE TABLE portal_course (id CHAR(32) PRIMARY KEY, tenant_id INTEGER)"
            )
            migration.upgrade()
            columns = {item["name"] for item in sa_inspect(connection).get_columns("portal_course")}
            assert "course_type" in columns
            assert "external_url" in columns
            migration.downgrade()
            columns = {item["name"] for item in sa_inspect(connection).get_columns("portal_course")}
            assert "course_type" not in columns
            assert "external_url" not in columns
        finally:
            migration.op = original_op
    engine.dispose()


def test_f104_migration_adds_external_import_fields():
    migration = importlib.import_module(
        "bisheng.core.database.alembic.versions.v2_6_0_f104_portal_course_external_import"
    )
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        original_op = migration.op
        migration.op = Operations(MigrationContext.configure(connection))
        try:
            connection.exec_driver_sql(
                "CREATE TABLE portal_course (id CHAR(32) PRIMARY KEY, tenant_id INTEGER)"
            )
            migration.upgrade()
            columns = {item["name"] for item in sa_inspect(connection).get_columns("portal_course")}
            assert "external_id" in columns
            assert "cover_url" in columns
            assert "source_updated_at" in columns
            migration.downgrade()
            columns = {item["name"] for item in sa_inspect(connection).get_columns("portal_course")}
            assert "external_id" not in columns
            assert "cover_url" not in columns
            assert "source_updated_at" not in columns
        finally:
            migration.op = original_op
    engine.dispose()

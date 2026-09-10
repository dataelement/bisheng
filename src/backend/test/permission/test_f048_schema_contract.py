"""F048 schema contract tests.

覆盖 AC: AC-137, AC-138, AC-139, AC-140, AC-146, AC-158
"""

from __future__ import annotations

import ast
from pathlib import Path

import sqlalchemy as sa
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from sqlalchemy import inspect
from sqlalchemy.dialects import mysql
from sqlalchemy.schema import CreateTable
from sqlmodel import SQLModel

from bisheng.common.models.base import SQLModelSerializable
from bisheng.core.database import tenant_filter
from bisheng.core.database.alembic.versions import f048_permission_model_grants as revision
from bisheng.core.database.alembic.versions import (
    v3_0_0_f048_migration_item_message_longtext as message_revision,
)
from bisheng.core.database.alembic.versions import (
    v3_0_0_f048_visible_source_projection as visible_revision,
)
from bisheng.core.database.dialect_helpers import LargeText
from bisheng.core.openfga.authorization_model_f048 import (
    DEFAULT_ACTION_CODES,
    FLAT_VISIBLE_RESOURCE_TYPES,
    MIGRATED_RESOURCE_TYPES,
    OWNER_PROJECTION_RESOURCE_TYPES,
    PARENT_TYPES,
    RESOURCE_ACTION_SCOPES,
    SYSTEM_SHARED_ACTION_TYPES,
    build_authorization_model_f048,
)
from bisheng.permission.domain import models as permission_models
from bisheng.permission.domain.services import catalog_policy

BACKEND_ROOT = Path(__file__).resolve().parents[2]
REVISION_PATH = BACKEND_ROOT / "bisheng/core/database/alembic/versions/f048_permission_model_grants.py"
MESSAGE_REVISION_PATH = (
    BACKEND_ROOT / "bisheng/core/database/alembic/versions/v3_0_0_f048_migration_item_message_longtext.py"
)
VISIBLE_REVISION_PATH = BACKEND_ROOT / "bisheng/core/database/alembic/versions/v3_0_0_f048_visible_source_projection.py"

F048_TABLES = {
    "authorization_model_release",
    "permission_catalog_release",
    "permission_action",
    "permission_action_resource_scope",
    "permission_model",
    "permission_model_action",
    "permission_catalog_projection_tuple",
    "permission_grant",
    "permission_grant_assignee",
    "resource_permission_mode",
    "permission_projection_operation",
    "permission_projection_tuple",
    "permission_visible_source_projection",
    "permission_migration_run",
    "permission_migration_item",
}
BASE_REVISION_TABLES = F048_TABLES - {"permission_visible_source_projection"}

TENANT_TABLES = {
    "permission_grant",
    "permission_grant_assignee",
    "resource_permission_mode",
    "permission_projection_operation",
    "permission_projection_tuple",
    "permission_visible_source_projection",
}


def test_f048_models_register_complete_portable_schema() -> None:
    """All F048 ORM tables have audit timestamps and portable scalar types."""

    assert permission_models.PermissionGrant.__tablename__ == "permission_grant"
    tables = SQLModel.metadata.tables
    assert F048_TABLES <= set(tables)
    for name in F048_TABLES:
        table = tables[name]
        assert {"id", "create_time", "update_time"} <= set(table.c.keys())
        model = next(
            candidate
            for candidate in SQLModelSerializable.__subclasses__()
            if getattr(candidate, "__tablename__", None) == name
        )
        assert issubclass(model, SQLModelSerializable)
        for column in table.c:
            assert not isinstance(column.type, sa.JSON)
            assert not isinstance(column.type, sa.Enum)


def test_tenant_tables_are_non_nullable_and_discovered() -> None:
    tenant_filter._force_import_all_models()
    discovered = tenant_filter._discover_tenant_aware_tables()
    assert TENANT_TABLES <= discovered
    for name in TENANT_TABLES:
        assert SQLModel.metadata.tables[name].c.tenant_id.nullable is False

    migration_item = SQLModel.metadata.tables["permission_migration_item"]
    assert migration_item.c.tenant_id.nullable is True
    assert isinstance(migration_item.c.message.type, LargeText)
    assert "permission_catalog_release" not in discovered
    assert "permission_migration_run" not in discovered


def test_migration_item_message_compiles_to_mysql_longtext() -> None:
    migration_item = SQLModel.metadata.tables["permission_migration_item"]
    ddl = str(CreateTable(migration_item).compile(dialect=mysql.dialect())).upper()

    assert "MESSAGE LONGTEXT" in ddl


def test_f048_unique_and_foreign_key_contract() -> None:
    tables = SQLModel.metadata.tables
    unique_names = {
        constraint.name
        for table_name in F048_TABLES
        for constraint in tables[table_name].constraints
        if isinstance(constraint, sa.UniqueConstraint)
    }
    assert {
        "uq_perm_catalog_release_key",
        "uq_perm_action_release_code",
        "uq_perm_model_release_key",
        "uq_perm_grant_resource_model",
        "uq_perm_assignee_source",
        "uq_resource_permission_mode",
        "uq_perm_projection_idempotency",
        "uq_perm_projection_tuple",
        "uq_perm_visible_source_contribution",
        "uq_perm_migration_environment",
        "uq_perm_migration_item_source",
    } <= unique_names

    foreign_targets = {fk.target_fullname for table_name in F048_TABLES for fk in tables[table_name].foreign_keys}
    assert {
        "authorization_model_release.id",
        "permission_catalog_release.id",
        "permission_action.id",
        "permission_model.id",
        "permission_grant.id",
        "permission_projection_operation.id",
        "permission_migration_run.id",
    } <= foreign_targets


def test_f048_revision_is_on_the_single_alembic_head_chain() -> None:
    """One head, and every F048 revision is on its ancestry — no parallel branch.

    Asserts the property rather than pinning the head to F048 by name: every
    later migration legitimately becomes the new head, so a name-pinned
    assertion fails for each one while catching nothing extra. (It used to pin
    ``f048_migration_item_message_longtext``; F049's ``f049_user_user_type`` was
    the first release it falsely failed.)
    """
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.set_main_option(
        "script_location",
        str(BACKEND_ROOT / "bisheng/core/database/alembic"),
    )
    script = ScriptDirectory.from_config(config)
    heads = script.get_heads()
    assert len(heads) == 1, f"alembic graph forked: {heads}"
    chain = {rev.revision for rev in script.walk_revisions("base", heads[0])}
    # Both lines' F048 revisions: the grants/message pair from 3.0-vibe and the
    # visibility projection from beta1. The merge is the first time all three
    # have to be on one chain.
    assert {
        "f048_permission_grants",
        "f048_migration_item_message_longtext",
        "f048_visible_source_projection",
    } <= chain


def test_f048_visible_projection_revision_is_static_ddl_only() -> None:
    source = VISIBLE_REVISION_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source)
    called_names = {
        node.func.attr for node in ast.walk(tree) if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }

    assert visible_revision.down_revision == "linsight_pending_files"
    assert visible_revision.revision == "f048_visible_source_projection"
    assert {"create_table", "create_index", "drop_table"} <= called_names
    assert not {"execute", "bulk_insert"} & called_names


def test_f048_visible_projection_revision_is_idempotent_and_downgrades() -> None:
    engine = sa.create_engine("sqlite://")
    with engine.connect() as connection:
        context = MigrationContext.configure(connection)
        with Operations.context(context):
            visible_revision.upgrade()
            assert "permission_visible_source_projection" in inspect(connection).get_table_names()
            visible_revision.upgrade()
            visible_revision.downgrade()
            assert "permission_visible_source_projection" not in inspect(connection).get_table_names()


def test_f048_message_revision_is_static_ddl_only() -> None:
    source = MESSAGE_REVISION_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source)
    called_names = {
        node.func.attr for node in ast.walk(tree) if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }

    assert message_revision.down_revision == "f048_permission_grants"
    assert message_revision.revision == "f048_migration_item_message_longtext"
    assert "alter_column" in called_names
    assert not {"execute", "bulk_insert"} & called_names


def test_f048_revision_is_static_ddl_only() -> None:
    source = REVISION_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source)

    imported_modules = {alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
    imported_modules |= {node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
    assert imported_modules <= {
        "__future__",
        "collections.abc",
        "sqlalchemy",
        "alembic",
        "bisheng.core.database.alembic_helpers.online",
    }

    forbidden_calls = {
        "execute",
        "bulk_insert",
        "get_context",
        "get_bind().execute",
    }
    call_names = {_qualified_name(node.func) for node in ast.walk(tree) if isinstance(node, ast.Call)}
    assert not (forbidden_calls & call_names)
    assert all("openfga" not in module.casefold() for module in imported_modules)
    assert "config_service" not in source
    assert "permission.domain.services" not in source
    assert "scripts." not in source


def test_f048_revision_upgrade_is_idempotent_and_downgrades() -> None:
    engine = sa.create_engine("sqlite://")
    with engine.connect() as connection:
        context = MigrationContext.configure(connection)
        with Operations.context(context):
            revision.upgrade()
            assert BASE_REVISION_TABLES <= set(inspect(connection).get_table_names())
            revision.upgrade()
            revision.downgrade()
            assert not (BASE_REVISION_TABLES & set(inspect(connection).get_table_names()))


def test_f048_tables_compile_for_mysql_without_native_enum_or_json() -> None:
    for name in F048_TABLES:
        ddl = str(CreateTable(SQLModel.metadata.tables[name]).compile(dialect=mysql.dialect()))
        normalized = ddl.upper()
        assert " JSON" not in normalized
        assert " ENUM(" not in normalized


def test_service_account_is_only_an_ordinary_direct_grant_subject() -> None:
    model = build_authorization_model_f048()
    definitions = {definition["type"]: definition for definition in model["type_definitions"]}
    assert "service_account" in definitions

    ordinary = definitions["permission_grant"]["metadata"]["relations"]["ordinary_assignee"]
    protected = definitions["permission_grant"]["metadata"]["relations"]["protected_assignee"]
    assert {entry["type"] for entry in ordinary["directly_related_user_types"]} >= {
        "user",
        "service_account",
    }
    assert {entry["type"] for entry in protected["directly_related_user_types"]} == {"user"}

    for protected_type, relation in (
        ("system", "super_admin"),
        ("tenant", "admin"),
        ("department", "admin"),
        ("user_group", "admin"),
    ):
        allowed = definitions[protected_type]["metadata"]["relations"][relation]["directly_related_user_types"]
        assert "service_account" not in {entry["type"] for entry in allowed}

    for type_name, relations in (
        ("permission_catalog_release", ("active",)),
        (
            "permission_model_release",
            ("enabled_marker", "edit_marker", "grant_level_1_marker"),
        ),
        ("knowledge_space", ("permission_enabled", "custom_mode")),
        ("knowledge_file", ("permission_enabled", "custom_mode", "inherit_mode")),
    ):
        for relation in relations:
            allowed = definitions[type_name]["metadata"]["relations"][relation]["directly_related_user_types"]
            assert {entry["type"] for entry in allowed} == {
                "service_account",
                "user",
            }

    for relation in ("public_reader", "system_download_marker", "system_use_marker"):
        allowed = definitions["knowledge_space"]["metadata"]["relations"][relation]["directly_related_user_types"]
        assert {entry["type"] for entry in allowed} == {"user"}


def test_catalog_policy_and_authorization_model_resource_lists_are_twins() -> None:
    """The Catalog validator and the model builder enumerate the same resources.

    ``catalog_policy`` validates every Catalog row on snapshot load; the model
    builder decides which object types OpenFGA accepts tuples for. A type in
    one list but not the other fails only at runtime (Catalog reads raise, or
    every tuple write 400s), so the two lists are held equal here — as whole
    sets and per action, not just for the type that was added last.
    """

    assert set(MIGRATED_RESOURCE_TYPES) == catalog_policy.MIGRATED_RESOURCE_TYPES
    assert set(DEFAULT_ACTION_CODES) == set(catalog_policy.REGISTERED_ACTION_CODES)
    assert set(RESOURCE_ACTION_SCOPES) == set(DEFAULT_ACTION_CODES)
    assert set(catalog_policy.ACTION_RESOURCE_SCOPES) == set(DEFAULT_ACTION_CODES)
    for action in DEFAULT_ACTION_CODES:
        assert RESOURCE_ACTION_SCOPES[action] == catalog_policy.ACTION_RESOURCE_SCOPES[action], action
        assert RESOURCE_ACTION_SCOPES[action] <= set(MIGRATED_RESOURCE_TYPES), action

    # Every Catalog-scoped type is a modelled object type, so a Catalog row can
    # never reference a type OpenFGA would reject.
    model = build_authorization_model_f048()
    modelled = {definition["type"] for definition in model["type_definitions"]}
    assert catalog_policy.MIGRATED_RESOURCE_TYPES <= modelled
    assert set(OWNER_PROJECTION_RESOURCE_TYPES) <= modelled

    # `app` (F054) is on both sides and is a flat, never-system-shared type.
    assert "app" in MIGRATED_RESOURCE_TYPES
    assert "app" in catalog_policy.MIGRATED_RESOURCE_TYPES
    assert "app" in FLAT_VISIBLE_RESOURCE_TYPES
    assert "app" not in PARENT_TYPES
    assert all("app" not in shared_types for shared_types in SYSTEM_SHARED_ACTION_TYPES.values())


def test_app_resource_type_is_shaped_like_the_other_flat_resource_types() -> None:
    """The union model gives ``app`` every subject the other flat types have.

    ``app`` came from one line and the ``service_account`` subject type from
    the other. The merge is correct only if the type that arrived last is
    built by the same code path as its peers: same technical-marker subjects,
    same ordinary assignees, same visibility subjects, no parent or inherit
    relations. ``dashboard`` is the reference because, like ``app``, it is
    flat and appears in no ``SYSTEM_SHARED_ACTION_TYPES`` entry.
    """

    model = build_authorization_model_f048()
    definitions = {definition["type"]: definition for definition in model["type_definitions"]}
    app = definitions["app"]
    reference = dict(definitions["dashboard"], type="app")
    assert app == reference

    metadata = app["metadata"]["relations"]
    for relation in ("permission_enabled", "custom_mode"):
        assert {entry["type"] for entry in metadata[relation]["directly_related_user_types"]} == {
            "service_account",
            "user",
        }
    assert {"type": "service_account"} in metadata["visible"]["directly_related_user_types"]
    assert "parent" not in app["relations"]
    assert "inherit_mode" not in app["relations"]
    assert app["relations"]["visible"] == {
        "union": {
            "child": [
                {"this": {}},
                {"computedUserset": {"relation": "system_visible"}},
            ]
        }
    }
    assert {f"can_{action}" for action in DEFAULT_ACTION_CODES} <= set(app["relations"])


def _qualified_name(node: ast.expr) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        prefix = _qualified_name(node.value)
        return f"{prefix}.{node.attr}" if prefix else node.attr
    if isinstance(node, ast.Call):
        return _qualified_name(node.func)
    return ""

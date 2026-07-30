"""F048 permission Catalog, Grant, projection, and migration audit tables.

This revision is intentionally DDL-only. F048 business-data conversion is a
separate maintenance operation executed after the schema is at head.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from bisheng.core.database.alembic_helpers.online import (
    column_exists,
    index_exists,
    table_exists,
)

revision: str = "f048_permission_grants"
down_revision: str | Sequence[str] | None = "f044_llm_status_time"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_DASHBOARD_TABLE = "dashboard"
_DASHBOARD_TENANT_COLUMN = "tenant_id"
_DASHBOARD_TENANT_INDEX = "ix_dashboard_tenant_id"
_DEPARTMENT_TABLE = "department"
_DEPARTMENT_PROJECTION_COLUMNS = (
    (
        "permission_projection_version",
        sa.Column(
            "permission_projection_version",
            sa.BigInteger(),
            nullable=False,
            server_default=sa.text("0"),
            comment="F048 department identity projection version",
        ),
    ),
    (
        "permission_projection_state",
        sa.Column(
            "permission_projection_state",
            sa.String(64),
            nullable=False,
            server_default=sa.text("'CURRENT'"),
            comment="F048 department identity projection state",
        ),
    ),
    (
        "permission_projection_operation_id",
        sa.Column(
            "permission_projection_operation_id",
            sa.BigInteger(),
            nullable=True,
            comment="F048 durable projection operation ID",
        ),
    ),
)
_DEPARTMENT_PROJECTION_INDEX = "ix_department_permission_projection"


def _timestamps() -> tuple[sa.Column, sa.Column]:
    return (
        sa.Column(
            "create_time",
            sa.DateTime,
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "update_time",
            sa.DateTime,
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
            onupdate=sa.text("CURRENT_TIMESTAMP"),
        ),
    )


def _create_table(
    name: str,
    *elements: sa.Column | sa.Constraint,
    indexes: tuple[tuple[str, tuple[str, ...]], ...] = (),
) -> None:
    if table_exists(name):
        return
    op.create_table(
        name,
        *elements,
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_unicode_ci",
    )
    for index_name, columns in indexes:
        op.create_index(index_name, name, list(columns))


def _drop_table(name: str) -> None:
    if table_exists(name):
        op.drop_table(name)


def _create_authorization_model_release() -> None:
    _create_table(
        "authorization_model_release",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("environment", sa.String(64), nullable=False),
        sa.Column("store_id", sa.String(64), nullable=False),
        sa.Column("model_version", sa.String(64), nullable=False),
        sa.Column("model_id", sa.String(64), nullable=False),
        sa.Column("predecessor_model_id", sa.String(64), nullable=True),
        sa.Column("model_checksum", sa.CHAR(64), nullable=False),
        sa.Column("required_relations_checksum", sa.CHAR(64), nullable=False),
        sa.Column("openfga_version", sa.String(64), nullable=False),
        sa.Column(
            "status",
            sa.String(64),
            nullable=False,
            server_default=sa.text("'STAGED'"),
        ),
        sa.Column("activated_at", sa.DateTime, nullable=True),
        sa.Column("retired_at", sa.DateTime, nullable=True),
        *_timestamps(),
        sa.UniqueConstraint(
            "environment",
            "store_id",
            "model_id",
            name="uq_auth_model_release",
        ),
        indexes=(
            (
                "ix_auth_model_release_status",
                ("environment", "status", "activated_at"),
            ),
        ),
    )


def _create_catalog_release() -> None:
    _create_table(
        "permission_catalog_release",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("release_key", sa.String(64), nullable=False),
        sa.Column("version", sa.BigInteger, nullable=False),
        sa.Column(
            "status",
            sa.String(64),
            nullable=False,
            server_default=sa.text("'DRAFT'"),
        ),
        sa.Column(
            "write_fenced",
            sa.Boolean,
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "predecessor_id",
            sa.BigInteger,
            sa.ForeignKey(
                "permission_catalog_release.id",
                ondelete="RESTRICT",
            ),
            nullable=True,
        ),
        sa.Column(
            "required_authorization_model_release_id",
            sa.BigInteger,
            sa.ForeignKey(
                "authorization_model_release.id",
                ondelete="RESTRICT",
            ),
            nullable=False,
        ),
        sa.Column("draft_owner_id", sa.BigInteger, nullable=False),
        sa.Column("idempotency_key", sa.String(64), nullable=False),
        sa.Column(
            "projection_checkpoint",
            sa.BigInteger,
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("expires_at", sa.DateTime, nullable=True),
        sa.Column("published_at", sa.DateTime, nullable=True),
        sa.Column("checksum", sa.CHAR(64), nullable=False),
        sa.Column("commit_checksum", sa.CHAR(64), nullable=True),
        *_timestamps(),
        sa.UniqueConstraint("release_key", name="uq_perm_catalog_release_key"),
        sa.UniqueConstraint("version", name="uq_perm_catalog_version"),
        sa.UniqueConstraint(
            "idempotency_key",
            name="uq_perm_catalog_idempotency",
        ),
        indexes=(("ix_perm_catalog_status_version", ("status", "version")),),
    )


def _create_catalog_children() -> None:
    _create_table(
        "permission_action",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column(
            "catalog_release_id",
            sa.BigInteger,
            sa.ForeignKey(
                "permission_catalog_release.id",
                ondelete="RESTRICT",
            ),
            nullable=False,
        ),
        sa.Column("code", sa.String(64), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("level", sa.Integer, nullable=True),
        sa.Column(
            "active",
            sa.Boolean,
            nullable=False,
            server_default=sa.text("1"),
        ),
        sa.Column(
            "sort_order",
            sa.Integer,
            nullable=False,
            server_default=sa.text("0"),
        ),
        *_timestamps(),
        sa.UniqueConstraint(
            "catalog_release_id",
            "code",
            name="uq_perm_action_release_code",
        ),
        indexes=(
            (
                "ix_perm_action_release_active",
                ("catalog_release_id", "active"),
            ),
        ),
    )
    _create_table(
        "permission_action_resource_scope",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column(
            "action_id",
            sa.BigInteger,
            sa.ForeignKey("permission_action.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("resource_type", sa.String(64), nullable=False),
        *_timestamps(),
        sa.UniqueConstraint(
            "action_id",
            "resource_type",
            name="uq_perm_action_resource_scope",
        ),
        indexes=(
            (
                "ix_permission_action_resource_scope_action_id",
                ("action_id",),
            ),
        ),
    )
    _create_table(
        "permission_model",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column(
            "catalog_release_id",
            sa.BigInteger,
            sa.ForeignKey(
                "permission_catalog_release.id",
                ondelete="RESTRICT",
            ),
            nullable=False,
        ),
        sa.Column("model_key", sa.String(64), nullable=False),
        sa.Column("normalized_name", sa.String(255), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("kind", sa.String(64), nullable=False),
        sa.Column(
            "config_scope",
            sa.String(64),
            nullable=False,
            server_default=sa.text("'PLATFORM'"),
        ),
        sa.Column("derived_level", sa.Integer, nullable=True),
        sa.Column(
            "active",
            sa.Boolean,
            nullable=False,
            server_default=sa.text("1"),
        ),
        sa.Column(
            "allow_same_level",
            sa.Boolean,
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("legacy_source_key", sa.String(64), nullable=True),
        *_timestamps(),
        sa.UniqueConstraint(
            "catalog_release_id",
            "model_key",
            name="uq_perm_model_release_key",
        ),
        sa.UniqueConstraint(
            "catalog_release_id",
            "normalized_name",
            name="uq_perm_model_release_name",
        ),
        indexes=(
            (
                "ix_perm_model_release_active",
                ("catalog_release_id", "active"),
            ),
        ),
    )
    _create_table(
        "permission_model_action",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column(
            "model_id",
            sa.BigInteger,
            sa.ForeignKey("permission_model.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "action_id",
            sa.BigInteger,
            sa.ForeignKey("permission_action.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        *_timestamps(),
        sa.UniqueConstraint(
            "model_id",
            "action_id",
            name="uq_perm_model_action",
        ),
        indexes=(
            ("ix_permission_model_action_model_id", ("model_id",)),
            ("ix_permission_model_action_action_id", ("action_id",)),
        ),
    )
    _create_table(
        "permission_catalog_projection_tuple",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column(
            "catalog_release_id",
            sa.BigInteger,
            sa.ForeignKey(
                "permission_catalog_release.id",
                ondelete="RESTRICT",
            ),
            nullable=False,
        ),
        sa.Column("phase", sa.String(64), nullable=False),
        sa.Column("sequence", sa.BigInteger, nullable=False),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("fga_user", sa.String(256), nullable=False),
        sa.Column("relation", sa.String(64), nullable=False),
        sa.Column("fga_object", sa.String(256), nullable=False),
        sa.Column("tuple_fingerprint", sa.CHAR(64), nullable=False),
        sa.Column("status", sa.String(64), nullable=False),
        *_timestamps(),
        sa.UniqueConstraint(
            "catalog_release_id",
            "phase",
            "tuple_fingerprint",
            name="uq_perm_catalog_tuple",
        ),
        indexes=(
            (
                "ix_perm_catalog_tuple_status",
                ("catalog_release_id", "status", "sequence"),
            ),
        ),
    )


def _create_projection_tables() -> None:
    _create_table(
        "permission_projection_operation",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("tenant_id", sa.BigInteger, nullable=False),
        sa.Column("idempotency_key", sa.String(64), nullable=False),
        sa.Column("request_checksum", sa.CHAR(64), nullable=False),
        sa.Column("operation_type", sa.String(64), nullable=False),
        sa.Column("scope_type", sa.String(64), nullable=False),
        sa.Column("scope_key", sa.String(256), nullable=False),
        sa.Column("expected_version", sa.BigInteger, nullable=False),
        sa.Column("target_version", sa.BigInteger, nullable=False),
        sa.Column("store_id", sa.String(64), nullable=False),
        sa.Column("model_id", sa.String(64), nullable=False),
        sa.Column(
            "status",
            sa.String(64),
            nullable=False,
            server_default=sa.text("'PREPARED'"),
        ),
        sa.Column("before_checksum", sa.CHAR(64), nullable=False),
        sa.Column("after_checksum", sa.CHAR(64), nullable=False),
        sa.Column("commit_checksum", sa.CHAR(64), nullable=True),
        sa.Column("operator_id", sa.BigInteger, nullable=False),
        sa.Column("error_code", sa.BigInteger, nullable=True),
        sa.Column("error_message", sa.Text, nullable=True),
        *_timestamps(),
        sa.UniqueConstraint(
            "tenant_id",
            "idempotency_key",
            name="uq_perm_projection_idempotency",
        ),
        indexes=(
            (
                "ix_permission_projection_operation_tenant_id",
                ("tenant_id",),
            ),
            (
                "ix_perm_projection_retry",
                ("status", "update_time", "id"),
            ),
            (
                "ix_perm_projection_scope",
                ("tenant_id", "scope_type", "scope_key", "status"),
            ),
        ),
    )
    _create_table(
        "permission_projection_tuple",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("tenant_id", sa.BigInteger, nullable=False),
        sa.Column(
            "operation_id",
            sa.BigInteger,
            sa.ForeignKey(
                "permission_projection_operation.id",
                ondelete="RESTRICT",
            ),
            nullable=False,
        ),
        sa.Column("phase", sa.String(64), nullable=False),
        sa.Column("sequence", sa.BigInteger, nullable=False),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("fga_user", sa.String(256), nullable=False),
        sa.Column("relation", sa.String(64), nullable=False),
        sa.Column("fga_object", sa.String(256), nullable=False),
        sa.Column("tuple_fingerprint", sa.CHAR(64), nullable=False),
        sa.Column("inverse_action", sa.String(64), nullable=False),
        sa.Column(
            "status",
            sa.String(64),
            nullable=False,
            server_default=sa.text("'PENDING'"),
        ),
        *_timestamps(),
        sa.UniqueConstraint(
            "operation_id",
            "phase",
            "tuple_fingerprint",
            name="uq_perm_projection_tuple",
        ),
        indexes=(
            (
                "ix_permission_projection_tuple_tenant_id",
                ("tenant_id",),
            ),
            (
                "ix_perm_projection_tuple_status",
                ("operation_id", "status", "sequence"),
            ),
        ),
    )


def _create_grant_tables() -> None:
    _create_table(
        "permission_grant",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("tenant_id", sa.BigInteger, nullable=False),
        sa.Column("resource_type", sa.String(64), nullable=False),
        sa.Column("resource_id", sa.String(64), nullable=False),
        sa.Column("model_key", sa.String(64), nullable=False),
        sa.Column(
            "state",
            sa.String(64),
            nullable=False,
            server_default=sa.text("'PENDING'"),
        ),
        sa.Column(
            "version",
            sa.BigInteger,
            nullable=False,
            server_default=sa.text("1"),
        ),
        sa.Column(
            "projection_state",
            sa.String(64),
            nullable=False,
            server_default=sa.text("'PENDING'"),
        ),
        *_timestamps(),
        sa.UniqueConstraint(
            "tenant_id",
            "resource_type",
            "resource_id",
            "model_key",
            name="uq_perm_grant_resource_model",
        ),
        indexes=(
            ("ix_permission_grant_tenant_id", ("tenant_id",)),
            (
                "ix_perm_grant_resource_state",
                (
                    "tenant_id",
                    "resource_type",
                    "resource_id",
                    "state",
                    "id",
                ),
            ),
        ),
    )
    _create_table(
        "permission_grant_assignee",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("tenant_id", sa.BigInteger, nullable=False),
        sa.Column(
            "grant_id",
            sa.BigInteger,
            sa.ForeignKey("permission_grant.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("subject_type", sa.String(64), nullable=False),
        sa.Column("subject_id", sa.String(64), nullable=False),
        sa.Column("userset_relation", sa.String(64), nullable=True),
        sa.Column(
            "include_children",
            sa.Boolean,
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("source_type", sa.String(64), nullable=False),
        sa.Column("source_ref", sa.String(256), nullable=False),
        sa.Column("source_locator", sa.String(256), nullable=False),
        sa.Column("source_fingerprint", sa.CHAR(64), nullable=False),
        sa.Column("projected_subject", sa.String(256), nullable=False),
        sa.Column(
            "protected",
            sa.Boolean,
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "state",
            sa.String(64),
            nullable=False,
            server_default=sa.text("'PENDING'"),
        ),
        sa.Column(
            "version",
            sa.BigInteger,
            nullable=False,
            server_default=sa.text("1"),
        ),
        *_timestamps(),
        sa.UniqueConstraint(
            "tenant_id",
            "grant_id",
            "source_fingerprint",
            name="uq_perm_assignee_source",
        ),
        indexes=(
            ("ix_permission_grant_assignee_tenant_id", ("tenant_id",)),
            (
                "ix_perm_assignee_grant_state",
                ("tenant_id", "grant_id", "state", "id"),
            ),
            (
                "ix_perm_assignee_subject_state",
                ("tenant_id", "subject_type", "subject_id", "state"),
            ),
        ),
    )
    _create_table(
        "resource_permission_mode",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("tenant_id", sa.BigInteger, nullable=False),
        sa.Column("resource_type", sa.String(64), nullable=False),
        sa.Column("resource_id", sa.String(64), nullable=False),
        sa.Column("mode", sa.String(64), nullable=False),
        sa.Column("parent_type", sa.String(64), nullable=True),
        sa.Column("parent_id", sa.String(64), nullable=True),
        sa.Column(
            "version",
            sa.BigInteger,
            nullable=False,
            server_default=sa.text("1"),
        ),
        sa.Column(
            "projection_state",
            sa.String(64),
            nullable=False,
            server_default=sa.text("'PENDING'"),
        ),
        sa.Column(
            "operation_id",
            sa.BigInteger,
            sa.ForeignKey(
                "permission_projection_operation.id",
                ondelete="RESTRICT",
            ),
            nullable=True,
        ),
        *_timestamps(),
        sa.UniqueConstraint(
            "tenant_id",
            "resource_type",
            "resource_id",
            name="uq_resource_permission_mode",
        ),
        indexes=(
            ("ix_resource_permission_mode_tenant_id", ("tenant_id",)),
            (
                "ix_resource_mode_projection",
                ("tenant_id", "projection_state", "update_time"),
            ),
        ),
    )


def _create_migration_tables() -> None:
    _create_table(
        "permission_migration_run",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("environment_fingerprint", sa.CHAR(64), nullable=False),
        sa.Column("phase", sa.String(64), nullable=False),
        sa.Column(
            "status",
            sa.String(64),
            nullable=False,
            server_default=sa.text("'PENDING'"),
        ),
        sa.Column("store_id", sa.String(64), nullable=False),
        sa.Column("source_model_id", sa.String(64), nullable=False),
        sa.Column("target_model_id", sa.String(64), nullable=True),
        sa.Column("source_watermark", sa.String(256), nullable=True),
        sa.Column("checkpoint", sa.String(256), nullable=True),
        sa.Column("source_checksum", sa.CHAR(64), nullable=True),
        sa.Column("target_checksum", sa.CHAR(64), nullable=True),
        sa.Column(
            "scanned_count",
            sa.BigInteger,
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "migrated_count",
            sa.BigInteger,
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "skipped_count",
            sa.BigInteger,
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "blocker_count",
            sa.BigInteger,
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "manual_count",
            sa.BigInteger,
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "error_count",
            sa.BigInteger,
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("report_uri", sa.String(512), nullable=True),
        sa.Column("report_checksum", sa.CHAR(64), nullable=True),
        sa.Column("lock_token", sa.String(64), nullable=True),
        sa.Column("lock_expires_at", sa.DateTime, nullable=True),
        sa.Column(
            "version",
            sa.BigInteger,
            nullable=False,
            server_default=sa.text("1"),
        ),
        sa.Column(
            "manual_review_status",
            sa.String(64),
            nullable=False,
            server_default=sa.text("'NOT_REQUIRED'"),
        ),
        sa.Column("approved_by", sa.BigInteger, nullable=True),
        sa.Column("approved_at", sa.DateTime, nullable=True),
        *_timestamps(),
        sa.UniqueConstraint(
            "environment_fingerprint",
            name="uq_perm_migration_environment",
        ),
        indexes=(
            (
                "ix_perm_migration_run_status",
                ("status", "update_time", "id"),
            ),
        ),
    )
    _create_table(
        "permission_migration_item",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column(
            "run_id",
            sa.BigInteger,
            sa.ForeignKey(
                "permission_migration_run.id",
                ondelete="RESTRICT",
            ),
            nullable=False,
        ),
        sa.Column("tenant_id", sa.BigInteger, nullable=True),
        sa.Column("source_kind", sa.String(64), nullable=False),
        sa.Column("source_locator", sa.String(256), nullable=False),
        sa.Column("source_checksum", sa.CHAR(64), nullable=False),
        sa.Column("target_kind", sa.String(64), nullable=True),
        sa.Column("target_id", sa.String(64), nullable=True),
        sa.Column("target_checksum", sa.CHAR(64), nullable=True),
        sa.Column(
            "status",
            sa.String(64),
            nullable=False,
            server_default=sa.text("'PENDING'"),
        ),
        sa.Column("severity", sa.String(64), nullable=False),
        sa.Column("difference_type", sa.String(64), nullable=True),
        sa.Column("message", sa.Text, nullable=True),
        sa.Column("manual_action", sa.String(64), nullable=True),
        sa.Column("approved_by", sa.BigInteger, nullable=True),
        sa.Column("approved_at", sa.DateTime, nullable=True),
        sa.Column(
            "retry_count",
            sa.Integer,
            nullable=False,
            server_default=sa.text("0"),
        ),
        *_timestamps(),
        sa.UniqueConstraint(
            "run_id",
            "source_kind",
            "source_locator",
            name="uq_perm_migration_item_source",
        ),
        indexes=(
            ("ix_permission_migration_item_tenant_id", ("tenant_id",)),
            (
                "ix_perm_migration_item_resume",
                ("run_id", "status", "id"),
            ),
            (
                "ix_perm_migration_item_diff",
                ("run_id", "severity", "difference_type"),
            ),
        ),
    )


def upgrade() -> None:
    dashboard_exists = table_exists(_DASHBOARD_TABLE)
    if dashboard_exists and not column_exists(
        _DASHBOARD_TABLE,
        _DASHBOARD_TENANT_COLUMN,
    ):
        op.add_column(
            _DASHBOARD_TABLE,
            sa.Column(
                _DASHBOARD_TENANT_COLUMN,
                sa.Integer(),
                nullable=False,
                server_default=sa.text("1"),
                comment="Tenant ID",
            ),
        )
    if dashboard_exists and not index_exists(
        _DASHBOARD_TABLE,
        _DASHBOARD_TENANT_INDEX,
    ):
        op.create_index(
            _DASHBOARD_TENANT_INDEX,
            _DASHBOARD_TABLE,
            [_DASHBOARD_TENANT_COLUMN],
        )
    _create_authorization_model_release()
    _create_catalog_release()
    _create_catalog_children()
    _create_projection_tables()
    department_exists = table_exists(_DEPARTMENT_TABLE)
    if department_exists:
        for column_name, column in _DEPARTMENT_PROJECTION_COLUMNS:
            if not column_exists(_DEPARTMENT_TABLE, column_name):
                op.add_column(_DEPARTMENT_TABLE, column)
        if not index_exists(
            _DEPARTMENT_TABLE,
            _DEPARTMENT_PROJECTION_INDEX,
        ):
            op.create_index(
                _DEPARTMENT_PROJECTION_INDEX,
                _DEPARTMENT_TABLE,
                [
                    "tenant_id",
                    "permission_projection_state",
                    "permission_projection_operation_id",
                ],
            )
    _create_grant_tables()
    _create_migration_tables()


def downgrade() -> None:
    _drop_table("permission_migration_item")
    _drop_table("permission_migration_run")
    _drop_table("resource_permission_mode")
    _drop_table("permission_grant_assignee")
    _drop_table("permission_grant")
    _drop_table("permission_projection_tuple")
    _drop_table("permission_projection_operation")
    department_exists = table_exists(_DEPARTMENT_TABLE)
    if department_exists and index_exists(
        _DEPARTMENT_TABLE,
        _DEPARTMENT_PROJECTION_INDEX,
    ):
        op.drop_index(
            _DEPARTMENT_PROJECTION_INDEX,
            table_name=_DEPARTMENT_TABLE,
        )
    if department_exists:
        for column_name, _column in reversed(_DEPARTMENT_PROJECTION_COLUMNS):
            if column_exists(_DEPARTMENT_TABLE, column_name):
                op.drop_column(_DEPARTMENT_TABLE, column_name)
    _drop_table("permission_catalog_projection_tuple")
    _drop_table("permission_model_action")
    _drop_table("permission_model")
    _drop_table("permission_action_resource_scope")
    _drop_table("permission_action")
    _drop_table("permission_catalog_release")
    _drop_table("authorization_model_release")
    dashboard_exists = table_exists(_DASHBOARD_TABLE)
    if dashboard_exists and index_exists(
        _DASHBOARD_TABLE,
        _DASHBOARD_TENANT_INDEX,
    ):
        op.drop_index(
            _DASHBOARD_TENANT_INDEX,
            table_name=_DASHBOARD_TABLE,
        )
    if dashboard_exists and column_exists(
        _DASHBOARD_TABLE,
        _DASHBOARD_TENANT_COLUMN,
    ):
        op.drop_column(
            _DASHBOARD_TABLE,
            _DASHBOARD_TENANT_COLUMN,
        )

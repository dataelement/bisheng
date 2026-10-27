"""F054: app / app_version / app_instance — hosted application tables (v3.0.0).

Revision ID: f054_app_runtime_tables
Revises: f049_user_user_type
Create Date: 2026-08-17

Changes (DDL-only):
  - CREATE app: the hosted-application aggregate root. ``id`` is VARCHAR(36),
    not an integer — the build-page list UNIONs it with ``flow`` and
    ``assistant`` and all three legs must share column types (design K5 ③).
    ``slug`` is unique **globally**, across tenants: it is the public entry
    segment ``/apps/{slug}`` (AC-08).
  - CREATE app_version: INSERT-only version records (RT-05 / AC-02). No
    ``tenant_id`` column on purpose — isolation is derived through ``app_id``
    (design K5 ②); ``manifest`` / ``capabilities`` / ``injections`` are JSON
    (CLOB on DM8), while ``runtime`` / ``tier_id`` stay explicit columns because
    they are filtered in SQL and ``JSON_EXTRACT`` is banned on DM8 (K4).
  - CREATE app_instance: at most one row per app (AC-24).

No ``mysql_charset`` / ``mysql_collate``: this repo runs MySQL **and** DM8 from
one revision (C2 / K4), and those kwargs emit MySQL-only DDL.

Data effect: none. Every table is new and starts empty.

Downgrade caveat — **stop and delete every hosted application first**. Dropping
these tables removes the platform's only record of which containers and host
volumes (``{data_root}/apps/*``) belong to which app; anything still running
becomes an ownerless orphan that only runtime-manager's orphan reclaim can
clean up. Tables are dropped app_instance → app_version → app (no FK
constraints exist; the order still avoids leaving child rows behind if a drop
fails midway). Idempotent on both directions: ``create_all()`` may already have
produced the tables on a fresh install.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

from bisheng.core.database.dialect_helpers import JsonType, table_exists

revision: str = "f054_app_runtime_tables"
down_revision: Union[str, Sequence[str], None] = "f049_user_user_type"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_APP = "app"
_APP_VERSION = "app_version"
_APP_INSTANCE = "app_instance"


def upgrade() -> None:
    conn = op.get_bind()

    if not table_exists(conn, _APP):
        op.create_table(
            _APP,
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("slug", sa.String(64), nullable=False, comment="Entry path segment /apps/{slug}"),
            sa.Column("name", sa.String(128), nullable=False),
            sa.Column("description", sa.String(1000), nullable=True),
            sa.Column("logo", sa.String(512), nullable=True),
            sa.Column("owner_user_id", sa.Integer, nullable=False),
            sa.Column("tenant_id", sa.Integer, nullable=False),
            sa.Column(
                "state",
                sa.String(16),
                nullable=False,
                comment="draft | online | pending_capacity | stopped | deleted",
            ),
            sa.Column("current_version_id", sa.String(36), nullable=True),
            sa.Column("pending_version_id", sa.String(36), nullable=True),
            sa.Column("create_time", sa.DateTime, nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.Column("update_time", sa.DateTime, nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.UniqueConstraint("slug", name="uk_app_slug"),
        )
        op.create_index("ix_app_owner_user_id", _APP, ["owner_user_id"])
        op.create_index("ix_app_tenant_id", _APP, ["tenant_id"])
        op.create_index("ix_app_tenant_state", _APP, ["tenant_id", "state"])

    if not table_exists(conn, _APP_VERSION):
        op.create_table(
            _APP_VERSION,
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("app_id", sa.String(36), nullable=False),
            sa.Column("version_no", sa.Integer, nullable=False),
            sa.Column("kind", sa.String(16), nullable=False, comment="initial | iteration"),
            sa.Column(
                "terminal_state",
                sa.String(16),
                nullable=True,
                comment="online | rejected | withdrawn | NULL",
            ),
            sa.Column("code_object_key", sa.String(512), nullable=False),
            sa.Column("manifest", JsonType, nullable=False),
            sa.Column("capabilities", JsonType, nullable=False),
            sa.Column("injections", JsonType, nullable=False),
            sa.Column("tier_id", sa.String(32), nullable=False),
            sa.Column("runtime", sa.String(32), nullable=False),
            sa.Column("image_ref", sa.String(256), nullable=True),
            sa.Column("submitted_at", sa.DateTime, nullable=True),
            sa.Column("create_time", sa.DateTime, nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.Column("update_time", sa.DateTime, nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.UniqueConstraint("app_id", "version_no", name="uk_app_version_no"),
        )
        op.create_index("ix_app_version_app_id", _APP_VERSION, ["app_id"])

    if not table_exists(conn, _APP_INSTANCE):
        op.create_table(
            _APP_INSTANCE,
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("app_id", sa.String(36), nullable=False),
            sa.Column("tenant_id", sa.Integer, nullable=False),
            sa.Column("version_id", sa.String(36), nullable=True),
            sa.Column(
                "phase",
                sa.String(16),
                nullable=False,
                comment="pending | building | starting | running | unhealthy | stopped | failed",
            ),
            sa.Column("health", sa.String(16), nullable=True),
            sa.Column(
                "exec_ref",
                sa.String(128),
                nullable=True,
                comment="Execution handle (compose: container name); audit/debug only",
            ),
            sa.Column("started_at", sa.DateTime, nullable=True),
            sa.Column("restart_count", sa.Integer, nullable=False, server_default=sa.text("0")),
            sa.Column("last_probe_at", sa.DateTime, nullable=True),
            sa.Column("create_time", sa.DateTime, nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.Column("update_time", sa.DateTime, nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.UniqueConstraint("app_id", name="uk_app_instance_app"),
        )
        op.create_index("ix_app_instance_tenant_id", _APP_INSTANCE, ["tenant_id"])


def downgrade() -> None:
    conn = op.get_bind()
    # See the module docstring: stop and delete every hosted application before
    # running this, or the running containers and their host volumes are orphaned.
    if table_exists(conn, _APP_INSTANCE):
        op.drop_table(_APP_INSTANCE)
    if table_exists(conn, _APP_VERSION):
        op.drop_table(_APP_VERSION)
    if table_exists(conn, _APP):
        op.drop_table(_APP)

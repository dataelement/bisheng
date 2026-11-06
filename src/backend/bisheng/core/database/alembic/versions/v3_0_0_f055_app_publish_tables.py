"""F055: app_deployment / resource_tier — publish pipeline tables (v3.0.0).

Revision ID: f055_app_publish_tables
Revises: f054_app_runtime_tables
Create Date: 2026-08-17

Changes (DDL-only):
  - CREATE app_deployment: one publish attempt. ``stage`` / ``status`` are
    explicit VARCHAR columns because the CLI polls on them and the in-flight
    gate filters ``(app_id, status)`` — ``JSON_EXTRACT`` is banned on DM8
    (C2 / design K6). ``manifest`` / ``failure`` / ``scan_result`` are JSON
    (CLOB on DM8) and are only inspected in Python. ``app_id`` is nullable for
    exactly one instant: a first publish creates the row, then calls F054
    ``create_draft`` and back-fills it (design D2).
  - CREATE resource_tier: the platform's selectable tiers. **No tenant_id** —
    tiers are platform-level and shared across tenants (AC-44). CPU is stored
    as integer millicores, memory as integer MB: floats round-trip through DM8
    and JSON into values like 0.30000000000000004 (design D11).

No ``mysql_charset`` / ``mysql_collate``: this repo runs MySQL **and** DM8 from
one revision (C2), and those kwargs emit MySQL-only DDL.

No seed rows here. The three factory tiers are seeded by
``ResourceTierService.seed_resource_tiers()`` from ``init_default_data``,
idempotent by ``code``, so a super admin's retuned specs survive an upgrade
(AC-44 / AC-19). Migrations in this repo are DDL-only (see the alembic
AGENTS.md).

Data effect: none. Both tables are new and start empty.

Downgrade caveat — **confirm no hosted application is running first**.
``app_version.tier_id`` references ``resource_tier.code``, so dropping the tier
table leaves every existing version with a dangling reference: the app keeps
running, but re-enabling it can no longer resolve a spec (design D11 "only
disable, never delete"). Tables are dropped app_deployment → resource_tier
(no FK constraints exist; the order still avoids leaving the attempt log
behind if a drop fails midway). Idempotent in both directions:
``create_all()`` may already have produced the tables on a fresh install.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

from bisheng.core.database.dialect_helpers import JsonType, table_exists

revision: str = "f055_app_publish_tables"
down_revision: Union[str, Sequence[str], None] = "f054_app_runtime_tables"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_APP_DEPLOYMENT = "app_deployment"
_RESOURCE_TIER = "resource_tier"


def upgrade() -> None:
    conn = op.get_bind()

    if not table_exists(conn, _RESOURCE_TIER):
        op.create_table(
            _RESOURCE_TIER,
            sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
            sa.Column("code", sa.String(32), nullable=False, comment="light | standard | performance"),
            sa.Column("name", sa.String(64), nullable=False),
            sa.Column("cpu_millicores", sa.Integer, nullable=False, comment="CPU limit in millicores"),
            sa.Column("memory_mb", sa.Integer, nullable=False, comment="Memory limit in MB"),
            sa.Column("description", sa.String(500), nullable=True),
            sa.Column(
                "enabled",
                sa.Boolean,
                nullable=False,
                server_default=sa.text("1"),
                comment="False blocks new selections only",
            ),
            sa.Column("sort_order", sa.Integer, nullable=False, server_default=sa.text("0")),
            sa.Column("create_time", sa.DateTime, nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.Column("update_time", sa.DateTime, nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.UniqueConstraint("code", name="uk_resource_tier_code"),
        )

    if not table_exists(conn, _APP_DEPLOYMENT):
        op.create_table(
            _APP_DEPLOYMENT,
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("tenant_id", sa.Integer, nullable=False),
            sa.Column("app_id", sa.String(36), nullable=True, comment="NULL only until create_draft back-fills it"),
            sa.Column("owner_user_id", sa.Integer, nullable=False, comment="Natural person; the approval applicant"),
            sa.Column("submitted_by_user_id", sa.Integer, nullable=False, comment="Acting service-account user"),
            sa.Column("version_id", sa.String(36), nullable=True),
            sa.Column("approval_instance_id", sa.Integer, nullable=True),
            sa.Column(
                "stage",
                sa.String(32),
                nullable=False,
                comment=(
                    "received | secret_scan | precheck_manifest | precheck_build | precheck_probe | "
                    "version_recorded | approval_created | approved | publishing | online | pending_online"
                ),
            ),
            sa.Column(
                "status",
                sa.String(16),
                nullable=False,
                comment="running | waiting_approval | succeeded | failed",
            ),
            sa.Column("code_object_key", sa.String(512), nullable=True),
            sa.Column("manifest", JsonType, nullable=True),
            sa.Column("tier_code", sa.String(32), nullable=True),
            sa.Column("failure", JsonType, nullable=True, comment="{stage, code, message, details, hints}"),
            sa.Column("scan_result", JsonType, nullable=True, comment="Secret-scan report; never carries values"),
            sa.Column("create_time", sa.DateTime, nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.Column("update_time", sa.DateTime, nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        )
        op.create_index("ix_app_deployment_tenant_id", _APP_DEPLOYMENT, ["tenant_id"])
        op.create_index("ix_app_deployment_app_status", _APP_DEPLOYMENT, ["app_id", "status"])
        op.create_index("ix_app_deployment_tenant_create", _APP_DEPLOYMENT, ["tenant_id", "create_time"])


def downgrade() -> None:
    conn = op.get_bind()
    # See the module docstring: confirm no hosted application is running before
    # running this, or every app_version.tier_id becomes a dangling reference.
    if table_exists(conn, _APP_DEPLOYMENT):
        op.drop_table(_APP_DEPLOYMENT)
    if table_exists(conn, _RESOURCE_TIER):
        op.drop_table(_RESOURCE_TIER)

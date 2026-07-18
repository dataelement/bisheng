"""Add portal course, video, progress, and media cleanup tables.

Revision ID: f062_add_portal_course_tables
Revises: f060_department_multiple_spaces
Create Date: 2026-07-18
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from bisheng.core.database.dialect_helpers import (
    UPDATE_TIME_SERVER_DEFAULT,
    LargeText,
    index_exists,
    table_exists,
)

revision: str = "f062_add_portal_course_tables"
down_revision: str | Sequence[str] | None = "f060_department_multiple_spaces"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _timestamps() -> tuple[sa.Column, sa.Column]:
    return (
        sa.Column(
            "create_time",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "update_time",
            sa.DateTime(),
            nullable=False,
            server_default=UPDATE_TIME_SERVER_DEFAULT,
        ),
    )


def _create_index(name: str, table: str, columns: list[str]) -> None:
    connection = op.get_bind()
    if not index_exists(connection, table, name):
        op.create_index(name, table, columns, unique=False)


def upgrade() -> None:
    connection = op.get_bind()

    if not table_exists(connection, "portal_course"):
        op.create_table(
            "portal_course",
            sa.Column("id", sa.CHAR(32), primary_key=True, nullable=False),
            sa.Column("tenant_id", sa.Integer(), nullable=False),
            sa.Column("name", sa.String(200), nullable=False),
            sa.Column("instructor", sa.String(100), nullable=False, server_default=sa.text("''")),
            sa.Column("organization", sa.String(200), nullable=False, server_default=sa.text("''")),
            sa.Column("description", sa.Text(), nullable=False),
            sa.Column("tags_json", LargeText(), nullable=False),
            sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("0")),
            sa.Column("show_on_home", sa.Boolean(), nullable=False, server_default=sa.text("0")),
            sa.Column("sort_order", sa.Integer(), nullable=False, server_default=sa.text("0")),
            sa.Column("create_user", sa.Integer(), nullable=False),
            *_timestamps(),
            mysql_charset="utf8mb4",
            mysql_collate="utf8mb4_unicode_ci",
        )

    if not table_exists(connection, "portal_course_video"):
        op.create_table(
            "portal_course_video",
            sa.Column("id", sa.CHAR(32), primary_key=True, nullable=False),
            sa.Column("tenant_id", sa.Integer(), nullable=False),
            sa.Column("course_id", sa.CHAR(32), nullable=False),
            sa.Column("title", sa.String(200), nullable=False),
            sa.Column("source_type", sa.String(16), nullable=False),
            sa.Column("object_name", sa.String(512), nullable=True),
            sa.Column("source_url", sa.String(2048), nullable=True),
            sa.Column("original_filename", sa.String(255), nullable=True),
            sa.Column("duration_seconds", sa.Integer(), nullable=False),
            sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("0")),
            sa.Column("sort_order", sa.Integer(), nullable=False, server_default=sa.text("0")),
            *_timestamps(),
            sa.ForeignKeyConstraint(
                ["course_id"],
                ["portal_course.id"],
                name="fk_portal_video_course",
            ),
            mysql_charset="utf8mb4",
            mysql_collate="utf8mb4_unicode_ci",
        )

    if not table_exists(connection, "portal_course_video_progress"):
        op.create_table(
            "portal_course_video_progress",
            sa.Column("id", sa.CHAR(32), primary_key=True, nullable=False),
            sa.Column("tenant_id", sa.Integer(), nullable=False),
            sa.Column("user_id", sa.Integer(), nullable=False),
            sa.Column("video_id", sa.CHAR(32), nullable=False),
            sa.Column("progress_seconds", sa.Integer(), nullable=False, server_default=sa.text("0")),
            sa.Column("completed", sa.Boolean(), nullable=False, server_default=sa.text("0")),
            sa.Column("completed_at", sa.DateTime(), nullable=True),
            *_timestamps(),
            sa.ForeignKeyConstraint(
                ["video_id"],
                ["portal_course_video.id"],
                name="fk_portal_progress_video",
            ),
            sa.UniqueConstraint(
                "tenant_id",
                "user_id",
                "video_id",
                name="uk_portal_progress_tenant_user_video",
            ),
            mysql_charset="utf8mb4",
            mysql_collate="utf8mb4_unicode_ci",
        )

    if not table_exists(connection, "portal_course_media_cleanup"):
        op.create_table(
            "portal_course_media_cleanup",
            sa.Column("id", sa.CHAR(32), primary_key=True, nullable=False),
            sa.Column("tenant_id", sa.Integer(), nullable=False),
            sa.Column("object_name", sa.String(512), nullable=False),
            sa.Column("reason", sa.String(32), nullable=False),
            sa.Column("status", sa.String(16), nullable=False, server_default=sa.text("'pending'")),
            sa.Column("not_before", sa.DateTime(), nullable=False),
            sa.Column("lease_until", sa.DateTime(), nullable=True),
            sa.Column("attempt_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
            sa.Column("last_error", sa.String(1000), nullable=True),
            *_timestamps(),
            mysql_charset="utf8mb4",
            mysql_collate="utf8mb4_unicode_ci",
        )

    _create_index(
        "ix_portal_course_tenant_enabled_home_order",
        "portal_course",
        ["tenant_id", "enabled", "show_on_home", "sort_order"],
    )
    _create_index(
        "ix_portal_course_tenant_order",
        "portal_course",
        ["tenant_id", "sort_order"],
    )
    _create_index(
        "ix_portal_video_tenant_course_enabled_order",
        "portal_course_video",
        ["tenant_id", "course_id", "enabled", "sort_order"],
    )
    _create_index(
        "ix_portal_video_tenant_object",
        "portal_course_video",
        ["tenant_id", "object_name"],
    )
    _create_index(
        "ix_portal_progress_tenant_video",
        "portal_course_video_progress",
        ["tenant_id", "video_id"],
    )
    _create_index(
        "ix_portal_cleanup_status_not_before",
        "portal_course_media_cleanup",
        ["status", "not_before"],
    )
    _create_index(
        "ix_portal_cleanup_status_lease",
        "portal_course_media_cleanup",
        ["status", "lease_until"],
    )
    _create_index(
        "ix_portal_cleanup_tenant_object_status",
        "portal_course_media_cleanup",
        ["tenant_id", "object_name", "status"],
    )


def downgrade() -> None:
    connection = op.get_bind()
    if table_exists(connection, "portal_course_video_progress"):
        op.drop_table("portal_course_video_progress")
    if table_exists(connection, "portal_course_media_cleanup"):
        op.drop_table("portal_course_media_cleanup")
    if table_exists(connection, "portal_course_video"):
        op.drop_table("portal_course_video")
    if table_exists(connection, "portal_course"):
        op.drop_table("portal_course")

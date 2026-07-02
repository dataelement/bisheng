"""F050: normalize tag-library tags and knowledge↔library M:N links.

Revision ID: f050_tag_library_m2m
Revises: f049_add_qa_expert_major
Create Date: 2026-07-01
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

from bisheng.core.database.dialect_helpers import table_exists

revision: str = "f050_tag_library_m2m"
down_revision: Union[str, Sequence[str], None] = "f049_add_qa_expert_major"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_LINK_TABLE = "knowledge_tag_library_link"
_LIBRARY_TABLE = "knowledge_space_tag_library"
_TAG_TABLE = "tag"
_KNOWLEDGE_TABLE = "knowledge"


def _json_list(raw) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, list):
        return [str(item).strip() for item in raw if str(item).strip()]
    if isinstance(raw, str):
        text = raw.strip()
        if not text:
            return []
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            return []
        if isinstance(parsed, list):
            return [str(item).strip() for item in parsed if str(item).strip()]
    return []


def upgrade() -> None:
    conn = op.get_bind()

    if not table_exists(conn, _LINK_TABLE):
        op.create_table(
            _LINK_TABLE,
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column(
                "tenant_id",
                sa.Integer(),
                nullable=False,
                server_default=sa.text("1"),
                comment="Tenant ID",
            ),
            sa.Column(
                "knowledge_id",
                sa.Integer(),
                nullable=False,
                comment="Knowledge space ID",
            ),
            sa.Column(
                "tag_library_id",
                sa.Integer(),
                nullable=False,
                comment="Tag library ID",
            ),
            sa.Column(
                "sort_order",
                sa.Integer(),
                nullable=False,
                server_default=sa.text("0"),
                comment="Merge order for auto-tag candidates",
            ),
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
                server_default=sa.text("CURRENT_TIMESTAMP"),
            ),
            sa.UniqueConstraint(
                "knowledge_id",
                "tag_library_id",
                name="uk_knowledge_tag_library",
            ),
            mysql_charset="utf8mb4",
            mysql_collate="utf8mb4_unicode_ci",
        )
        op.create_index(
            "ix_knowledge_tag_library_link_knowledge_id",
            _LINK_TABLE,
            ["knowledge_id"],
        )
        op.create_index(
            "ix_knowledge_tag_library_link_tag_library_id",
            _LINK_TABLE,
            ["tag_library_id"],
        )
        op.create_index(
            "ix_knowledge_tag_library_link_tenant_id",
            _LINK_TABLE,
            ["tenant_id"],
        )

    if table_exists(conn, _LIBRARY_TABLE) and table_exists(conn, _TAG_TABLE):
        libraries = (
            conn.execute(
                sa.text(
                    f"""
                SELECT id, tenant_id, user_id, tags, ai_tags
                FROM {_LIBRARY_TABLE}
                """
                )
            )
            .mappings()
            .all()
        )
        for library in libraries:
            library_id = library["id"]
            tenant_id = library.get("tenant_id") or 1
            user_id = library.get("user_id") or 0
            for name in _json_list(library.get("tags")):
                exists = conn.execute(
                    sa.text(
                        f"""
                        SELECT id FROM {_TAG_TABLE}
                        WHERE business_type = 'tag_library'
                          AND business_id = :business_id
                          AND name = :name
                          AND resource_type = 'manual_tag'
                        LIMIT 1
                        """
                    ),
                    {"business_id": str(library_id), "name": name},
                ).first()
                if exists:
                    continue
                conn.execute(
                    sa.text(
                        f"""
                        INSERT INTO {_TAG_TABLE}
                            (name, business_type, business_id, user_id, tenant_id, resource_type)
                        VALUES
                            (:name, 'tag_library', :business_id, :user_id, :tenant_id, 'manual_tag')
                        """
                    ),
                    {
                        "name": name,
                        "business_id": str(library_id),
                        "user_id": user_id,
                        "tenant_id": tenant_id,
                    },
                )
            for name in _json_list(library.get("ai_tags")):
                exists = conn.execute(
                    sa.text(
                        f"""
                        SELECT id FROM {_TAG_TABLE}
                        WHERE business_type = 'tag_library'
                          AND business_id = :business_id
                          AND name = :name
                          AND resource_type = 'ai_auto_tag'
                        LIMIT 1
                        """
                    ),
                    {"business_id": str(library_id), "name": name},
                ).first()
                if exists:
                    continue
                conn.execute(
                    sa.text(
                        f"""
                        INSERT INTO {_TAG_TABLE}
                            (name, business_type, business_id, user_id, tenant_id, resource_type)
                        VALUES
                            (:name, 'tag_library', :business_id, :user_id, :tenant_id, 'ai_auto_tag')
                        """
                    ),
                    {
                        "name": name,
                        "business_id": str(library_id),
                        "user_id": user_id,
                        "tenant_id": tenant_id,
                    },
                )

    if table_exists(conn, _KNOWLEDGE_TABLE) and table_exists(conn, _LINK_TABLE):
        rows = (
            conn.execute(
                sa.text(
                    f"""
                SELECT id, tenant_id, auto_tag_library_id
                FROM {_KNOWLEDGE_TABLE}
                WHERE auto_tag_library_id IS NOT NULL
                """
                )
            )
            .mappings()
            .all()
        )
        for row in rows:
            exists = conn.execute(
                sa.text(
                    f"""
                    SELECT id FROM {_LINK_TABLE}
                    WHERE knowledge_id = :knowledge_id
                      AND tag_library_id = :tag_library_id
                    LIMIT 1
                    """
                ),
                {
                    "knowledge_id": row["id"],
                    "tag_library_id": row["auto_tag_library_id"],
                },
            ).first()
            if exists:
                continue
            conn.execute(
                sa.text(
                    f"""
                    INSERT INTO {_LINK_TABLE}
                        (tenant_id, knowledge_id, tag_library_id, sort_order)
                    VALUES
                        (:tenant_id, :knowledge_id, :tag_library_id, 0)
                    """
                ),
                {
                    "tenant_id": row.get("tenant_id") or 1,
                    "knowledge_id": row["id"],
                    "tag_library_id": row["auto_tag_library_id"],
                },
            )

    if table_exists(conn, _LIBRARY_TABLE) and table_exists(conn, _LINK_TABLE):
        private_rows = (
            conn.execute(
                sa.text(
                    f"""
                SELECT id, tenant_id, owner_knowledge_id
                FROM {_LIBRARY_TABLE}
                WHERE owner_knowledge_id IS NOT NULL
                """
                )
            )
            .mappings()
            .all()
        )
        for row in private_rows:
            exists = conn.execute(
                sa.text(
                    f"""
                    SELECT id FROM {_LINK_TABLE}
                    WHERE knowledge_id = :knowledge_id
                      AND tag_library_id = :tag_library_id
                    LIMIT 1
                    """
                ),
                {
                    "knowledge_id": row["owner_knowledge_id"],
                    "tag_library_id": row["id"],
                },
            ).first()
            if exists:
                continue
            conn.execute(
                sa.text(
                    f"""
                    INSERT INTO {_LINK_TABLE}
                        (tenant_id, knowledge_id, tag_library_id, sort_order)
                    VALUES
                        (:tenant_id, :knowledge_id, :tag_library_id, 0)
                    """
                ),
                {
                    "tenant_id": row.get("tenant_id") or 1,
                    "knowledge_id": row["owner_knowledge_id"],
                    "tag_library_id": row["id"],
                },
            )


def downgrade() -> None:
    conn = op.get_bind()
    if table_exists(conn, _TAG_TABLE):
        conn.execute(sa.text(f"DELETE FROM {_TAG_TABLE} WHERE business_type = 'tag_library'"))
    if table_exists(conn, _LINK_TABLE):
        op.drop_index("ix_knowledge_tag_library_link_tenant_id", table_name=_LINK_TABLE)
        op.drop_index(
            "ix_knowledge_tag_library_link_tag_library_id",
            table_name=_LINK_TABLE,
        )
        op.drop_index(
            "ix_knowledge_tag_library_link_knowledge_id",
            table_name=_LINK_TABLE,
        )
        op.drop_table(_LINK_TABLE)

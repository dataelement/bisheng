"""Persist knowledge-file similarity candidates.

Revision ID: f053_knowledge_file_similarity_candidates
Revises: f052_favorite_space_unique_per_user
Create Date: 2026-07-03
"""

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

from bisheng.core.database.dialect_helpers import index_exists, table_exists

revision: str = "f053_knowledge_file_similarity_candidates"
down_revision: Union[str, Sequence[str], None] = "f052_favorite_space_unique_per_user"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLE = "knowledge_file_similarity_candidate"


def _create_index_if_missing(name: str, columns: list[str], *, unique: bool = False) -> None:
    conn = op.get_bind()
    if not index_exists(conn, _TABLE, name):
        op.create_index(name, _TABLE, columns, unique=unique)


def upgrade() -> None:
    conn = op.get_bind()
    if not table_exists(conn, _TABLE):
        op.create_table(
            _TABLE,
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column(
                "tenant_id",
                sa.Integer(),
                nullable=False,
                server_default=sa.text("1"),
                comment="Tenant ID",
            ),
            sa.Column("knowledge_id", sa.Integer(), nullable=False, comment="Owning knowledge space ID"),
            sa.Column("source_file_id", sa.Integer(), nullable=False, comment="Source knowledgefile.id"),
            sa.Column(
                "candidate_file_id",
                sa.Integer(),
                nullable=False,
                comment="Candidate primary knowledgefile.id at scan time",
            ),
            sa.Column(
                "candidate_document_id",
                sa.Integer(),
                nullable=False,
                comment="Candidate knowledge_document.id",
            ),
            sa.Column("similarity", sa.Float(), nullable=False, comment="Raw SimHash similarity"),
            sa.Column("refined_similarity", sa.Float(), nullable=True, comment="Optional TF-IDF cosine"),
            sa.Column(
                "sort_order",
                sa.Integer(),
                nullable=False,
                server_default=sa.text("0"),
                comment="Order within one source file's candidate list",
            ),
            sa.Column("create_time", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.Column(
                "update_time",
                sa.DateTime(),
                nullable=False,
                server_default=sa.text("CURRENT_TIMESTAMP"),
                onupdate=sa.text("CURRENT_TIMESTAMP"),
            ),
            sa.UniqueConstraint(
                "source_file_id",
                "candidate_document_id",
                name="uk_kf_similarity_source_document",
            ),
            mysql_charset="utf8mb4",
            mysql_collate="utf8mb4_unicode_ci",
        )

    _create_index_if_missing("ix_kf_similarity_tenant_id", ["tenant_id"])
    _create_index_if_missing("ix_kf_similarity_knowledge_source", ["knowledge_id", "source_file_id"])
    _create_index_if_missing("ix_kf_similarity_source_file_id", ["source_file_id"])
    _create_index_if_missing("ix_kf_similarity_candidate_file_id", ["candidate_file_id"])
    _create_index_if_missing("ix_kf_similarity_candidate_document_id", ["candidate_document_id"])


def downgrade() -> None:
    conn = op.get_bind()
    if not table_exists(conn, _TABLE):
        return
    for index_name in [
        "ix_kf_similarity_candidate_document_id",
        "ix_kf_similarity_candidate_file_id",
        "ix_kf_similarity_source_file_id",
        "ix_kf_similarity_knowledge_source",
        "ix_kf_similarity_tenant_id",
    ]:
        if index_exists(conn, _TABLE, index_name):
            op.drop_index(index_name, table_name=_TABLE)
    op.drop_table(_TABLE)

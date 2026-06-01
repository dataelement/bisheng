"""F042: add channel membership relation and grant source fields.

Revision ID: f042_channel_membership_relation_source
Revises: f041_revoke_business_resource_share
Create Date: 2026-05-28
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

from bisheng.core.database.dialect_helpers import column_exists, index_exists

revision: str = 'f042_channel_membership_relation_source'
down_revision: Union[str, Sequence[str], None] = 'f041_revoke_business_resource_share'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _add_column_if_missing(column: sa.Column) -> None:
    conn = op.get_bind()
    if not column_exists(conn, 'space_channel_member', column.name):
        op.add_column('space_channel_member', column)


def _create_index_if_missing(name: str, columns: list[str]) -> None:
    conn = op.get_bind()
    if not index_exists(conn, 'space_channel_member', name):
        op.create_index(name, 'space_channel_member', columns)


def upgrade() -> None:
    _add_column_if_missing(sa.Column('relation', sa.String(length=32), nullable=True))
    _add_column_if_missing(sa.Column('grant_subject_type', sa.String(length=32), nullable=True))
    _add_column_if_missing(sa.Column('grant_subject_id', sa.Integer(), nullable=True))
    _add_column_if_missing(sa.Column('grant_relation', sa.String(length=32), nullable=True))
    _add_column_if_missing(
        sa.Column(
            'grant_include_children',
            sa.Boolean(),
            nullable=False,
            server_default=sa.text('0'),
        ),
    )
    _add_column_if_missing(sa.Column('grant_model_id', sa.String(length=64), nullable=True))
    _add_column_if_missing(sa.Column('grant_binding_key', sa.String(length=255), nullable=True))

    _create_index_if_missing('idx_scm_relation', ['relation'])
    _create_index_if_missing('idx_scm_grant_subject_type', ['grant_subject_type'])
    _create_index_if_missing('idx_scm_grant_subject_id', ['grant_subject_id'])
    _create_index_if_missing('idx_scm_grant_binding_key', ['grant_binding_key'])


def downgrade() -> None:
    conn = op.get_bind()
    for idx_name in (
        'idx_scm_grant_binding_key',
        'idx_scm_grant_subject_id',
        'idx_scm_grant_subject_type',
        'idx_scm_relation',
    ):
        if index_exists(conn, 'space_channel_member', idx_name):
            op.drop_index(idx_name, table_name='space_channel_member')

    for column_name in (
        'grant_binding_key',
        'grant_model_id',
        'grant_include_children',
        'grant_relation',
        'grant_subject_id',
        'grant_subject_type',
        'relation',
    ):
        if column_exists(conn, 'space_channel_member', column_name):
            op.drop_column('space_channel_member', column_name)

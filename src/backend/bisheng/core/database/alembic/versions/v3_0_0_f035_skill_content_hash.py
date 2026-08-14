"""F035: add linsight_skill.content_hash (skill bundles move to object storage).

Bundle bytes used to live on the node's local filesystem, which made a
multi-node deployment inconsistent by construction: the API replica that
received an upload was the only host holding the files, while any Linsight
worker on another host read an empty directory and silently skipped the skill.
Bundles now live in object storage and ``content_hash`` is the pointer's version
component — the object key embeds it, so a key that exists always holds exactly
the bytes the row describes.

The hash is computed over the bundle's *file mapping*
(``skill_store.bundle_content_hash``), not over the packed archive: zip bytes
carry timestamps and entry ordering, so hashing them would make every process
disagree about whether an unchanged bundle had changed.

Empty string means "not migrated yet" and is left for the operational
backfill (``scripts/migrate_skills_to_object_storage.py``) to resolve — this
revision issues DDL only.

Revision ID: f035_skill_content_hash
Revises: f048_visible_source_projection
Create Date: 2026-08-14
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

from bisheng.core.database.alembic_helpers.online import column_exists

revision: str = "f035_skill_content_hash"
down_revision: Union[str, Sequence[str], None] = "f048_visible_source_projection"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLE = "linsight_skill"
_COLUMN = "content_hash"


def upgrade() -> None:
    if not column_exists(_TABLE, _COLUMN):
        op.add_column(
            _TABLE,
            sa.Column(
                _COLUMN,
                sa.String(length=64),
                nullable=False,
                server_default=sa.text("''"),
                comment="sha256 of the bundle's file mapping; '' = not yet on object storage",
            ),
        )


def downgrade() -> None:
    if column_exists(_TABLE, _COLUMN):
        op.drop_column(_TABLE, _COLUMN)

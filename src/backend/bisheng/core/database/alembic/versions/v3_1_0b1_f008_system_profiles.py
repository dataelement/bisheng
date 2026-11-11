"""F008 official profile provenance; system initialization has no fake user."""

import sqlalchemy as sa
from alembic import op

from bisheng.core.database.alembic_helpers.online import column_exists

revision = "v310b1_f008_system_profiles"
down_revision = "v310b1_f004_workflow_soft_delete"
branch_labels = None
depends_on = None


def upgrade():
    for name, kind in (
        ("origin", sa.String(16)),
        ("release_version", sa.String(64)),
        ("catalog_digest", sa.String(64)),
    ):
        if not column_exists("runtime_profile", name):
            op.add_column(
                "runtime_profile",
                sa.Column(name, kind, nullable=name != "origin", server_default="user" if name == "origin" else None),
            )
    op.alter_column("runtime_profile", "created_by", existing_type=sa.Integer(), nullable=True)


def downgrade():
    table = sa.table("runtime_profile", sa.column("origin"), sa.column("created_by"))
    if op.get_bind().execute(sa.select(sa.func.count()).select_from(table).where(table.c.origin == "system")).scalar():
        raise RuntimeError(
            "Cannot downgrade system profiles into fake-user records; retain data and use a compatible image"
        )
    op.alter_column("runtime_profile", "created_by", existing_type=sa.Integer(), nullable=False)
    for name in ("catalog_digest", "release_version", "origin"):
        if column_exists("runtime_profile", name):
            op.drop_column("runtime_profile", name)

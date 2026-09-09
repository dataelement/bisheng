"""Add the monotonic DSH profile version to the existing user table.

No data migration is performed; the database applies the column server default.
The additive column is retained on rollback so delayed profile messages cannot
become newer than a reset version counter. Disable DSH before application rollback.
"""

import sqlalchemy as sa
from alembic import op

from bisheng.core.database.alembic_helpers.online import column_exists

revision = "f062_profile_version"
down_revision = "update_time_default_align"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if not column_exists("user", "dsh_profile_version"):
        op.add_column(
            "user",
            sa.Column(
                "dsh_profile_version",
                sa.BigInteger(),
                nullable=False,
                server_default=sa.text("0"),
            ),
        )


def downgrade() -> None:
    # Intentionally retain the counter and its default for safe application rollback.
    # Re-upgrade tolerates this additive column; no seat or audit history is deleted.
    return

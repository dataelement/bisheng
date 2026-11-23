"""Record when a desktop refresh token was first consumed.

The column stays nullable so rows written before this revision keep the strict
replay rule. Downgrade retains it: a rolled-back application must still upgrade
cleanly, and the timestamp is replay evidence rather than disposable state.

Both release lines share this revision id. A database that applied it on
bisheng-work-110 can move to 130 without Alembic reporting a missing revision.
"""

import sqlalchemy as sa
from alembic import op

from bisheng.core.database.alembic_helpers.online import column_exists, table_exists

revision = "work110_dsh_refresh_used_at"
down_revision = "work110_dsh_local_sessions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Fresh installs create the column from the model. Upgrades add it here.
    if table_exists("dsh_refresh_token") and not column_exists("dsh_refresh_token", "used_at"):
        op.add_column("dsh_refresh_token", sa.Column("used_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    # Keep the additive timestamp so rollback and a later upgrade stay compatible.
    return

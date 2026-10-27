"""Default third-party desktop installs to disabled for new tenant policies.

Existing tenant choices remain unchanged; only the database column defaults move.
"""

import sqlalchemy as sa
from alembic import op

from bisheng.core.database.alembic_helpers.online import table_exists

revision = "f065_dsh_install_policy_default_off"
down_revision = "linsight_skill_default_checked"
branch_labels = None
depends_on = None

_TABLE = "dsh_market_install_policy"
_COLUMNS = ("allow_third_party_plugins", "allow_third_party_workbenches")


def _set_default(value):
    if not table_exists(_TABLE):
        return
    for column in _COLUMNS:
        op.alter_column(
            _TABLE,
            column,
            existing_type=sa.Boolean(),
            existing_nullable=False,
            server_default=value,
        )


def upgrade():
    _set_default(sa.false())


def downgrade():
    _set_default(sa.true())

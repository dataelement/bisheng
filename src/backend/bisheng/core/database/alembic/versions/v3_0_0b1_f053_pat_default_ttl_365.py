"""Align the personal-token lifetime default with the 365-day product policy.

Existing tenant choices and issued-token expiry dates are intentionally preserved.
"""

import sqlalchemy as sa
from alembic import op

from bisheng.core.database.alembic_helpers.online import column_exists

revision = "f053_pat_default_ttl_365"
down_revision = "f058_widen_projection_idempotency_key"
branch_labels = None
depends_on = None


def _set_default(days: int) -> None:
    if column_exists("open_api_tenant_setting", "pat_ttl_days"):
        op.alter_column(
            "open_api_tenant_setting",
            "pat_ttl_days",
            existing_type=sa.Integer(),
            existing_nullable=False,
            server_default=sa.text(str(days)),
        )


def upgrade() -> None:
    _set_default(365)


def downgrade() -> None:
    _set_default(30)

"""F044: record when a model's status was last checked.

The model list shows "available / abnormal" but nothing said how old that
verdict is -- and it can be weeks old, since the status is only probed when the
provider config is saved. Manual verification (F044) needs to surface a
timestamp next to the status.

A dedicated column rather than reusing ``update_time``: that one is refreshed by
any column change, so renaming a model would make its status look freshly
verified. Null means the model has never been probed.

Revision ID: f044_llm_status_time
Revises: f048_merge_f046_f047_heads
Create Date: 2026-07-27
"""

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

from bisheng.core.database.dialect_helpers import column_exists

revision: str = "f044_llm_status_time"
down_revision: Union[str, Sequence[str], None] = "f048_merge_f046_f047_heads"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    if not column_exists(conn, "llm_model", "status_update_time"):
        op.add_column(
            "llm_model",
            sa.Column(
                "status_update_time",
                sa.DateTime(),
                nullable=True,
                comment="Last time the model status was checked (config-time probe or manual verify)",
            ),
        )


def downgrade() -> None:
    conn = op.get_bind()
    if column_exists(conn, "llm_model", "status_update_time"):
        op.drop_column("llm_model", "status_update_time")

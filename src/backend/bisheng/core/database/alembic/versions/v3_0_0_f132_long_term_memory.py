"""Long-term memory (F132): assistant.memory_enabled switch.

The six new memory tables are standalone tables declared with ``table=True``
under ``memory/domain/models``; the online upgrade creates them through
``create_all(checkfirst=True)`` before revisions run (``src/backend/AGENTS.md``
"Schema ownership"). This revision only changes the existing ``assistant``
table. Downgrade removes the column and drops the six new tables, which hold no
migrated data.
"""

import sqlalchemy as sa
from alembic import op

from bisheng.core.database.alembic_helpers.online import column_exists, table_exists

revision = "f132_long_term_memory"
down_revision = "f114_app_authorization"
branch_labels = None
depends_on = None

_MEMORY_TABLES = (
    "memory_metric_daily",
    "memory_resident_snapshot",
    "memory_turn_record",
    "memory_user_setting",
    "memory_session_cursor",
    "memory_item",
)


def upgrade():
    if table_exists("assistant") and not column_exists("assistant", "memory_enabled"):
        op.add_column(
            "assistant",
            sa.Column("memory_enabled", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        )


def downgrade():
    if table_exists("assistant") and column_exists("assistant", "memory_enabled"):
        op.drop_column("assistant", "memory_enabled")
    for table in _MEMORY_TABLES:
        if table_exists(table):
            op.drop_table(table)

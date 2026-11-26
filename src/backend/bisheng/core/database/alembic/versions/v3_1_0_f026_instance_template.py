"""F026: the WeKnora knowledge base whose extract_config new spaces on an instance copy.

It replaces the per-tenant creation preset. NULL means the operator has not named one yet,
so creating WeKnora spaces on that instance stays unavailable.
"""

import sqlalchemy as sa
from alembic import op

from bisheng.core.database.alembic_helpers.online import column_exists

revision = "f026_instance_template"
down_revision = "f026_linsight_scope"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if not column_exists("knowledge_provider_instance", "template_kb_id"):
        op.add_column("knowledge_provider_instance", sa.Column("template_kb_id", sa.String(128), nullable=True))


def downgrade() -> None:
    if column_exists("knowledge_provider_instance", "template_kb_id"):
        op.drop_column("knowledge_provider_instance", "template_kb_id")

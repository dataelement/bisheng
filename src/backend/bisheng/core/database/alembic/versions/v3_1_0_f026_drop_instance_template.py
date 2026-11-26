"""F026: extract template is chosen at space creation; instance no longer stores template_kb_id."""

from alembic import op

from bisheng.core.database.alembic_helpers.online import column_exists

revision = "f026_drop_instance_template"
down_revision = "f026_instance_template"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if column_exists("knowledge_provider_instance", "template_kb_id"):
        op.drop_column("knowledge_provider_instance", "template_kb_id")


def downgrade() -> None:
    import sqlalchemy as sa

    if not column_exists("knowledge_provider_instance", "template_kb_id"):
        op.add_column("knowledge_provider_instance", sa.Column("template_kb_id", sa.String(128), nullable=True))

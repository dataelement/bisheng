"""F026: seal WeKnora signed-token HMAC on the provider instance (not config.yaml)."""

import sqlalchemy as sa
from alembic import op

from bisheng.core.database.alembic_helpers.online import column_exists

revision = "f026_instance_upload_secret"
down_revision = "f026_drop_instance_template"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if not column_exists("knowledge_provider_instance", "upload_credential_ref"):
        op.add_column(
            "knowledge_provider_instance",
            sa.Column("upload_credential_ref", sa.String(256), nullable=True),
        )


def downgrade() -> None:
    if column_exists("knowledge_provider_instance", "upload_credential_ref"):
        op.drop_column("knowledge_provider_instance", "upload_credential_ref")

"""F111 multimodal finetune task evidence fields; DDL only."""

import sqlalchemy as sa
from alembic import op

from bisheng.core.database.alembic_helpers.online import column_exists
from bisheng.core.database.dialect_helpers import JsonType

revision = "f111_multimodal_finetune"
down_revision = "v310b1_f016_dsh_call_pricing"
branch_labels = None
depends_on = None


_COLUMNS = (
    ("data_type", sa.String(length=32)),
    ("stage", sa.String(length=32)),
    ("capability_snapshot", JsonType),
    ("dataset_report", JsonType),
    ("artifact_report", JsonType),
    ("inference_validation", JsonType),
)


def upgrade():
    for name, datatype in _COLUMNS:
        if not column_exists("finetune", name):
            op.add_column("finetune", sa.Column(name, datatype, nullable=True))


def downgrade():
    for name, _ in reversed(_COLUMNS):
        if column_exists("finetune", name):
            op.drop_column("finetune", name)

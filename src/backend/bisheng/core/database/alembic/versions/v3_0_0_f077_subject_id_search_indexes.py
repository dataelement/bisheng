"""Add leading external-ID indexes without changing existing identity data."""

from alembic import op

from bisheng.core.database.alembic_helpers.online import index_exists

revision = "f077_subject_id_search_indexes"
down_revision = "merge_release_information_heads"
branch_labels = None
depends_on = None

_INDEXES = (
    ("user", "ix_user_external_id_search"),
    ("department", "ix_department_external_id_search"),
)


def upgrade() -> None:
    for table, name in _INDEXES:
        if not index_exists(table, name):
            op.create_index(name, table, ["external_id"], unique=False)


def downgrade() -> None:
    for table, name in reversed(_INDEXES):
        if index_exists(table, name):
            op.drop_index(name, table_name=table)

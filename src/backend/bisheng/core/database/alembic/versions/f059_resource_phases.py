"""Keep sequential fixed-name workload evidence as separate immutable rows.

Revision ID: f059_resource_phases
Revises: f059_merge_release_heads

Downgrade prerequisite: operators must verify there are no duplicate historical
(operation_id, kind, name) tuples. The DDL fails rather than deleting evidence.
"""

from alembic import op

from bisheng.core.database.alembic_helpers.online import table_exists
from bisheng.core.database.dialect_helpers import constraint_exists

revision = "f059_resource_phases"
down_revision = "f059_merge_release_heads"
branch_labels = None
depends_on = None


def _exists():
    connection = op.get_bind()
    return any(
        constraint_exists(connection, "runtime_execution_resource", name)
        for name in ("uq_rt_resource_intent", "UQ_RT_RESOURCE_INTENT")
    )


def upgrade():
    if table_exists("runtime_execution_resource") and _exists():
        op.drop_constraint("uq_rt_resource_intent", "runtime_execution_resource", type_="unique")


def downgrade():
    if table_exists("runtime_execution_resource") and not _exists():
        op.create_unique_constraint(
            "uq_rt_resource_intent", "runtime_execution_resource", ["operation_id", "kind", "name"]
        )

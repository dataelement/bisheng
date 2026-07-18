"""F029: backfill local department external_id from dept_id.

Revision ID: f029_backfill_local_department_external_id
Revises: f028_workbench_menu_keys_backfill
Create Date: 2026-04-25

Local departments use ``dept_id`` as their stable business identifier in the
management UI and org-sync reconciliation. Older rows left ``external_id``
NULL, so upstream sync items with the same ID were treated as new departments
instead of adopting/updating the local row.
"""

from typing import Sequence, Union

from alembic import op

revision: str = 'f029_backfill_local_department_external_id'
down_revision: Union[str, Sequence[str], None] = 'f028_workbench_menu_keys_backfill'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        UPDATE department
        SET external_id = dept_id
        WHERE source = 'local'
          AND (external_id IS NULL OR external_id = '')
    """)


def downgrade() -> None:
    """No-op: clearing external_id would re-break org-sync matching."""
    pass

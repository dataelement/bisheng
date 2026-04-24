"""F028: merge alembic heads + backfill workbench HOME/APPS menu keys.

Revision ID: f028_workbench_menu_keys_backfill
Revises: f026_chatmessage_files_longtext, f026_department_admin_grant, f027_role_scope_nullsafe_unique
Create Date: 2026-04-24

Roles that already have WEB_MENU ``workstation`` but no explicit ``home`` / ``apps``
rows get both keys so admins can revoke them per-role without ambiguous legacy state.
"""

from typing import Sequence, Union

from alembic import op

revision: str = 'f028_workbench_menu_keys_backfill'
down_revision: Union[str, Sequence[str], None] = (
    'f026_chatmessage_files_longtext',
    'f026_department_admin_grant',
    'f027_role_scope_nullsafe_unique',
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

WEB_MENU = 99


def upgrade() -> None:
    for third in ('home', 'apps'):
        op.execute(f"""
            INSERT INTO roleaccess (role_id, third_id, type, tenant_id)
            SELECT DISTINCT r.role_id, '{third}', {WEB_MENU}, r.tenant_id
            FROM roleaccess r
            WHERE r.type = {WEB_MENU}
              AND r.third_id = 'workstation'
              AND NOT EXISTS (
                SELECT 1 FROM roleaccess x
                WHERE x.role_id = r.role_id
                  AND x.type = {WEB_MENU}
                  AND x.third_id = '{third}'
                  AND (x.tenant_id <=> r.tenant_id)
              )
        """)


def downgrade() -> None:
    """No-op: cannot distinguish backfilled rows from manually granted ones."""
    pass

"""F028: merge alembic heads + backfill workbench HOME/APPS menu keys.

Revision ID: f028_workbench_menu_keys_backfill
Revises: f026_chatmessage_files_longtext, f026_department_admin_grant, f027_role_scope_nullsafe_unique
Create Date: 2026-04-24

Roles that already have WEB_MENU ``workstation`` but no explicit ``home`` / ``apps``
rows get both keys so admins can revoke them per-role without ambiguous legacy state.
"""

from typing import Sequence, Union

import sqlalchemy as sa
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
    """Backfill WEB_MENU rows via SQLAlchemy expression language.

    MySQL ``<=>`` NULL-safe equality is replaced with explicit
    ``a = b OR (a IS NULL AND b IS NULL)`` for DM8 compatibility.
    """
    conn = op.get_bind()
    ra = sa.Table('roleaccess', sa.MetaData(), autoload_with=conn)
    existing_alias = sa.orm.aliased(ra)

    for third in ('home', 'apps'):
        select_new = (
            sa.select(
                sa.distinct(ra.c.role_id).label('role_id'),
                sa.literal(third).label('third_id'),
                sa.literal(WEB_MENU).label('type'),
                ra.c.tenant_id.label('tenant_id'),
            )
            .where(
                ra.c.type == WEB_MENU,
                ra.c.third_id == 'workstation',
                ~sa.exists().where(
                    existing_alias.c.role_id == ra.c.role_id,
                    existing_alias.c.type == WEB_MENU,
                    existing_alias.c.third_id == third,
                    sa.or_(
                        existing_alias.c.tenant_id == ra.c.tenant_id,
                        sa.and_(
                            existing_alias.c.tenant_id.is_(None),
                            ra.c.tenant_id.is_(None),
                        ),
                    ),
                ),
            )
        )
        conn.execute(sa.insert(ra).from_select(
            ['role_id', 'third_id', 'type', 'tenant_id'], select_new
        ))


def downgrade() -> None:
    """No-op: cannot distinguish backfilled rows from manually granted ones."""
    pass

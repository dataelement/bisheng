"""F032: backfill WEB_MENU ``subscription`` for roles with ``workstation``.

Revision ID: f032_workbench_subscription_web_menu_backfill
Revises: f031_startup_hotfix_fields
Create Date: 2026-04-27

Aligns historical roles with F028-style workbench keys: if a role already has
the parent ``workstation`` WEB_MENU row but no ``subscription`` child, insert
one so 首页/应用/订阅/知识空间四项与新建角色默认一致。
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'f032_workbench_subscription_web_menu_backfill'
down_revision: Union[str, Sequence[str], None] = 'f031_startup_hotfix_fields'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

WEB_MENU = 99


def upgrade() -> None:
    """Backfill ``subscription`` WEB_MENU rows via SQLAlchemy expression language.

    MySQL ``<=>`` NULL-safe equality is replaced with explicit
    ``a = b OR (a IS NULL AND b IS NULL)`` for DM8 compatibility.
    """
    conn = op.get_bind()
    ra = sa.Table('roleaccess', sa.MetaData(), autoload_with=conn)
    existing_alias = sa.orm.aliased(ra)

    select_new = (
        sa.select(
            sa.distinct(ra.c.role_id).label('role_id'),
            sa.literal('subscription').label('third_id'),
            sa.literal(WEB_MENU).label('type'),
            ra.c.tenant_id.label('tenant_id'),
        )
        .where(
            ra.c.type == WEB_MENU,
            ra.c.third_id == 'workstation',
            ~sa.exists().where(
                existing_alias.c.role_id == ra.c.role_id,
                existing_alias.c.type == WEB_MENU,
                existing_alias.c.third_id == 'subscription',
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

"""F032: backfill WEB_MENU ``subscription`` for roles with ``workstation``.

Revision ID: f032_workbench_subscription_web_menu_backfill
Revises: f031_startup_hotfix_fields
Create Date: 2026-04-27

Aligns historical roles with F028-style workbench keys: if a role already has
the parent ``workstation`` WEB_MENU row but no ``subscription`` child, insert
one so 首页/应用/订阅/知识空间四项与新建角色默认一致。
"""

from typing import Sequence, Union

from alembic import op

revision: str = 'f032_workbench_subscription_web_menu_backfill'
down_revision: Union[str, Sequence[str], None] = 'f031_startup_hotfix_fields'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

WEB_MENU = 99


def upgrade() -> None:
    op.execute(f"""
        INSERT INTO roleaccess (role_id, third_id, type, tenant_id)
        SELECT DISTINCT r.role_id, 'subscription', {WEB_MENU}, r.tenant_id
        FROM roleaccess r
        WHERE r.type = {WEB_MENU}
          AND r.third_id = 'workstation'
          AND NOT EXISTS (
            SELECT 1 FROM roleaccess x
            WHERE x.role_id = r.role_id
              AND x.type = {WEB_MENU}
              AND x.third_id = 'subscription'
              AND (x.tenant_id <=> r.tenant_id)
          )
    """)


def downgrade() -> None:
    """No-op: cannot distinguish backfilled rows from manually granted ones."""
    pass

"""PRD 3.3.3: Backfill WEB_MENU `create_knowledge` for roles that already have `knowledge`.

Revision ID: f011_backfill_create_knowledge_web_menu
Revises: f010_user_name_nonunique
Create Date: 2026-04-18

Existing deployments may have `knowledge` in roleaccess (type=WEB_MENU) without the new
sub-toggle `create_knowledge`. After upgrade, POST /knowledge/create checks this flag;
backfill preserves prior behavior (users who could open the 知识 menu can still create
unless an admin later revokes `create_knowledge`).
"""

from typing import Sequence, Union

from alembic import op

revision: str = 'f011_backfill_create_knowledge_web_menu'
down_revision: Union[str, Sequence[str], None] = 'f010_user_name_nonunique'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

WEB_MENU = 99


def upgrade() -> None:
    op.execute(f"""
        INSERT INTO roleaccess (role_id, third_id, type, tenant_id)
        SELECT DISTINCT r.role_id, 'create_knowledge', {WEB_MENU}, r.tenant_id
        FROM roleaccess r
        WHERE r.type = {WEB_MENU}
          AND r.third_id = 'knowledge'
          AND NOT EXISTS (
            SELECT 1 FROM roleaccess x
            WHERE x.role_id = r.role_id
              AND x.type = {WEB_MENU}
              AND x.third_id = 'create_knowledge'
              AND (x.tenant_id <=> r.tenant_id)
          )
    """)


def downgrade() -> None:
    """No-op: cannot safely remove only rows inserted by upgrade without a marker column."""
    pass

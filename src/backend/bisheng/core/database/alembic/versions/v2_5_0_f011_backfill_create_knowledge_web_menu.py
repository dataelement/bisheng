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

import sqlalchemy as sa
from alembic import op

revision: str = 'f011_backfill_create_knowledge_web_menu'
down_revision: Union[str, Sequence[str], None] = 'f010_user_name_nonunique'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

WEB_MENU = 99


def upgrade() -> None:
    """Insert WEB_MENU ``create_knowledge`` rows for roles that already have ``knowledge``.

    Implemented via SQLAlchemy expression language so it works on both MySQL
    and DM8 — MySQL's ``<=>`` NULL-safe equality operator is not portable.
    """
    conn = op.get_bind()
    ra = sa.Table('roleaccess', sa.MetaData(), autoload_with=conn)

    existing_alias = sa.orm.aliased(ra)
    select_new = (
        sa.select(
            sa.distinct(ra.c.role_id).label('role_id'),
            sa.literal('create_knowledge').label('third_id'),
            sa.literal(WEB_MENU).label('type'),
            ra.c.tenant_id.label('tenant_id'),
        )
        .where(
            ra.c.type == WEB_MENU,
            ra.c.third_id == 'knowledge',
            ~sa.exists().where(
                existing_alias.c.role_id == ra.c.role_id,
                existing_alias.c.type == WEB_MENU,
                existing_alias.c.third_id == 'create_knowledge',
                # NULL-safe match: equal when both NULL or both equal.
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
    """No-op: cannot safely remove only rows inserted by upgrade without a marker column."""
    pass

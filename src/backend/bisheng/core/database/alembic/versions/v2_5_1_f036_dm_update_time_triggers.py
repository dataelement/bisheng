"""F036: create BEFORE UPDATE triggers for update_time on DaMeng.

DaMeng does not support MySQL's ON UPDATE CURRENT_TIMESTAMP column option.
This migration creates equivalent BEFORE UPDATE triggers on every table
that has an update_time column, but ONLY when the active dialect is DaMeng.
MySQL and SQLite skip this migration entirely.

Revision ID: f036_dm_update_time_triggers
Revises: f035_user_tenant_subtree_cleanup
Create Date: 2026-04-28
"""

from typing import Sequence, Union

from alembic import op

revision: str = 'f036_dm_update_time_triggers'
down_revision: Union[str, Sequence[str], None] = 'f035_user_tenant_subtree_cleanup'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    if conn.dialect.name != 'dm':
        return

    import logging
    from sqlalchemy import inspect

    log = logging.getLogger(__name__)
    insp = inspect(conn)

    for table in insp.get_table_names():
        try:
            col_names = [c['name'].lower() for c in insp.get_columns(table)]
        except Exception:
            continue

        if 'update_time' not in col_names:
            continue

        trigger_name = f'trg_{table}_update_time'
        # Use exec_driver_sql to prevent SQLAlchemy from parsing :new as a bind parameter
        trigger_ddl = (
            f'CREATE OR REPLACE TRIGGER "{trigger_name}" '
            f'BEFORE UPDATE ON "{table}" '
            f'FOR EACH ROW '
            f'BEGIN '
            f'  :new.update_time := CURRENT_TIMESTAMP; '
            f'END'
        )
        try:
            conn.exec_driver_sql(trigger_ddl)
        except Exception as exc:
            log.warning(f'[f036] Could not create trigger {trigger_name}: {exc}')


def downgrade() -> None:
    conn = op.get_bind()
    if conn.dialect.name != 'dm':
        return

    from sqlalchemy import inspect

    insp = inspect(conn)

    for table in insp.get_table_names():
        try:
            col_names = [c['name'].lower() for c in insp.get_columns(table)]
        except Exception:
            continue

        if 'update_time' not in col_names:
            continue

        trigger_name = f'trg_{table}_update_time'
        try:
            conn.exec_driver_sql(f'DROP TRIGGER IF EXISTS "{trigger_name}"')
        except Exception:
            pass

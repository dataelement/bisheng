"""F035: cleanup UserTenant residue rows that lie outside the tenant subtree.

Revision ID: f035_user_tenant_subtree_cleanup
Revises: f034_tenant_system_model_config
Create Date: 2026-05-07

Why:
  F024 changed the tenant user list/count source to "primary department in
  tenant subtree" (UserDepartmentDao.aget_users_by_tenant_subtree). The
  legacy v2.5.0 ``aadd_users`` write path left ``UserTenant`` rows with
  ``is_active=1`` whose user's primary department is *no longer* (or
  never was) inside the corresponding tenant subtree — these rows are the
  "phantom members" that surfaced as non-zero ``user_count`` whose detail
  dialog rendered an empty list.

  F035 is the data-fix companion to the F024-phase-2 service switchover
  (``acount_users_by_tenant_subtree``). After this migration:
    * Counts shown by tenant list / detail / quota usage match the dialog
      list 1:1.
    * The ``uk_user_active(user_id, is_active)`` invariant is preserved —
      we only flip is_active=1 → NULL, never delete rows, so a user's
      historical leaf trail stays intact.

What:
  Find every ``user_tenant`` row with ``is_active=1`` whose ``user_id``
  has no primary ``user_department`` row pointing into the tenant's
  subtree (resolved via ``tenant.root_dept_id`` → ``department.path``,
  with the legacy flat-model fallback ``department.tenant_id``). For
  each such id, set ``is_active=NULL``.

Rollback:
  Downgrade is a no-op. Restoring the previous "phantom" is_active=1
  rows would re-introduce the user_count/list mismatch and would also
  violate ``uk_user_active`` if the user has since been promoted to a
  different leaf, so reversing this fix is not safe in general.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'f035_user_tenant_subtree_cleanup'
down_revision: Union[str, Sequence[str], None] = 'f034_tenant_system_model_config'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _select_residue_sql(dialect: str) -> str:
    """Build the dialect-specific SELECT for residue ``user_tenant.id`` rows.

    The path-prefix match needs string concat: MySQL uses ``CONCAT(...)``,
    SQLite uses the ``||`` operator. Postgres also supports ``||`` so it
    falls under the SQLite branch here; production is MySQL.
    """
    if dialect == 'mysql':
        prefix_expr = "CONCAT(rd.path, '%')"
    else:
        prefix_expr = "rd.path || '%'"
    return f"""
        SELECT ut.id
        FROM user_tenant ut
        WHERE ut.is_active = 1
          AND NOT EXISTS (
            SELECT 1
            FROM user_department ud
            JOIN department d ON d.id = ud.department_id
            JOIN tenant t ON t.id = ut.tenant_id
            LEFT JOIN department rd ON rd.id = t.root_dept_id
            WHERE ud.user_id = ut.user_id
              AND ud.is_primary = 1
              AND (
                (rd.path IS NOT NULL AND d.path LIKE {prefix_expr})
                OR (rd.id IS NULL AND d.tenant_id = ut.tenant_id)
              )
          )
    """


def upgrade() -> None:
    bind = op.get_bind()
    dialect = bind.dialect.name
    if dialect not in ('mysql', 'sqlite', 'postgresql'):
        # Unknown backend — skip rather than risk a partial flip. Production
        # is MySQL; sqlite branch covers test harnesses.
        return

    rows = bind.execute(sa.text(_select_residue_sql(dialect))).fetchall()
    residue_ids = [row[0] for row in rows]
    if not residue_ids:
        return

    # Chunk the IN-list to keep individual statements within MySQL's
    # max_allowed_packet — 1000 ids per UPDATE is comfortably small.
    chunk_size = 1000
    for i in range(0, len(residue_ids), chunk_size):
        chunk = residue_ids[i:i + chunk_size]
        bind.execute(
            sa.text(
                'UPDATE user_tenant SET is_active = NULL '
                'WHERE id IN :ids'
            ).bindparams(sa.bindparam('ids', expanding=True)),
            {'ids': chunk},
        )


def downgrade() -> None:
    """No-op: see module docstring (Rollback)."""
    return

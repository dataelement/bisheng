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


def upgrade() -> None:
    """Flip residue ``user_tenant.is_active`` to NULL using SQLAlchemy expression.

    Implemented in the expression language so the same code path runs on
    MySQL and DM8 (and SQLite/Postgres in tests). String concatenation for
    the path-prefix match uses ``sa.func.concat`` which compiles to the
    native ``CONCAT(...)`` on MySQL/DM8 and to ``||`` elsewhere.
    """
    bind = op.get_bind()
    dialect = bind.dialect.name
    if dialect not in ('mysql', 'dm', 'sqlite', 'postgresql'):
        # Unknown backend — skip rather than risk a partial flip.
        return

    ut_tbl = sa.Table('user_tenant', sa.MetaData(), autoload_with=bind)
    ud_tbl = sa.Table('user_department', sa.MetaData(), autoload_with=bind)
    dept_tbl = sa.Table('department', sa.MetaData(), autoload_with=bind)
    tenant_tbl = sa.Table('tenant', sa.MetaData(), autoload_with=bind)
    rd_alias = sa.orm.aliased(dept_tbl, name='rd')

    primary_path_match = sa.and_(
        rd_alias.c.path.isnot(None),
        dept_tbl.c.path.like(sa.func.concat(rd_alias.c.path, '%')),
    )
    legacy_flat_match = sa.and_(
        rd_alias.c.id.is_(None),
        dept_tbl.c.tenant_id == ut_tbl.c.tenant_id,
    )

    exists_primary = (
        sa.select(sa.literal(1))
        .select_from(
            ud_tbl
            .join(dept_tbl, dept_tbl.c.id == ud_tbl.c.department_id)
            .join(tenant_tbl, tenant_tbl.c.id == ut_tbl.c.tenant_id)
            .outerjoin(rd_alias, rd_alias.c.id == tenant_tbl.c.root_dept_id)
        )
        .where(
            ud_tbl.c.user_id == ut_tbl.c.user_id,
            ud_tbl.c.is_primary == 1,
            sa.or_(primary_path_match, legacy_flat_match),
        )
        .exists()
    )

    residue_rows = bind.execute(
        sa.select(ut_tbl.c.id)
        .where(
            ut_tbl.c.is_active == 1,
            ~exists_primary,
        )
    ).fetchall()
    residue_ids = [row[0] for row in residue_rows]
    if not residue_ids:
        return

    # Chunk the IN-list — 1000 ids per UPDATE is comfortably small for
    # MySQL's max_allowed_packet and DM8's parameter limits.
    chunk_size = 1000
    for i in range(0, len(residue_ids), chunk_size):
        chunk = residue_ids[i:i + chunk_size]
        bind.execute(
            sa.update(ut_tbl)
            .where(ut_tbl.c.id.in_(chunk))
            .values(is_active=None)
        )


def downgrade() -> None:
    """No-op: see module docstring (Rollback)."""
    return

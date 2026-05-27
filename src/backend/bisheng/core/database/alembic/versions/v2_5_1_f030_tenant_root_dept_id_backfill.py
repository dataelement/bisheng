"""F030: backfill tenant.root_dept_id for already-mounted Child Tenants.

Revision ID: f030_tenant_root_dept_id_backfill
Revises: f029_llm_shared_backfill
Create Date: 2026-04-25

Why:
  Until F030, ``TenantMountService.mount_child`` only wrote one side of
  the dept↔tenant link — ``department.mounted_tenant_id`` got populated,
  but ``tenant.root_dept_id`` was left NULL on every mount. The detail
  endpoint ``GET /api/v1/tenants/{id}`` exposes ``root_dept_id`` and the
  frontend (``TenantUserDialog`` member-picker scope, F019 admin-scope
  switcher labels) relies on the column being filled. Without backfill,
  every Child mounted before this revision keeps falling back to the
  full org tree in the picker — silently bypassing the write-side
  subtree guard for member adds.

What:
  One UPDATE join — for any tenant row whose ``root_dept_id`` is NULL,
  derive the dept id from ``department.mounted_tenant_id`` (the side
  mount_child *did* write). Restricted to active mount points
  (``is_tenant_root = 1``) so we never link to a stale dept.

Failure tolerance:
  Pure DDL-free DML; runs inside the alembic transaction. If an existing
  row already has ``root_dept_id`` set (e.g. backfilled manually) the
  WHERE clause skips it — safe to rerun.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = 'f030_tenant_root_dept_id_backfill'
# Doubles as a merge revision: when this lands there are two open heads
# (``f029_llm_shared_backfill`` and ``f029_backfill_local_department_external_id``)
# and a single new head must be produced. Listing both as parents collapses the
# graph without needing a dedicated empty merge migration.
down_revision: Union[str, Sequence[str], None] = (
    'f029_llm_shared_backfill',
    'f029_backfill_local_department_external_id',
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Backfill ``tenant.root_dept_id`` from ``department.mounted_tenant_id``.

    Uses SQLAlchemy expression language so the dialect-specific multi-table
    ``UPDATE...JOIN`` syntax is avoided — MySQL accepts it, DM8 does not.
    """
    conn = op.get_bind()
    tenant_tbl = sa.Table('tenant', sa.MetaData(), autoload_with=conn)
    dept_tbl = sa.Table('department', sa.MetaData(), autoload_with=conn)

    # Per active mount: pick department.id where mounted_tenant_id=tenant.id.
    rows = conn.execute(
        sa.select(
            tenant_tbl.c.id.label('tenant_id'),
            dept_tbl.c.id.label('dept_id'),
        )
        .where(
            tenant_tbl.c.root_dept_id.is_(None),
            dept_tbl.c.mounted_tenant_id == tenant_tbl.c.id,
            dept_tbl.c.is_tenant_root == 1,
        )
    ).fetchall()

    updated = 0
    for row in rows:
        result = conn.execute(
            sa.update(tenant_tbl)
            .where(
                tenant_tbl.c.id == row.tenant_id,
                tenant_tbl.c.root_dept_id.is_(None),
            )
            .values(root_dept_id=row.dept_id)
        )
        updated += result.rowcount or 0
    print(f'[F030] backfilled tenant.root_dept_id on {updated} rows')


def downgrade() -> None:
    """No-op — the backfilled values are recoverable from department.mounted_tenant_id
    if rollback is ever needed; rather than NULL them out here we leave them in
    place (harmless on downgrade)."""
    pass

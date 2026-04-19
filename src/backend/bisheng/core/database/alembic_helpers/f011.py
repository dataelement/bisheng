"""F011 tenant-tree-model migration business helpers (v2.5.1).

Exposed:
  - ``ensure_root_tenant_shape(conn)`` — upsert tenant id=1 into the v2.5.1
    tree shape (``parent_tenant_id=NULL``, ``share_default_to_children=1``).
  - ``backfill_is_active(conn)`` — write ``is_active=1`` where the v2.5.0
    UserTenant record was the user's default active leaf.
  - ``deduplicate_multi_active_user_tenants(conn)`` — if multiple rows for
    the same user carry ``is_active=1`` after backfill (production drift
    under F001 multi-to-multi), demote all but the one with the latest
    ``last_access_time`` to ``is_active=NULL`` so ``uk_user_active`` can be
    added without conflict.

Each helper takes a live SQLAlchemy ``Connection`` so it is reusable from
both the Alembic revision and the pytest suite.
"""

from sqlalchemy import text
from sqlalchemy.engine import Connection


def ensure_root_tenant_shape(conn: Connection) -> None:
    """Make sure the Root tenant (id=1) is present and has tree fields set.

    F001 migration already inserts ``(id=1, tenant_code='default', ...)``,
    so the common branch is an UPDATE. The INSERT branch only fires on a
    tenant table that was somehow left empty.
    """
    row = conn.execute(text('SELECT id FROM tenant WHERE id = 1')).first()
    if row is None:
        conn.execute(text(
            "INSERT INTO tenant (id, tenant_code, tenant_name, status, "
            "parent_tenant_id, share_default_to_children) "
            "VALUES (1, 'default', 'Default', 'active', NULL, 1)"
        ))
        return
    conn.execute(text(
        'UPDATE tenant SET parent_tenant_id = NULL, '
        'share_default_to_children = 1 WHERE id = 1'
    ))


def backfill_is_active(conn: Connection) -> None:
    """Set ``is_active = 1`` where (status='active' AND is_default=1).

    All other rows stay NULL, matching the unique-leaf semantic: one
    active row per user, everything else is history.
    """
    conn.execute(text(
        "UPDATE user_tenant SET is_active = 1 "
        "WHERE status = 'active' AND is_default = 1"
    ))


def deduplicate_multi_active_user_tenants(conn: Connection) -> None:
    """Demote stale actives so each user has at most one ``is_active=1`` row.

    Strategy: for any user with >1 is_active=1 row, keep the row with the
    latest ``last_access_time`` (NULL treated as oldest) and demote the
    rest to NULL. This is idempotent — running twice is a no-op.

    MySQL 8.0 and SQLite both honour the correlated subqueries below.
    """
    # Step 1: compute, per user, the (max) last_access_time across their
    # currently-active rows. Any row whose last_access_time is strictly
    # less than the max gets demoted.
    conn.execute(text("""
        UPDATE user_tenant
        SET is_active = NULL
        WHERE is_active = 1
          AND user_id IN (
              SELECT user_id FROM user_tenant
              WHERE is_active = 1
              GROUP BY user_id
              HAVING COUNT(*) > 1
          )
          AND (
              last_access_time IS NULL
              OR last_access_time < (
                  SELECT MAX(last_access_time)
                  FROM user_tenant ut2
                  WHERE ut2.user_id = user_tenant.user_id
                    AND ut2.is_active = 1
              )
          )
    """))
    # Step 2: if several rows share the same max last_access_time (or all
    # NULL), keep the one with the smallest id and demote the rest.
    conn.execute(text("""
        UPDATE user_tenant
        SET is_active = NULL
        WHERE is_active = 1
          AND id NOT IN (
              SELECT keeper_id FROM (
                  SELECT MIN(id) AS keeper_id
                  FROM user_tenant
                  WHERE is_active = 1
                  GROUP BY user_id
              ) AS keepers
          )
    """))

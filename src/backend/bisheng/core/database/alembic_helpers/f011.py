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
    latest ``last_access_time`` (NULL treated as oldest; tie-break on
    lowest id) and demote the rest to NULL. Idempotent — running twice
    is a no-op.

    Implementation note (2026-04-19): the previous SQL-only form used
    ``UPDATE ... WHERE user_id IN (SELECT ... FROM user_tenant ...)``
    which MySQL 8 rejects with 1093 "You can't specify target table for
    update in FROM clause" (even when the inner select returns no rows —
    the parser rejects it). Rewriting as multi-statement with derived
    tables is possible but noisy; we resolve the keepers in Python
    instead since this migration runs once on a bounded table.
    """
    # Step 1: find users with multiple active rows.
    dup_user_ids = [
        row[0] for row in conn.execute(text(
            'SELECT user_id FROM user_tenant '
            'WHERE is_active = 1 '
            'GROUP BY user_id HAVING COUNT(*) > 1'
        )).all()
    ]
    if not dup_user_ids:
        return

    # Step 2: for each such user, rank active rows and pick the keeper.
    for uid in dup_user_ids:
        rows = conn.execute(
            text(
                'SELECT id, last_access_time FROM user_tenant '
                'WHERE user_id = :uid AND is_active = 1'
            ),
            {'uid': uid},
        ).all()
        if len(rows) <= 1:
            continue

        # Prefer rows with non-NULL last_access_time; for those, keeper is
        # the one with the latest timestamp, tie-break on lowest id. If
        # every row has NULL, keeper is the lowest id.
        # NOTE: ``last_access_time`` comes back as ``datetime`` under
        # pymysql/aiomysql and as an ISO-8601 string under SQLite. Both
        # orderings are consistent within their type, so we sort twice
        # (once by ts descending, once by id ascending for ties) rather
        # than doing numeric conversion that differs per driver.
        ts_rows = [r for r in rows if r[1] is not None]
        if ts_rows:
            ts_rows.sort(key=lambda r: (r[1], -r[0]), reverse=True)
            keeper_id = ts_rows[0][0]
        else:
            keeper_id = min(r[0] for r in rows)
        demote_ids = [r[0] for r in rows if r[0] != keeper_id]
        if not demote_ids:
            continue

        # Use a parameterised IN list. Build an explicit tuple for
        # drivers (pymysql) that require a value per placeholder.
        placeholders = ', '.join(f':id{i}' for i in range(len(demote_ids)))
        params = {f'id{i}': did for i, did in enumerate(demote_ids)}
        conn.execute(
            text(
                f'UPDATE user_tenant SET is_active = NULL '
                f'WHERE id IN ({placeholders})'
            ),
            params,
        )

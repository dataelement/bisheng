"""F020: llm_server UNIQUE(name) -> UNIQUE(tenant_id, name).

Revision ID: f020_llm_tenant
Revises: f015_reconcile_log_fields, f017_llm_token_log
Create Date: 2026-04-21

Change:
  - llm_server: drop global ``UNIQUE(name)`` index, replace with composite
    ``UNIQUE(tenant_id, name)`` named ``uk_llm_server_tenant_name``.

Why:
  v2.5.0/F001 added ``tenant_id`` to llm_server (server_default=1) but
  kept the v2.4 UNIQUE(name) inherited from the ORM. Under the Tenant-
  tree model (v2.5.1 F020) different Children can independently register
  services with the same display name (``Azure-GPT-4``); the composite
  unique key enforces per-tenant uniqueness instead.

  llm_model's ``UNIQUE(server_id, model_name)`` already implies per-
  tenant uniqueness (server is tenant-bound), so no change there.

Pre-check:
  A malformed dataset with duplicate ``(tenant_id, name)`` pairs would
  cause ``CREATE UNIQUE INDEX`` to fail with a hard-to-read MySQL error
  mid-migration. We scan for duplicates first and abort with a human-
  readable RuntimeError listing the conflicts so a DBA can manually
  rename (e.g. suffix ``-dup-{id}``) and rerun.

Merge revision:
  Two heads exist at merge time — ``f015_reconcile_log_fields`` (F015
  reconcile chain) and ``f017_llm_token_log`` (F017 shared-storage
  chain) — both descending from ``f014_sso_sync_fields``. This
  revision joins them while carrying the real schema change; a
  separate no-op merge revision would be equivalent but adds an empty
  step operators have to apply.
"""

from typing import List, Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'f020_llm_tenant'
down_revision: Union[str, Sequence[str], None] = (
    'f015_reconcile_log_fields',
    'f017_llm_token_log',
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_OLD_UNIQUE_INDEX_NAME = 'name'   # SQLAlchemy default when unique=True is on the column
_NEW_UNIQUE_INDEX_NAME = 'uk_llm_server_tenant_name'
_TABLE = 'llm_server'


def _find_duplicates(conn) -> List[sa.engine.Row]:
    """Return rows violating the (tenant_id, name) uniqueness invariant.

    Separated out so tests can patch a connection whose ``execute``
    returns a canned fetchall.
    """
    result = conn.execute(sa.text(
        'SELECT tenant_id, name, COUNT(*) AS cnt '
        f'FROM {_TABLE} '
        'GROUP BY tenant_id, name '
        'HAVING cnt > 1'
    ))
    return result.fetchall()


def _index_exists(conn, index_name: str) -> bool:
    result = conn.execute(sa.text(
        'SELECT COUNT(*) FROM information_schema.STATISTICS '
        'WHERE TABLE_SCHEMA = DATABASE() '
        '  AND TABLE_NAME = :t AND INDEX_NAME = :i'
    ), {'t': _TABLE, 'i': index_name})
    return result.scalar() > 0


def upgrade() -> None:
    conn = op.get_bind()

    conflicts = _find_duplicates(conn)
    if conflicts:
        lines = [
            f'  tenant_id={row.tenant_id!r}, name={row.name!r}, count={row.cnt}'
            for row in conflicts
        ]
        raise RuntimeError(
            'llm_server has duplicate (tenant_id, name) pairs — cannot '
            'create composite UNIQUE index. Please deduplicate manually '
            '(e.g. suffix ``-dup-{id}``) and rerun `alembic upgrade head`.\n'
            + '\n'.join(lines)
        )

    # Drop the old global UNIQUE(name). The index name SQLAlchemy gives a
    # ``Field(name, unique=True)`` column is the column name itself on
    # MySQL. Be defensive: only drop if present, so a DB that never had
    # the legacy index (fresh install at v2.5.1) upgrades cleanly.
    if _index_exists(conn, _OLD_UNIQUE_INDEX_NAME):
        op.drop_index(_OLD_UNIQUE_INDEX_NAME, table_name=_TABLE)

    if not _index_exists(conn, _NEW_UNIQUE_INDEX_NAME):
        op.create_index(
            _NEW_UNIQUE_INDEX_NAME,
            _TABLE,
            ['tenant_id', 'name'],
            unique=True,
        )


def downgrade() -> None:
    conn = op.get_bind()

    if _index_exists(conn, _NEW_UNIQUE_INDEX_NAME):
        op.drop_index(_NEW_UNIQUE_INDEX_NAME, table_name=_TABLE)

    # Recreate the old global UNIQUE(name) — only safe if no two tenants
    # share the same llm_server name. If they do, the downgrade caller
    # must dedupe first; we do not silently rename rows.
    if not _index_exists(conn, _OLD_UNIQUE_INDEX_NAME):
        op.create_index(
            _OLD_UNIQUE_INDEX_NAME,
            _TABLE,
            ['name'],
            unique=True,
        )

"""F040: force knowledge_llm.auto_tag_enabled to false on upgrade.

The tenant-level auto-tag switch (`KnowledgeLLMConfig.auto_tag_enabled`)
historically had no UI; pre-existing tenant config rows may carry it as
true from earlier internal builds. We want the released behaviour to be
"opt-in only": after upgrade, every tenant's knowledge_llm row has
auto_tag_enabled=false so admins must explicitly turn it on.

Per-space `knowledge.auto_tag_enabled` is left alone — those are user
preferences, and they stay dormant until the tenant flips the global
switch back on (the service guards on both flags).

The JSON value column is parsed and rewritten in Python so the migration
works on both MySQL and DaMeng without dialect-specific JSON SQL.

Revision ID: f040_disable_knowledge_llm_auto_tag
Revises: f039_knowledge_document_tables
Create Date: 2026-05-21
"""

import json
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

from bisheng.core.database.alembic_helpers.online import table_exists


revision: str = "f040_disable_knowledge_llm_auto_tag"
down_revision: Union[str, Sequence[str], None] = "f039_knowledge_document_tables"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_TABLE = "tenant_system_model_config"
_KEY = "knowledge_llm"


def upgrade() -> None:
    if not table_exists(_TABLE):
        return

    bind = op.get_bind()
    meta = sa.MetaData()
    tbl = sa.Table(_TABLE, meta, autoload_with=bind)

    rows = bind.execute(
        sa.select(tbl.c.id, tbl.c.value).where(tbl.c.key == _KEY)
    ).fetchall()

    for row in rows:
        row_id, raw = row[0], row[1]
        if not raw:
            continue
        try:
            payload = json.loads(raw)
        except (TypeError, ValueError):
            # Leave malformed rows alone — the service layer already
            # treats them as missing config and falls back to defaults.
            continue
        if not isinstance(payload, dict):
            continue
        if payload.get("auto_tag_enabled") is False:
            # Already off; skip the write so we don't bump update_time.
            continue
        payload["auto_tag_enabled"] = False
        bind.execute(
            sa.update(tbl)
            .where(tbl.c.id == row_id)
            .values(value=json.dumps(payload, ensure_ascii=False))
        )


def downgrade() -> None:
    # No-op: we don't know which tenants had it on before, and the
    # upgrade is intentionally one-way (opt-in only after release).
    pass

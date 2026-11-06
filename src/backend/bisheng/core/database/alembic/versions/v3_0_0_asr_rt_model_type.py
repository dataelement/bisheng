"""Mark known realtime ASR rows as asr_rt.

Revision ID: asr_rt_model_type
Revises: f077_subject_id_search_indexes, f076_session_skill_snapshot
Create Date: 2026-10-21

Rows saved as ``asr`` used to pick a realtime client from the engine name.
New processes treat Tencent, Baidu, and Volcengine ``asr`` as file recognition
and fail, so these rows must already be ``asr_rt`` before that process takes
traffic. The provider is ``llm_server.type``. Every tenant is included.

This revision also collapses the two open heads.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from bisheng.core.ai.asr.capabilities import realtime_protocol, should_promote_legacy_asr

revision: str = "asr_rt_model_type"
down_revision: str | Sequence[str] | None = (
    "f077_subject_id_search_indexes",
    "f076_session_skill_snapshot",
)
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _matching_ids(conn, model_type: str) -> tuple[sa.Table, list]:
    model = sa.Table("llm_model", sa.MetaData(), autoload_with=conn)
    server = sa.Table("llm_server", sa.MetaData(), autoload_with=conn)
    rows = conn.execute(
        sa.select(
            model.c.id,
            model.c.model_name,
            model.c.model_type,
            server.c.type.label("server_type"),
        ).select_from(model.join(server, model.c.server_id == server.c.id))
    ).fetchall()
    # Positional access: a column named ``type`` is not a reliable row attribute.
    if model_type == "asr":
        ids = [row[0] for row in rows if should_promote_legacy_asr(row[3], row[1], row[2])]
    else:
        ids = [row[0] for row in rows if row[2] == "asr_rt" and realtime_protocol(row[3], row[1]) is not None]
    return model, ids


def upgrade() -> None:
    conn = op.get_bind()
    model, ids = _matching_ids(conn, "asr")
    if ids:
        conn.execute(sa.update(model).where(model.c.id.in_(ids)).values(model_type="asr_rt"))


def downgrade() -> None:
    conn = op.get_bind()
    model, ids = _matching_ids(conn, "asr_rt")
    if ids:
        conn.execute(sa.update(model).where(model.c.id.in_(ids)).values(model_type="asr"))

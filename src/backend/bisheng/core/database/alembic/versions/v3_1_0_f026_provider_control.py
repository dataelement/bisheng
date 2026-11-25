"""F026 provider control schema boundary (whole tables belong to SQLModel).

Downgrade is intentionally fail-closed: after quiescing all writers, a DBA
must verify all control tables are empty and remove the empty schema before
crossing this boundary. Never make a destructive data-dependent decision in
an Alembic revision or roll an old application over live external bindings.
"""

from bisheng.core.database.alembic_helpers.online import table_exists

revision = "f026_provider_control"
down_revision = "v310b1_f016_dsh_call_pricing"
branch_labels = None
depends_on = None

# Dependent tables first (also the offline DBA removal order).
CONTROL_TABLES = (
    "knowledge_provider_tag_import",
    "knowledge_provider_quota",
    "knowledge_provider_operation",
    "knowledge_provider_tag_ref",
    "knowledge_provider_mapping",
    "knowledge_provider_binding",
    "knowledge_provider_generation",
    "knowledge_provider_instance",
)


def upgrade() -> None:
    # The online upgrade bootstrap creates new whole tables before revisions.
    missing = [name for name in CONTROL_TABLES if not table_exists(name)]
    if missing:
        raise RuntimeError(f"F026 model bootstrap incomplete; missing tables: {', '.join(missing)}")


def downgrade() -> None:
    if any(table_exists(name) for name in CONTROL_TABLES):
        raise RuntimeError("F026 rollback blocked: quiesce writers and perform verified empty-schema removal first")

"""Allow a zero-item retry receipt for a guarded finalize-only recovery."""

import re

from alembic import op

from bisheng.core.database.alembic_helpers.online import get_check_constraint, table_exists

revision = "f118_finalize_retry"
down_revision = "f118_processing_acceptance"
branch_labels = None
depends_on = None

TABLE = "knowledge_processing_retry_receipt"
OLD_CHECK = "expected_job_revision >= 0 AND accepted_job_revision > expected_job_revision AND item_count > 0"
NEW_CHECK = "expected_job_revision >= 0 AND accepted_job_revision > expected_job_revision AND item_count >= 0"


def _normalized(value):
    return re.sub(r'[\s()`\"]', "", value or "").casefold()


def upgrade():
    if not table_exists(TABLE):
        return
    existing = get_check_constraint(TABLE, "ck_kpr_revision")
    if existing is not None:
        definition = _normalized(existing.get("sqltext"))
        if definition == _normalized(NEW_CHECK):
            return
        if definition != _normalized(OLD_CHECK):
            raise RuntimeError("unexpected F118 retry revision CHECK definition")
        op.drop_constraint(existing["name"], TABLE, type_="check")
    op.create_check_constraint("ck_kpr_revision", TABLE, NEW_CHECK)


def downgrade():
    # Existing valid zero-item receipts must not be invalidated in place.
    raise RuntimeError("F118 rollback requires the maintenance-window consistent backup")

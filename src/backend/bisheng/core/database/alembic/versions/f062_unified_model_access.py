"""Separate model visibility from the shared personal credit allowance."""

from alembic import op

revision = "f062_unified_model_access"
down_revision = "work110_dsh_local_sessions"
branch_labels = None
depends_on = None


def upgrade():
    from bisheng.dsh.domain.models.unified_policy import (
        CreditRule,
        ModelVisibility,
        PersonalLedgerState,
        UnifiedPolicyAudit,
    )

    bind = op.get_bind()
    for model in (ModelVisibility, CreditRule, UnifiedPolicyAudit, PersonalLedgerState):
        model.__table__.create(bind, checkfirst=True)


def downgrade():
    # Operational rollback restores the paired database snapshot.
    pass

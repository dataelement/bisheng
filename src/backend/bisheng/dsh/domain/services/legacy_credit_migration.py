"""One-time, reviewable conversion of effective legacy model grants."""

from collections import defaultdict

from sqlmodel import select

from bisheng.core.context.tenant import strict_tenant_filter
from bisheng.database.models.tenant import UserTenant
from bisheng.dsh.domain.models.unified_policy import (
    CreditRule,
    ModelVisibility,
    PersonalLedgerState,
    UnifiedPolicyAudit,
)
from bisheng.dsh.domain.repositories.admin_operation import require_tenant
from bisheng.dsh.domain.repositories.subject_policy import DshSubjectPolicyRepository
from bisheng.dsh.domain.repositories.unified_policy import UnifiedPolicyRepository
from bisheng.dsh.domain.schemas.unified_policy import (
    CreditRuleValue,
    ModelVisibilityInput,
    PolicySubject,
    credits_from_tokens,
)

MIGRATION_RESOURCE = "migration:unified-credits-v1"


def migrate_legacy_credits(session, *, actor_id: int, apply: bool = False) -> dict:
    """Snapshot existing users' effective grants; retain all historical usage rows."""
    tenant = require_tenant()
    legacy = DshSubjectPolicyRepository(session)
    legacy._lock_tenant()
    with strict_tenant_filter():
        completed = session.exec(
            select(UnifiedPolicyAudit).where(UnifiedPolicyAudit.resource == MIGRATION_RESOURCE)
        ).first()
        if completed:
            return {"tenant_id": tenant, "state": "already_applied", **completed.after_values}
        if session.exec(select(ModelVisibility)).first() or session.exec(select(CreditRule)).first():
            raise ValueError("Review existing unified policies before importing legacy grants")
        users = session.exec(
            select(UserTenant.user_id)
            .where(UserTenant.is_active == 1, UserTenant.status == "active")
            .order_by(UserTenant.user_id)
        ).all()
    grants = defaultdict(list)
    allowances = {}
    epochs = {}
    for user_id in sorted(set(users)):
        policy = legacy.effective(user_id)
        if policy:
            if any(row.quota_sync_state != "READY" or row.pending_operation_id for row in policy.rows):
                raise ValueError("Complete legacy policy operations before importing credits")
            epochs[user_id] = max(row.quota_epoch for row in policy.rows)
        models = [row for row in policy.model_configs if row.monthly_token_limit > 0] if policy else []
        if models:
            allowances[user_id] = sum(row.monthly_token_limit for row in models)
            for row in models:
                grants[row.model_id].append(PolicySubject(kind="USER", id=user_id))
    # Validate the entire import before any writes. Values remain exact token amounts.
    visibility = {model: ModelVisibilityInput(version=0, subjects=subjects) for model, subjects in grants.items()}
    credits = {
        user: CreditRuleValue(version=0, monthly_credits=credits_from_tokens(limit))
        for user, limit in allowances.items()
    }
    summary = {
        "users": len(credits),
        "models": len(visibility),
        "total_credits": credits_from_tokens(sum(allowances.values())),
    }
    if apply:
        for user, epoch in epochs.items():
            session.add(PersonalLedgerState(tenant_id=tenant, user_id=user, quota_epoch=epoch))
        repo = UnifiedPolicyRepository(session)
        for model, value in sorted(visibility.items()):
            repo.save_visibility(model, actor_id, value)
        for user, value in sorted(credits.items()):
            repo.save_rule(PolicySubject(kind="USER", id=user), actor_id, value)
        repo._audit(actor_id, MIGRATION_RESOURCE, None, summary)
    return {"tenant_id": tenant, "state": "applied" if apply else "preview", **summary}

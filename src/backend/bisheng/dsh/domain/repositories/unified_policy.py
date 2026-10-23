"""Transactional visibility and credit policy storage within the current tenant."""

from decimal import Decimal

from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from bisheng.common.errcode.dsh import DshInvalidRequestError, DshOperationConflictError
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
from bisheng.dsh.domain.schemas.model_policy import DshModelPolicyState, DshPolicySnapshot
from bisheng.dsh.domain.schemas.unified_policy import (
    CreditRuleInput,
    ModelVisibilityInput,
    PolicySubject,
    credits_from_tokens,
    effective_token_limit,
)


class UnifiedPolicyRepository:
    def __init__(self, session: Session):
        self.session = session
        self.memberships = DshSubjectPolicyRepository(session)

    def _validate_subject(self, subject: PolicySubject):
        if subject.kind in {"DEPARTMENT", "ROLE"}:
            self.memberships._validate_subject(subject.kind, subject.id)
            return
        with strict_tenant_filter():
            member = self.session.exec(
                select(UserTenant).where(
                    UserTenant.user_id == subject.id, UserTenant.is_active == 1, UserTenant.status == "active"
                )
            ).first()
        if member is None:
            raise DshInvalidRequestError()

    @staticmethod
    def visibility_payload(row: ModelVisibility | None) -> dict:
        return {
            "version": row.version if row else 0,
            "everyone": row.everyone if row else False,
            "credit_multiplier": format(Decimal(row.credit_rate if row else 100) / 100, "f"),
            "subjects": row.subjects if row else [],
        }

    @staticmethod
    def rule_payload(row: CreditRule) -> dict:
        return {
            "subject_type": row.subject_type,
            "subject_id": row.subject_id,
            "version": row.version,
            "enabled": row.enabled,
            "monthly_credits": credits_from_tokens(row.monthly_token_limit),
        }

    def visibility(self, model_id: int) -> dict:
        require_tenant()
        with strict_tenant_filter():
            row = self.session.exec(select(ModelVisibility).where(ModelVisibility.model_id == model_id)).one_or_none()
        payload = self.visibility_payload(row)
        from bisheng.user.domain.models.user import User

        user_ids = [item["id"] for item in payload["subjects"] if item["kind"] == "USER"]
        labels = []
        for offset in range(0, len(user_ids), 500):
            with strict_tenant_filter():
                users = self.session.exec(select(User).where(User.user_id.in_(user_ids[offset : offset + 500]))).all()
            labels.extend({"value": user.user_id, "label": user.user_name} for user in users)
        return {**payload, "users": labels}

    def rules(self) -> list[dict]:
        require_tenant()
        with strict_tenant_filter():
            rows = self.session.exec(select(CreditRule).order_by(CreditRule.subject_type, CreditRule.subject_id)).all()
        inventory = self.subject_options()
        names = {(item["kind"], item["id"]): item["name"] for item in inventory}
        from bisheng.user.domain.models.user import User

        user_ids = [row.subject_id for row in rows if row.subject_type == "USER"]
        for offset in range(0, len(user_ids), 500):
            with strict_tenant_filter():
                users = self.session.exec(select(User).where(User.user_id.in_(user_ids[offset : offset + 500]))).all()
            names.update({("USER", user.user_id): user.user_name for user in users})
        return [{**self.rule_payload(row), "name": names.get((row.subject_type, row.subject_id))} for row in rows]

    def subject_options(self) -> list[dict]:
        departments = self.memberships._ordered_department_tree(self.memberships._departments())
        return [
            {"kind": "DEPARTMENT", "id": row.id, "name": row.name, "depth": depth} for row, depth in departments
        ] + [{"kind": "ROLE", "id": row.id, "name": row.role_name, "depth": 0} for row in self.memberships._roles()]

    def _audit(self, actor: int, resource: str, before: dict | None, after: dict):
        self.session.add(
            UnifiedPolicyAudit(
                tenant_id=require_tenant(),
                actor_user_id=actor,
                resource=resource,
                before_values=before,
                after_values=after,
            )
        )
        try:
            self.session.flush()
        except IntegrityError as error:
            raise DshOperationConflictError() from error

    def initialize_model_visibility(self, model_id: int, actor: int) -> dict:
        """Give a newly created dialogue model its tenant-wide initial grant."""
        self.memberships._lock_tenant()
        existing = self.visibility(model_id)
        if existing["version"]:
            return existing
        return self.save_visibility(model_id, actor, ModelVisibilityInput(version=0, everyone=True))

    def save_visibility(self, model_id: int, actor: int, value: ModelVisibilityInput) -> dict:
        tenant = require_tenant()
        # Serialize create and update, including the initially absent policy.
        self.memberships._lock_tenant()
        for subject in value.subjects:
            self._validate_subject(subject)
        with strict_tenant_filter():
            row = self.session.exec(
                select(ModelVisibility).where(ModelVisibility.model_id == model_id).with_for_update()
            ).one_or_none()
        before = self.visibility_payload(row)
        if value.version != before["version"]:
            raise DshOperationConflictError()
        if row is None:
            row = ModelVisibility(tenant_id=tenant, model_id=model_id, updated_by=actor)
        row.credit_rate = value.credit_rate
        row.everyone = value.everyone
        row.subjects = [item.model_dump() for item in sorted(value.subjects, key=lambda item: (item.kind, item.id))]
        row.version = value.version + 1
        row.updated_by = actor
        self.session.add(row)
        after = self.visibility_payload(row)
        self._audit(actor, f"model:{model_id}", before, after)
        return after

    def save_rule(self, subject: PolicySubject, actor: int, value: CreditRuleInput) -> dict:
        tenant = require_tenant()
        self.memberships._lock_tenant()
        self._validate_subject(subject)
        with strict_tenant_filter():
            row = self.session.exec(
                select(CreditRule)
                .where(CreditRule.subject_type == subject.kind, CreditRule.subject_id == subject.id)
                .with_for_update()
            ).one_or_none()
        if value.version != (row.version if row else 0):
            raise DshOperationConflictError()
        before = self.rule_payload(row) if row else None
        if row is None:
            row = CreditRule(
                tenant_id=tenant,
                subject_type=subject.kind,
                subject_id=subject.id,
                monthly_token_limit=value.monthly_token_limit,
                updated_by=actor,
            )
        row.monthly_token_limit = value.monthly_token_limit
        row.enabled = value.enabled
        row.version = value.version + 1
        row.updated_by = actor
        self.session.add(row)
        after = self.rule_payload(row)
        self._audit(actor, f"credits:{subject.kind}:{subject.id}", before, after)
        return after

    def effective(self, user_id: int, *, lock: bool = False) -> DshPolicySnapshot:
        tenant = require_tenant()
        if lock:
            self.memberships._lock_tenant()
        departments = self.memberships._department_ancestor_ids(user_id, self.memberships._departments())
        roles = self.memberships._role_ids(user_id)
        with strict_tenant_filter():
            models = self.session.exec(select(ModelVisibility)).all()
            rules = self.session.exec(select(CreditRule)).all()
            ledger = self.session.exec(
                select(PersonalLedgerState).where(PersonalLedgerState.user_id == user_id)
            ).one_or_none()
        epoch = ledger.quota_epoch if ledger else 1
        limit = effective_token_limit(
            user_id=user_id, departments=departments, roles=roles, rules=[row.model_dump() for row in rules]
        )
        rows = [
            DshModelPolicyState(
                model_id=row.model_id,
                credit_rate=row.credit_rate,
                monthly_token_limit=limit,
                enabled=1,
                version=row.version,
                quota_epoch=epoch,
                quota_sync_state="READY",
                pending_operation_id=None,
            )
            for row in models
            if ModelVisibilityInput(**self.visibility_payload(row)).permits(
                user_id=user_id, departments=departments, roles=roles
            )
        ]
        return DshPolicySnapshot(
            tenant_id=tenant, user_id=user_id, rows=rows, shared_token_limit=limit, ledger_epoch=epoch
        )

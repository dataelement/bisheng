"""Tenant credit settings within the current tenant (F016)."""

from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from bisheng.common.errcode.dsh import DshOperationConflictError
from bisheng.core.context.tenant import strict_tenant_filter
from bisheng.dsh.domain.models.credit_setting import DshCreditSetting
from bisheng.dsh.domain.models.unified_policy import UnifiedPolicyAudit
from bisheng.dsh.domain.repositories.admin_operation import require_tenant
from bisheng.dsh.domain.repositories.subject_policy import DshSubjectPolicyRepository
from bisheng.dsh.domain.schemas.pricing import CreditSettingInput, CreditSettingState, format_micro


class DshCreditSettingRepository:
    def __init__(self, session: Session):
        self.session = session

    def _row(self, *, lock: bool = False) -> DshCreditSetting | None:
        statement = select(DshCreditSetting)
        if lock:
            statement = statement.with_for_update()
        with strict_tenant_filter():
            return self.session.exec(statement).one_or_none()

    @staticmethod
    def state(row: DshCreditSetting | None) -> CreditSettingState:
        if row is None:
            return CreditSettingState()
        return CreditSettingState(
            currency=row.currency,
            credit_value_micro=row.credit_value_micro,
            usd_cny_rate_micro=row.usd_cny_rate_micro,
            base_model_id=row.base_model_id,
            version=row.version,
        )

    @staticmethod
    def payload(state: CreditSettingState) -> dict:
        return {
            "version": state.version,
            "currency": state.currency,
            "credit_value": format_micro(state.credit_value_micro),
            "usd_cny_rate": format_micro(state.usd_cny_rate_micro),
            "base_model_id": state.base_model_id,
        }

    def effective(self) -> CreditSettingState:
        """Uncached read used at the start of every billed call."""
        require_tenant()
        return self.state(self._row())

    def save(self, actor: int, value: CreditSettingInput) -> dict:
        tenant = require_tenant()
        # Same tenant lock as visibility and credit rules, so policy writes serialize.
        DshSubjectPolicyRepository(self.session)._lock_tenant()
        row = self._row(lock=True)
        before = self.payload(self.state(row))
        if value.version != before["version"]:
            raise DshOperationConflictError()
        if row is None:
            row = DshCreditSetting(
                tenant_id=tenant, currency=value.currency, credit_value_micro=0, usd_cny_rate_micro=0, updated_by=actor
            )
        row.currency = value.currency
        row.credit_value_micro = value.credit_value_micro
        row.usd_cny_rate_micro = value.usd_cny_rate_micro
        row.base_model_id = value.base_model_id
        row.version = value.version + 1
        row.updated_by = actor
        self.session.add(row)
        after = self.payload(self.state(row))
        self.session.add(
            UnifiedPolicyAudit(
                tenant_id=tenant,
                actor_user_id=actor,
                resource="credit-settings",
                before_values=before,
                after_values=after,
            )
        )
        try:
            self.session.flush()
        except IntegrityError as error:
            raise DshOperationConflictError() from error
        return after

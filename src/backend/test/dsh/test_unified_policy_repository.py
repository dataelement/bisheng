import pytest
from sqlmodel import Session, select

from bisheng.common.errcode.dsh import DshOperationConflictError
from bisheng.core.context.tenant import current_tenant_id, set_current_tenant_id
from bisheng.database.models.tenant import Tenant
from bisheng.dsh.domain.models.unified_policy import (
    CreditRule,
    ModelVisibility,
    PersonalLedgerState,
    UnifiedPolicyAudit,
)
from bisheng.dsh.domain.models.user_policy import DshUserPolicy
from bisheng.dsh.domain.repositories.unified_policy import UnifiedPolicyRepository
from bisheng.dsh.domain.schemas.unified_policy import CreditRuleInput, ModelVisibilityInput, PolicySubject
from bisheng.dsh.domain.services.legacy_credit_migration import migrate_legacy_credits
from test.dsh.test_subject_policy import subject_store as subject_store


@pytest.fixture
def store(subject_store):
    for model in (CreditRule, ModelVisibility, PersonalLedgerState, UnifiedPolicyAudit):
        model.__table__.create(subject_store)
    from bisheng.core.database.tenant_filter import register_tenant_filter_events

    register_tenant_filter_events()
    return subject_store


def test_nested_department_and_role_use_one_personal_allowance(store):
    with Session(store) as session, session.begin():
        repo = UnifiedPolicyRepository(session)
        repo.save_visibility(7, 20, ModelVisibilityInput(version=0, subjects=[PolicySubject(kind="DEPARTMENT", id=10)]))
        repo.save_visibility(8, 20, ModelVisibilityInput(version=0, everyone=True))
        repo.save_rule(PolicySubject(kind="DEPARTMENT", id=10), 20, CreditRuleInput(version=0, monthly_credits="500"))
        repo.save_rule(PolicySubject(kind="ROLE", id=41), 20, CreditRuleInput(version=0, monthly_credits="800"))
        policy = repo.effective(20)
        assert policy.allowed_model_ids == [7, 8]
        assert policy.monthly_token_limit == 800_000_000
        assert repo.effective(21).allowed_model_ids == [8]
        assert repo.effective(21).monthly_token_limit == 0
        repo.save_rule(PolicySubject(kind="USER", id=20), 20, CreditRuleInput(version=0, monthly_credits="0"))
        assert repo.effective(20).monthly_token_limit == 800_000_000
        assert repo.effective(20).allowed_model_ids == [7, 8]
        assert len(session.exec(select(UnifiedPolicyAudit)).all()) == 5
        repo.save_rule(PolicySubject(kind="USER", id=20), 20, CreditRuleInput(version=1, monthly_credits="10000"))
        assert repo.effective(20).monthly_token_limit == 10_000_000_000
        repo.save_rule(
            PolicySubject(kind="USER", id=20), 20, CreditRuleInput(version=2, monthly_credits="10000", enabled=False)
        )
        assert repo.effective(20).monthly_token_limit == 800_000_000


def test_conflict_keeps_committed_rule_and_other_tenant_private(store):
    with Session(store) as session, session.begin():
        repo = UnifiedPolicyRepository(session)
        repo.save_visibility(7, 20, ModelVisibilityInput(version=0, everyone=True))
        with pytest.raises(DshOperationConflictError):
            repo.save_visibility(7, 20, ModelVisibilityInput(version=0, everyone=False))
        assert repo.visibility(7)["everyone"] is True
        session.add(Tenant(id=3, tenant_code="tenant-3", tenant_name="Other"))
    token = set_current_tenant_id(3)
    try:
        with Session(store) as session:
            repo = UnifiedPolicyRepository(session)
            assert repo.visibility(7)["version"] == 0
            assert repo.rules() == []
    finally:
        current_tenant_id.reset(token)


@pytest.mark.parametrize(
    "limits,credits,total",
    [
        ([999999, 2], "1.000001", 1000001),
        ([1000000000000, 1], "1000000.000001", 1000000000001),
        ([9223372036854775806, 1], "9223372036854.775807", 9223372036854775807),
    ],
)
def test_legacy_import_exact_sum_and_idempotence(store, limits, credits, total):
    with Session(store) as session, session.begin():
        session.add_all(
            [
                DshUserPolicy(
                    tenant_id=2,
                    user_id=20,
                    model_id=model,
                    monthly_token_limit=limit,
                    updated_by=20,
                    enabled=1,
                    version=1,
                    quota_epoch=7,
                    quota_sync_state="READY",
                )
                for model, limit in zip([7, 8], limits, strict=True)
            ]
        )
    with Session(store) as session, session.begin():
        preview = migrate_legacy_credits(session, actor_id=20)
        assert preview["total_credits"] == credits
        assert session.exec(select(CreditRule)).first() is None
        applied = migrate_legacy_credits(session, actor_id=20, apply=True)
        assert applied["state"] == "applied"
        assert UnifiedPolicyRepository(session).effective(20).quota_epoch == 7
        assert UnifiedPolicyRepository(session).effective(20).monthly_token_limit == total
        assert migrate_legacy_credits(session, actor_id=20, apply=True)["state"] == "already_applied"


def test_rate_edit_updates_new_policy_and_audit(store):
    with Session(store) as session, session.begin():
        repo = UnifiedPolicyRepository(session)
        repo.save_visibility(7, 20, ModelVisibilityInput(version=0, everyone=True, credit_multiplier="1.25"))
        original = repo.effective(20)
        assert original.rows[0].credit_rate == 125
        value = repo.visibility(7)
        assert value["credit_multiplier"] == "1.25"
        repo.save_visibility(
            7, 20, ModelVisibilityInput(version=value["version"], everyone=True, credit_multiplier="1.1")
        )
        assert repo.effective(20).rows[0].credit_rate == 110
        assert original.rows[0].credit_rate == 125
        audits = session.exec(select(UnifiedPolicyAudit).order_by(UnifiedPolicyAudit.id)).all()
        assert audits[-1].after_values["credit_multiplier"] == "1.1"

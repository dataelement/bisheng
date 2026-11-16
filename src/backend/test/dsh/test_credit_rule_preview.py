"""F016: the credit rule editor previews a member's effective limit before saving."""

from sqlmodel import Session, select

from bisheng.dsh.domain.models.unified_policy import CreditRule
from bisheng.dsh.domain.repositories.unified_policy import UnifiedPolicyRepository
from bisheng.dsh.domain.schemas.unified_policy import UNLIMITED_TOKEN_LIMIT, CreditRuleInput, PolicySubject
from test.dsh.test_subject_policy import subject_store as subject_store
from test.dsh.test_unified_policy_repository import store as store


def rule(credits, enabled=True):
    return CreditRuleInput(version=0, monthly_credits=credits, enabled=enabled)


def test_preview_takes_the_highest_matching_rule_and_writes_nothing(store):
    with Session(store) as session, session.begin():
        repo = UnifiedPolicyRepository(session)
        # With no other rule the member is capped by the own rule alone, or not at all when disabled.
        assert repo.preview_user_limit(21, rule("50")) == 50_000_000
        assert repo.preview_user_limit(21, rule("50", enabled=False)) == UNLIMITED_TOKEN_LIMIT
        repo.save_rule(PolicySubject(kind="DEPARTMENT", id=10), 20, rule("500"))
        repo.save_rule(PolicySubject(kind="ROLE", id=41), 20, rule("800"))
        repo.save_rule(PolicySubject(kind="USER", id=20), 20, rule("300"))
        # Raising the member's own rule above the department and role takes effect.
        assert repo.preview_user_limit(20, rule("1000")) == 1_000_000_000
        # A lower own rule, or a disabled one, leaves the role's higher allowance in force.
        assert repo.preview_user_limit(20, rule("100")) == 800_000_000
        assert repo.preview_user_limit(20, rule("5000", enabled=False)) == 800_000_000
        # Department 10's allowance reaches member 21 through sub-department 12.
        assert repo.preview_user_limit(21, rule("50")) == 500_000_000
        stored = session.exec(select(CreditRule).where(CreditRule.subject_type == "USER")).one()
        assert (stored.subject_id, stored.monthly_token_limit, stored.version) == (20, 300_000_000, 1)

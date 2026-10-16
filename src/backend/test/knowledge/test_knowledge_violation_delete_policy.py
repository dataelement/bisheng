"""知识文档违规删除的档位和豁免."""

from bisheng.knowledge.domain.services.knowledge_violation_delete_policy import (
    deduct_block_reason,
    highest_scope_tier,
    manager_spaces_needing_relation_check,
    monthly_award_exempt,
    resolve_payee_id,
)
from bisheng.points.domain.constants.monthly_reward_rules import MonthlyRuleMatcher


def test_public_tier_wins_even_when_its_rank_is_not_a_score():
    assert highest_scope_tier(["department", "public", "team"]) == "public"
    assert highest_scope_tier(["team_ks", "department"]) == "department"
    assert highest_scope_tier(["team", "team_ks"]) == "team"
    assert highest_scope_tier(["personal"]) is None


def test_clinic_manager_exempt_only_while_file_is_visible_in_that_clinic():
    matcher = MonthlyRuleMatcher(levels=("team_ks",), roles=("manager",))
    assert monthly_award_exempt(
        uploader_id=7,
        space_levels={1: "team_ks", 2: "public"},
        owners_by_space={1: set(), 2: set()},
        managers_by_space={1: {7}, 2: set()},
        enabled_matchers=[matcher],
    )
    assert not monthly_award_exempt(
        uploader_id=7,
        space_levels={2: "public"},
        owners_by_space={2: set()},
        managers_by_space={2: set()},
        enabled_matchers=[matcher],
    )


def test_relation_check_skips_direct_manager_owner_and_disabled_level():
    department_manager = MonthlyRuleMatcher(levels=("department",), roles=("manager",))
    assert manager_spaces_needing_relation_check(
        payee_id=79,
        space_levels={10: "department", 11: "department", 12: "department", 13: "personal", 14: "team"},
        owners_by_space={10: set(), 11: {79}, 12: set(), 13: set(), 14: set()},
        managers_by_space={10: {79}, 11: set(), 12: set(), 13: set(), 14: {79}},
        enabled_matchers=[department_manager],
    ) == [12]


def test_payee_and_self_delete():
    assert resolve_payee_id(None, 4) == 4
    assert resolve_payee_id(9, 4) == 9
    assert resolve_payee_id(None, None) is None
    assert deduct_block_reason(rule_code="R4", payee_id=3, operator_id=3, exempt=False) == "self_author"
    assert deduct_block_reason(rule_code=None, payee_id=3, operator_id=8, exempt=False) == "no_rule"
    assert deduct_block_reason(rule_code="R4", payee_id=3, operator_id=8, exempt=True) == "monthly_award_exempt"
    assert deduct_block_reason(rule_code="R4", payee_id=3, operator_id=8, exempt=False) is None

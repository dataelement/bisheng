"""R4-R6 库档分值校验."""

import pytest

from bisheng.common.errcode.points import PointsRuleConflictError
from bisheng.points.domain.constants.library_scope_score import library_scope_score
from bisheng.points.domain.services.points_rule_service import PointsRuleService


def test_library_scope_score_uses_requested_tier():
    expr = {"mode": "library_scope", "public": 1, "department": 5, "team": 9}
    assert library_scope_score(expr, "public") == 1
    assert library_scope_score(expr, "department") == 5
    assert library_scope_score(expr, "team") == 9


def test_r4_rejects_fixed_score_and_non_positive():
    PointsRuleService.validate_score_expr(
        "R4",
        {"mode": "library_scope", "public": 3, "department": 2, "team": 1},
    )
    with pytest.raises(PointsRuleConflictError):
        PointsRuleService.validate_score_expr("R4", {"mode": "fixed", "score": 3})
    with pytest.raises(PointsRuleConflictError):
        PointsRuleService.validate_score_expr(
            "R5",
            {"mode": "library_scope", "public": 0, "department": 2, "team": 1},
        )
    with pytest.raises(PointsRuleConflictError):
        PointsRuleService.validate_score_expr(
            "R6",
            {"mode": "library_scope", "public": -1, "department": 2, "team": 1},
        )


def test_r1_fixed_score_still_skips_library_scope_check():
    PointsRuleService.validate_score_expr("R1", {"mode": "fixed", "score": 100})

"""G3 阶梯 score_expr 校验单测。"""

from bisheng.points.domain.constants.tier_rule_score_expr import validate_g3_tier_score_expr


def test_validate_g3_accepts_configurable_lifetime_cap():
    err = validate_g3_tier_score_expr(
        {
            "mode": "tier",
            "tiers": [
                {"threshold": 3, "score": 5},
                {"threshold": 10, "score": 12},
                {"threshold": 20, "score": 20},
            ],
            "lifetime_cap": 30,
        }
    )
    assert err is None


def test_validate_g3_rejects_lifetime_below_top_tier():
    err = validate_g3_tier_score_expr(
        {
            "mode": "tier",
            "tiers": [{"threshold": 3, "score": 10}],
            "lifetime_cap": 5,
        }
    )
    assert err == "G3 终身上限不得低于最高档奖励分"


def test_validate_g3_rejects_excessive_lifetime_cap():
    err = validate_g3_tier_score_expr(
        {
            "mode": "tier",
            "tiers": [{"threshold": 3, "score": 5}],
            "lifetime_cap": 10001,
        }
    )
    assert "最大为" in (err or "")

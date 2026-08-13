"""可留空固定分规则启用校验。"""

from bisheng.points.domain.constants.optional_fixed_score_rules import (
    validate_deferred_config_rule_can_enable,
)


def test_g5_requires_score_and_daily_cap_to_enable():
    err = validate_deferred_config_rule_can_enable(
        "G5",
        score_expr={"mode": "fixed", "score": 0},
        daily_cap=10,
        status="enabled",
    )
    assert err == "启用规则须填写积分分值"

    err = validate_deferred_config_rule_can_enable(
        "G5",
        score_expr={"mode": "fixed", "score": 2},
        daily_cap=None,
        status="enabled",
    )
    assert err == "启用规则须填写每日上限"

    assert (
        validate_deferred_config_rule_can_enable(
            "G5",
            score_expr={"mode": "fixed", "score": 2},
            daily_cap=10,
            status="enabled",
        )
        is None
    )
    assert (
        validate_deferred_config_rule_can_enable(
            "G5",
            score_expr={"mode": "fixed", "score": 0},
            daily_cap=None,
            status="disabled",
        )
        is None
    )


def test_m2_requires_score_and_daily_cap_to_enable():
    assert (
        validate_deferred_config_rule_can_enable(
            "M2",
            score_expr={"mode": "fixed", "score": 150},
            daily_cap=None,
            status="enabled",
        )
        == "启用规则须填写每日上限"
    )
    assert (
        validate_deferred_config_rule_can_enable(
            "M2",
            score_expr={"mode": "fixed", "score": 150},
            daily_cap=20,
            status="enabled",
        )
        is None
    )

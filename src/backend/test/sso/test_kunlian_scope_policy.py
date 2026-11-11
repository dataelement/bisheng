"""范围配置只声明允许组合, 新模式在完整接入前不能启动登录。"""

import pytest

from bisheng.core.config.kunlian_scope import resolve_scope_pairs
from test.sso.test_kunlian_admission import config


def test_scope_pairs_preserve_fixed_and_refuse_cartesian_union():
    pairs = {"A": ["WA"], "B": ["WB"]}
    assert resolve_scope_pairs("fixed", "old", ["old-workspace"], pairs) == {"old": frozenset({"old-workspace"})}
    resolved = resolve_scope_pairs("tenant_workspace_map", "old", ["WA", "WB"], pairs)
    assert "WA" in resolved["A"] and "WB" not in resolved["A"]
    assert "WB" in resolved["B"] and "old" not in resolved


@pytest.mark.parametrize("pairs", [{}, {"A": []}, {"*": ["WA"]}, {"A": ["*"]}, {"A": "WA"}, {" A": ["WA"]}])
def test_malformed_scope_policy_is_rejected_as_a_whole(pairs):
    with pytest.raises(ValueError):
        resolve_scope_pairs("tenant_workspace_map", "old", ["old-workspace"], pairs)


def test_fixed_defaults_remain_usable_and_map_mode_stays_gated_until_token_paths_are_integrated():
    conf = config()
    assert not conf.auto_onboarding_enabled
    assert conf.login_scope_mode == "fixed"
    assert not conf.readiness_reasons(multi_tenant_enabled=True)
    conf.login_scope_mode = "tenant_workspace_map"
    conf.tenant_workspace_allowlist = {"A": ["WA"], "B": ["WB"]}
    assert "SCOPE_RUNTIME_NOT_READY" in conf.readiness_reasons(multi_tenant_enabled=True)

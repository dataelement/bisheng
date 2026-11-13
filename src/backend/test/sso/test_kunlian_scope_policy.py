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


def test_fixed_defaults_remain_usable_and_integrated_map_mode_is_ready():
    conf = config()
    assert not conf.auto_onboarding_enabled
    assert conf.login_scope_mode == "fixed"
    assert not conf.readiness_reasons(multi_tenant_enabled=True)
    conf.login_scope_mode = "tenant_workspace_map"
    conf.tenant_workspace_allowlist = {"A": ["WA"], "B": ["WB"]}
    assert not conf.readiness_reasons(multi_tenant_enabled=True)


def test_directory_mode_needs_no_static_list_but_keeps_readiness_gates():
    conf = config().model_copy(update={"login_scope_mode": "directory_active_tenants"})
    conf.allowed_tenant_id, conf.allowed_workspace_ids = "", []
    assert not conf.readiness_reasons(multi_tenant_enabled=True)
    for tenant, workspace in [("A", "WA"), ("B", "WB"), ("future-tenant", "future-workspace")]:
        assert conf.allows_scope(tenant, workspace)
    for tenant, workspace in [("", "WA"), ("A", ""), ("*", "WA"), ("A", "W A"), (123, "WA"), ("A", "W\u0081")]:
        assert not conf.allows_scope(tenant, workspace)
    assert "MULTI_TENANT_REQUIRED" in conf.readiness_reasons(multi_tenant_enabled=False)
    conf.directory_enabled = False
    assert "DIRECTORY_DISABLED" in conf.readiness_reasons(multi_tenant_enabled=True)

"""组织层级打标 helper: 相对深度映射与公司子树外为 None."""

from types import SimpleNamespace

from bisheng.points.domain.constants.org_levels import org_level_for_path
from bisheng.points.domain.services.department_org_level_labeler import (
    apply_org_level_to_nodes,
)


def test_org_level_for_path_maps_relative_depth():
    company = "/1/"
    assert org_level_for_path(company, "/1/") == "company"
    assert org_level_for_path(company, "/1/2/") == "dept"
    assert org_level_for_path(company, "/1/2/3/") == "office"
    assert org_level_for_path(company, "/1/2/3/4/") == "squad"
    assert org_level_for_path(company, "/1/2/3/4/5/") == "squad"


def test_org_level_for_path_outside_or_missing_company_is_none():
    assert org_level_for_path("/1/", "/9/") is None
    assert org_level_for_path(None, "/1/2/") is None
    assert org_level_for_path("/1/", None) is None


def test_apply_org_level_to_nodes_clears_outside_subtree():
    company = SimpleNamespace(path="/1/", org_level=None)
    outside = SimpleNamespace(path="/9/", org_level="dept")
    labeled, levels = apply_org_level_to_nodes([company, outside], "/1/")
    assert company.org_level == "company"
    assert outside.org_level is None
    assert labeled == 1
    assert levels["company"] == 1
    assert levels["squad"] == 0

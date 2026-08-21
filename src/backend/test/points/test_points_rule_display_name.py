"""积分规则 display_name 与默认 name 分离。"""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bisheng.points.domain.constants.rule_display_name import resolve_point_rule_display_name
from bisheng.points.domain.schemas.points_schema import PointRuleRequest
from bisheng.points.domain.services.points_rule_service import PointsRuleService


def test_resolve_point_rule_display_name_prefers_display_name():
    rule = SimpleNamespace(rule_code="G1", name="发布/上传文档到公共库", display_name="公共库上传")
    assert resolve_point_rule_display_name(rule) == "公共库上传"


def test_resolve_point_rule_display_name_falls_back_to_default_name():
    rule = SimpleNamespace(rule_code="G1", name="发布/上传文档到公共库", display_name=None)
    assert resolve_point_rule_display_name(rule) == "发布/上传文档到公共库"


@pytest.mark.asyncio
async def test_update_rule_persists_display_name_not_default_name():
    rule = SimpleNamespace(
        id=1,
        tenant_id=1,
        rule_code="G1",
        rule_type="earn",
        name="发布/上传文档到公共库",
        display_name="发布/上传文档到公共库",
        score_expr={"mode": "fixed", "score": 3},
        daily_cap=15,
        beneficiary="uploader",
        status="enabled",
        remark=None,
        sort_order=1,
    )
    repo = SimpleNamespace(
        get_rule_by_id=AsyncMock(return_value=rule),
        save_rule=AsyncMock(side_effect=lambda r: r),
    )
    session = SimpleNamespace(commit=AsyncMock())
    service = PointsRuleService(session=session, repository=repo)
    body = PointRuleRequest(display_name="运营自定义名")

    out = await service.update_rule(
        1,
        SimpleNamespace(is_admin=lambda: True, is_global_super=True),
        1,
        body,
    )

    assert rule.display_name == "运营自定义名"
    assert rule.name == "发布/上传文档到公共库"
    assert out.display_name == "运营自定义名"
    assert out.name == "发布/上传文档到公共库"

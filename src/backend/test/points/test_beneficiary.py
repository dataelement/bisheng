"""积分受益人白名单测试。"""

import pytest

from bisheng.common.errcode.points import PointsRuleConflictError
from bisheng.points.domain.services.points_rule_service import PointsRuleService


def test_g7_allows_uploader_or_sharer():
    PointsRuleService.validate_beneficiary("G7", "earn", "uploader")
    PointsRuleService.validate_beneficiary("G7", "earn", "sharer")


def test_g4_rejects_configurable_uploader():
    with pytest.raises(PointsRuleConflictError):
        PointsRuleService.validate_beneficiary("G4", "earn", "uploader")

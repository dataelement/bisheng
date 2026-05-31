"""Unit tests for ShougangConf and ConfigService.aget_shougang_conf."""
from __future__ import annotations

# The shared conftest pre-mocks bisheng.common.services.config_service as a
# MagicMock to avoid circular imports in most tests. Here we need the REAL
# ConfigService, so we pop those mock entries before importing.
import sys as _sys

for _mod in (
    'bisheng.common.services',
    'bisheng.common.services.config_service',
):
    _sys.modules.pop(_mod, None)

from unittest.mock import AsyncMock, patch  # noqa: E402

import pytest  # noqa: E402

from bisheng.core.config.settings import ShougangConf  # noqa: E402
from bisheng.common.services.config_service import ConfigService  # noqa: E402


def test_shougang_conf_disabled_when_prefix_empty():
    conf = ShougangConf()
    assert conf.enabled is False
    conf2 = ShougangConf(prefix="")
    assert conf2.enabled is False


def test_shougang_conf_enabled_with_prefix():
    conf = ShougangConf(prefix="GF")
    assert conf.enabled is True
    assert conf.prefix == "GF"


def test_shougang_conf_accepts_unused_fields():
    conf = ShougangConf(
        prefix="GF",
        deployment_label="首钢",
        portal_admin_url="/portal-admin/",
    )
    assert conf.deployment_label == "首钢"
    assert conf.portal_admin_url == "/portal-admin/"


def test_shougang_conf_ignores_invalid_file_encoding_block():
    conf = ShougangConf(prefix="GF", file_encoding=None)
    assert conf.enabled is True
    assert conf.prefix == "GF"


def test_shougang_file_encoding_has_default_document_types():
    conf = ShougangConf(prefix="GF")

    assert conf.file_encoding.document_types == [
        {"code": "POL", "label": "政策制度"},
        {"code": "STD", "label": "标准规范"},
        {"code": "PRO", "label": "流程与程序"},
        {"code": "SPC", "label": "技术规程与诀窍"},
        {"code": "RPT", "label": "报告"},
        {"code": "CAS", "label": "案例"},
        {"code": "DGN", "label": "设计资产"},
        {"code": "PAT", "label": "专利与知识产权"},
        {"code": "TRN", "label": "培训资源"},
    ]


@pytest.mark.asyncio
async def test_aget_shougang_conf_returns_default_when_block_missing():
    with patch.object(ConfigService, "aget_all_config", AsyncMock(return_value={})):
        svc = ConfigService.__new__(ConfigService)
        conf = await svc.aget_shougang_conf()
    assert conf.enabled is False
    assert conf.prefix is None


@pytest.mark.asyncio
async def test_aget_shougang_conf_returns_parsed_block():
    cfg = {"shougang": {"prefix": "GF", "deployment_label": "首钢"}}
    with patch.object(ConfigService, "aget_all_config", AsyncMock(return_value=cfg)):
        svc = ConfigService.__new__(ConfigService)
        conf = await svc.aget_shougang_conf()
    assert conf.enabled is True
    assert conf.prefix == "GF"
    assert conf.deployment_label == "首钢"


@pytest.mark.asyncio
async def test_aget_shougang_conf_swallows_exceptions():
    with patch.object(ConfigService, "aget_all_config",
                      AsyncMock(side_effect=RuntimeError("redis down"))):
        svc = ConfigService.__new__(ConfigService)
        conf = await svc.aget_shougang_conf()
    assert conf.enabled is False

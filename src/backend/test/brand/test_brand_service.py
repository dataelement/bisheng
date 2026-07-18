import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

from bisheng.brand.domain.services.brand_service import BRAND_CONFIG_KEY, BrandService


def build_service(raw_value: str | None) -> tuple[BrandService, AsyncMock]:
    get_value = AsyncMock(return_value=raw_value)
    repository = SimpleNamespace(get_value=get_value)
    return BrandService(repository=repository), get_value


async def test_runtime_config_returns_builtin_brand_when_not_configured() -> None:
    service, get_value = build_service(None)

    config = await service.get_runtime_config()

    assert config["brandName"] == {"zh": "BISHENG", "en": "BISHENG"}
    assert config["assets"]["favicon"]["url"] == "/assets/bisheng/favicon.ico"
    assert "linsightAgentName" not in config
    get_value.assert_awaited_once_with(BRAND_CONFIG_KEY)


async def test_runtime_config_falls_back_to_builtin_brand_for_invalid_saved_config() -> None:
    service, _ = build_service("{invalid json")

    config = await service.get_runtime_config()

    assert config["brandName"] == {"zh": "BISHENG", "en": "BISHENG"}
    assert config["assets"]["headerLogoLight"]["url"] == "/assets/bisheng/login-logo-small.png"


async def test_runtime_config_preserves_saved_brand_and_fills_default_assets() -> None:
    saved_config = json.dumps({"brandName": {"zh": "定制品牌", "en": "Custom Brand"}})
    service, _ = build_service(saved_config)

    config = await service.get_runtime_config()

    assert config["brandName"] == {"zh": "定制品牌", "en": "Custom Brand"}
    assert config["assets"]["favicon"]["url"] == "/assets/bisheng/favicon.ico"

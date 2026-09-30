from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from bisheng.knowledge.domain.services.auto_publish_config_service import AutoPublishConfigService
from bisheng.knowledge.domain.services.auto_publish_service import AutoPublishService
from bisheng.shougang_portal_config.domain.schemas.portal_config_schema import PortalAutoPublishRuleConfig


@pytest.mark.parametrize(
    "selection,category,subcategory,space_id,enabled,expected",
    [
        (None, "POL", "POL-A", 10, True, True),
        ([], "POL", "POL-NEW", 10, True, True),
        (["POL-A", "POL-B"], " pol ", " pol-b ", 10, True, True),
        (["POL-A"], "POL", "POL-B", 10, True, False),
        (["POL-A"], "POL", "", 10, True, False),
        (["POL-A"], "OTHER", "POL-A", 10, True, False),
        (["POL-A"], "POL", "POL-A", 11, True, False),
        (["POL-A"], "POL", "POL-A", 10, False, False),
    ],
)
def test_rule_roundtrip_and_matching(selection, category, subcategory, space_id, enabled, expected):
    payload = dict(id="rule", enabled=enabled, document_type_code="POL", source_space_ids=[10])
    if selection is not None:
        payload["subcategory_codes"] = selection
    stored = PortalAutoPublishRuleConfig.model_validate(payload).model_dump(mode="json")
    rule = AutoPublishConfigService._dict_to_rule(stored)
    result = AutoPublishConfigService.match_rule(
        [rule], space_id, category, file_subcategory_code=subcategory,
    )
    assert (result is rule) is expected
    assert stored["subcategory_codes"] == (selection or [])


def test_schema_normalizes_without_turning_invalid_selection_into_all():
    config = PortalAutoPublishRuleConfig(subcategory_codes=[" pol-a ", "POL-A", "POL-B"])
    assert config.subcategory_codes == ["POL-A", "POL-B"]
    with pytest.raises(ValidationError):
        PortalAutoPublishRuleConfig(subcategory_codes=[" "])


@pytest.mark.parametrize("subcategory,matched", [("POL-A", True), ("POL-B", False)])
async def test_execute_uses_file_subcategory(monkeypatch, subcategory, matched):
    from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFileDao
    from bisheng.knowledge.domain.services.auto_publish_target_resolver import AutoPublishTargetResolver
    from bisheng.knowledge.domain import constants

    monkeypatch.setattr(KnowledgeFileDao, "query_by_id", AsyncMock(return_value=SimpleNamespace(
        knowledge_id=10, split_rule=None, file_subcategory_code=subcategory, tenant_id=1, deleted_at=None, status=2,
    )))
    monkeypatch.setattr(constants, "get_file_category_code_from_split_rule", lambda _: "POL")
    rule = AutoPublishConfigService._dict_to_rule(dict(
        id="rule", enabled=True, document_type_code="POL", source_space_ids=[10],
        subcategory_codes=["POL-A"],
    ))
    monkeypatch.setattr(AutoPublishConfigService, "get_enabled_rules", AsyncMock(return_value=[rule]))
    from bisheng.knowledge.domain.models.knowledge_space_scope import KnowledgeSpaceScopeDao, KnowledgeSpaceLevelEnum
    monkeypatch.setattr(KnowledgeSpaceScopeDao, "aget_by_space_id", AsyncMock(return_value=SimpleNamespace(level=KnowledgeSpaceLevelEnum.DEPARTMENT)))
    resolver = AsyncMock(return_value=None)
    monkeypatch.setattr(AutoPublishTargetResolver, "resolve_target_space_id", resolver)
    if matched:
        with pytest.raises(RuntimeError, match="auto_publish_target_space_not_resolved"):
            await AutoPublishService.execute(file_id=7, tenant_id=1)
    else:
        result = await AutoPublishService.execute(file_id=7, tenant_id=1)
        assert result.skip_reason == "no matching rule"
    assert resolver.await_count == int(matched)


@pytest.mark.parametrize("cache_hit", [True, False])
async def test_cached_and_persisted_rules_keep_selection(monkeypatch, cache_hit):
    from bisheng.core.cache import redis_manager

    payload = [dict(id="rule", enabled=True, document_type_code="POL", source_space_ids=[10],
                    subcategory_codes=["POL-A"])]
    cached = []
    redis = SimpleNamespace(
        get=lambda _: payload if cache_hit else None,
        set=lambda key, value, **kwargs: cached.append(value),
    )
    monkeypatch.setattr(redis_manager, "get_redis_client", AsyncMock(return_value=redis))
    loader = AsyncMock(return_value=payload)
    monkeypatch.setattr(AutoPublishConfigService, "_load_rules_from_config", loader)
    rules = await AutoPublishConfigService.get_enabled_rules(1)
    assert rules[0].subcategory_codes == ["POL-A"]
    assert loader.await_count == int(not cache_hit)
    if not cache_hit:
        assert cached == [payload]

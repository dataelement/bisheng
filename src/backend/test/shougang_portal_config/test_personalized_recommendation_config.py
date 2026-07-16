from copy import deepcopy

import pytest
from pydantic import ValidationError

from bisheng.shougang_portal_config.domain.schemas.portal_config_schema import (
    ShougangPortalAdminConfig,
)


def _config_payload() -> dict:
    return {
        "version": 99,
        "portal": {
            "domains": [
                {
                    "name": "安全",
                    "code": "SAFE",
                    "space_ids": [],
                    "color": "#fff",
                    "bg": "#000",
                    "icon": "Shield",
                    "enabled": True,
                },
                {
                    "name": "停用域",
                    "code": "OLD",
                    "space_ids": [],
                    "color": "#fff",
                    "bg": "#000",
                    "icon": "Archive",
                    "enabled": False,
                },
            ],
            "sections": [],
            "document_types": [],
            "qa": {},
            "recommendation": {
                "provider": "tag_feed",
                "home_strategy": "latest",
                "detail_strategy": "related",
            },
            "display": {
                "home": {"section_page_size": 6},
                "list": {},
                "search": {},
                "detail": {},
            },
            "banners": [],
            "integrations": {},
            "site": {},
        },
        "bisheng": {"base_url": "http://bisheng.example.com"},
        "unified_auth": {},
    }


def test_old_config_receives_personalized_recommendation_defaults():
    config = ShougangPortalAdminConfig.model_validate(_config_payload())

    assert config.portal.domains[0].department_ids == []
    assert config.portal.recommendation.home_total_count == 20
    assert config.portal.recommendation.hot_half_life_days == 7
    assert config.portal.recommendation.home_entry_source_weight == 0.3
    assert config.portal.recommendation.stable_shuffle_score_gap == 5
    assert config.portal.recommendation.stable_shuffle_cycle_days == 7
    assert config.portal.recommendation.personalized_shadow_enabled is False
    assert config.portal.recommendation.personalized_rollout_percent == 0


def test_old_config_expands_missing_home_total_count_to_cover_legacy_section_size():
    payload = _config_payload()
    payload["portal"]["display"]["home"]["section_page_size"] = 32

    config = ShougangPortalAdminConfig.model_validate(payload)

    assert config.portal.recommendation.home_total_count == 32


def test_explicit_home_total_count_is_not_silently_expanded():
    payload = _config_payload()
    payload["portal"]["display"]["home"]["section_page_size"] = 32
    payload["portal"]["recommendation"]["home_total_count"] = 20

    with pytest.raises(ValidationError, match="home_total_count"):
        ShougangPortalAdminConfig.model_validate(payload)


def test_legacy_section_size_above_recommendation_limit_is_rejected():
    payload = _config_payload()
    payload["portal"]["display"]["home"]["section_page_size"] = 51

    with pytest.raises(ValidationError):
        ShougangPortalAdminConfig.model_validate(payload)


def test_domain_department_ids_are_normalized_and_deduplicated_in_input_order():
    payload = _config_payload()
    payload["portal"]["domains"][0]["department_ids"] = [12, 10, 12, 11]

    config = ShougangPortalAdminConfig.model_validate(payload)

    assert config.portal.domains[0].department_ids == [12, 10, 11]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("home_total_count", 0),
        ("home_total_count", 51),
        ("hot_half_life_days", 0),
        ("hot_half_life_days", 91),
        ("home_entry_source_weight", -0.01),
        ("home_entry_source_weight", 1.01),
        ("stable_shuffle_score_gap", -0.01),
        ("stable_shuffle_score_gap", 100.01),
        ("stable_shuffle_cycle_days", 0),
        ("stable_shuffle_cycle_days", 31),
        ("personalized_rollout_percent", -1),
        ("personalized_rollout_percent", 101),
    ],
)
def test_recommendation_parameter_ranges_are_rejected(field: str, value):
    payload = _config_payload()
    payload["portal"]["recommendation"][field] = value

    with pytest.raises(ValidationError):
        ShougangPortalAdminConfig.model_validate(payload)


def test_home_total_count_must_cover_home_section_page_size():
    payload = _config_payload()
    payload["portal"]["display"]["home"]["section_page_size"] = 8
    payload["portal"]["recommendation"]["home_total_count"] = 7

    with pytest.raises(ValidationError, match="home_total_count"):
        ShougangPortalAdminConfig.model_validate(payload)


@pytest.mark.parametrize("department_id", [0, -1])
def test_domain_department_ids_must_be_positive(department_id: int):
    payload = _config_payload()
    payload["portal"]["domains"][0]["department_ids"] = [department_id]

    with pytest.raises(ValidationError):
        ShougangPortalAdminConfig.model_validate(payload)


def test_same_department_can_be_bound_to_multiple_domains():
    payload = _config_payload()
    payload["portal"]["domains"][0]["department_ids"] = [12]
    payload["portal"]["domains"][1]["department_ids"] = [12]

    config = ShougangPortalAdminConfig.model_validate(payload)

    assert [domain.department_ids for domain in config.portal.domains] == [[12], [12]]


def test_disabled_or_uncoded_domain_with_department_ids_remains_schema_compatible():
    payload = _config_payload()
    payload["portal"]["domains"][0]["enabled"] = False
    payload["portal"]["domains"][0]["department_ids"] = [12]
    payload["portal"]["domains"][1]["code"] = ""
    payload["portal"]["domains"][1]["department_ids"] = [13]

    config = ShougangPortalAdminConfig.model_validate(payload)

    assert config.portal.domains[0].department_ids == [12]
    assert config.portal.domains[1].department_ids == [13]


def test_legacy_independent_binding_field_is_ignored_in_favor_of_domain_config():
    payload = _config_payload()
    payload["portal"]["domains"][0]["department_ids"] = [12]
    payload["portal"]["department_business_domain_bindings"] = [
        {"department_id": 99, "business_domain_codes": ["SAFE"]},
    ]

    config = ShougangPortalAdminConfig.model_validate(payload)

    assert config.portal.domains[0].department_ids == [12]
    assert "department_business_domain_bindings" not in config.portal.model_dump()


def test_explicit_valid_personalized_config_round_trips():
    payload = deepcopy(_config_payload())
    payload["portal"]["recommendation"].update(
        {
            "home_total_count": 32,
            "hot_half_life_days": 14,
            "home_entry_source_weight": 0.5,
            "stable_shuffle_score_gap": 12.5,
            "stable_shuffle_cycle_days": 10,
            "personalized_shadow_enabled": True,
            "personalized_rollout_percent": 25,
        }
    )

    config = ShougangPortalAdminConfig.model_validate(payload)
    reloaded = ShougangPortalAdminConfig.model_validate(config.model_dump(mode="json"))

    assert reloaded.portal.recommendation == config.portal.recommendation

from uuid import uuid4

import pytest
from pydantic import ValidationError

from bisheng.api_rate_limit.domain.schemas import (
    ApiRateLimitConfig,
    ApiRateLimitConfigUpdate,
    ApiRateLimitRouteRule,
    RateLimitLimits,
    RateLimitMatchType,
)


def test_zero_and_blank_limits_are_normalized_to_disabled():
    limits = RateLimitLimits(second=0, minute="0", hour="", day=None)

    assert limits.model_dump() == {
        "second": None,
        "minute": None,
        "hour": None,
        "day": None,
    }
    assert limits.is_disabled()


@pytest.mark.parametrize(
    ("match_type", "method"),
    [
        ("METHOD_PATH", None),
        ("PATH", "GET"),
        ("PREFIX", "POST"),
    ],
)
def test_match_type_rejects_invalid_method_combinations(match_type, method):
    with pytest.raises(ValidationError):
        ApiRateLimitRouteRule(
            match_type=match_type,
            method=method,
            path="/api/v1/items/{item_id}",
        )


def test_config_rejects_duplicate_rule_identity():
    rule_id = uuid4()
    payload = {
        "expected_revision": 0,
        "routes": [
            {
                "id": str(rule_id),
                "match_type": "PATH",
                "path": "/api/v1/items/{item_id}",
            },
            {
                "match_type": "PATH",
                "path": "/api/v1/items/{item_id}",
            },
        ],
    }

    with pytest.raises(ValidationError, match="duplicate route rule"):
        ApiRateLimitConfigUpdate.model_validate(payload)


def test_route_rule_with_all_limits_disabled_remains_an_explicit_override():
    config = ApiRateLimitConfig(
        global_rule={"limits": {"minute": 10}, "message": "global"},
        routes=[
            {
                "match_type": RateLimitMatchType.PATH,
                "path": "/api/v1/items/{item_id}",
                "limits": {},
            }
        ],
    )

    from bisheng.api_rate_limit.domain.services import ApiRateLimitService

    resolved = ApiRateLimitService.resolve_policy(
        config,
        method="GET",
        route_template="/api/v1/items/{item_id}",
    )
    assert resolved.policy.limits.is_disabled()
    assert resolved.policy.message == "global"

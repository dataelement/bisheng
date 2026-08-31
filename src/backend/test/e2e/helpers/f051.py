"""Environment-backed helpers for the F051 controllable-provider E2E suite."""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from typing import Any

import httpx
import pytest


def load_f051_cases(env_name: str) -> dict[str, dict[str, Any]]:
    """Load an isolated E2E case map or skip when its external harness is absent."""
    raw = os.environ.get(env_name)
    if not raw:
        pytest.skip(f"{env_name} is required for the F051 controllable-provider E2E harness")
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise AssertionError(f"{env_name} must contain a JSON object")
    return value


def require_case(cases: Mapping[str, dict[str, Any]], name: str) -> dict[str, Any]:
    case = cases.get(name)
    if case is None:
        pytest.skip(f"F051 E2E case {name!r} is not configured")
    prefix = str(case.get("data_prefix", ""))
    assert prefix.startswith("e2e-f051-"), "F051 E2E data must use the e2e-f051- prefix"
    return case


async def configure_fake_provider(case: Mapping[str, Any]) -> None:
    """Reset and arm the external fake provider for exactly one test case."""
    base_url = os.environ.get("E2E_F051_FAKE_PROVIDER_URL")
    if not base_url:
        pytest.skip("E2E_F051_FAKE_PROVIDER_URL is required")
    async with httpx.AsyncClient(base_url=base_url, timeout=15.0) as client:
        response = await client.post("/__e2e/scenario", json=case["provider_scenario"])
        response.raise_for_status()


async def fake_provider_observation(case_name: str) -> dict[str, Any]:
    base_url = os.environ.get("E2E_F051_FAKE_PROVIDER_URL")
    if not base_url:
        pytest.skip("E2E_F051_FAKE_PROVIDER_URL is required")
    async with httpx.AsyncClient(base_url=base_url, timeout=15.0) as client:
        response = await client.get("/__e2e/observation", params={"case": case_name})
        response.raise_for_status()
        data = response.json()
        assert isinstance(data, dict)
        return data


def decode_api_response(response: httpx.Response) -> Any:
    """Decode either a UnifiedResponseModel response or a buffered SSE response."""
    content_type = response.headers.get("content-type", "")
    if "text/event-stream" not in content_type:
        body = response.json()
        assert "status_code" in body, body
        return body.get("data", body)

    events: list[Any] = []
    for line in response.text.splitlines():
        if not line.startswith("data:"):
            continue
        raw = line.removeprefix("data:").strip()
        if not raw:
            continue
        try:
            events.append(json.loads(raw))
        except json.JSONDecodeError:
            events.append(raw)
    return events


def assert_provider_detail_is_hidden(payload: Any) -> None:
    rendered = json.dumps(payload, ensure_ascii=False).lower()
    for forbidden in ("request_id", "allocationquota", "ratequota", "api_key"):
        assert forbidden not in rendered

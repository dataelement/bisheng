"""E2E coverage for F051 model-level rate-limit state and bounded probes.

The suite uses a separately deployed OpenAI-compatible fake provider. It is
environment-gated because running it requires the full BiSheng middleware stack,
two isolated tenants, Celery worker/beat, and models whose base URL points at the
fake provider. See the feature manual checklist for the harness contract.
"""

from __future__ import annotations

import asyncio
import os
from typing import Any

import httpx
import pytest

from test.e2e.helpers.api import API_BASE, assert_resp_200
from test.e2e.helpers.auth import auth_headers, get_admin_token
from test.e2e.helpers.f051 import (
    assert_provider_detail_is_hidden,
    configure_fake_provider,
    decode_api_response,
    fake_provider_observation,
    load_f051_cases,
    require_case,
)

pytestmark = pytest.mark.skipif(
    not os.environ.get("E2E_F051_STATE_CASES_JSON"),
    reason="E2E_F051_STATE_CASES_JSON is required for the F051 external harness",
)


async def _model_projection(client: httpx.AsyncClient, token: str, model_id: int) -> dict[str, Any]:
    response = await client.get("/workstation/config", headers=auth_headers(token))
    data = assert_resp_200(response)
    return next(model for model in data["models"] if int(model["id"]) == model_id)


async def _trigger(client: httpx.AsyncClient, token: str, case: dict[str, Any]) -> Any:
    response = await client.request(
        case.get("method", "POST"),
        case["request_path"],
        json=case.get("request_json"),
        headers=auth_headers(token),
        timeout=60.0,
    )
    response.raise_for_status()
    return decode_api_response(response)


async def _wait_for_state(
    client: httpx.AsyncClient,
    token: str,
    model_id: int,
    expected: str,
    timeout_seconds: float = 125.0,
) -> dict[str, Any]:
    deadline = asyncio.get_running_loop().time() + timeout_seconds
    while asyncio.get_running_loop().time() < deadline:
        projection = await _model_projection(client, token, model_id)
        if projection["rateLimitState"] == expected:
            return projection
        await asyncio.sleep(1.0)
    raise AssertionError(f"model {model_id} did not reach {expected!r}")


class TestE2EAliyunModelRateLimitState:
    """E2E: provider classification, tenant projection, and model-only probes."""

    @pytest.fixture
    async def client(self):
        async with httpx.AsyncClient(base_url=API_BASE, timeout=60.0) as client:
            yield client

    @pytest.fixture
    async def admin_token(self, client):
        return await get_admin_token(client)

    @pytest.fixture
    def cases(self):
        return load_f051_cases("E2E_F051_STATE_CASES_JSON")

    async def test_ac01_temporary_limit_is_standardized_and_projected(
        self,
        client,
        admin_token,
        cases,
    ):
        """AC-01/AC-06/AC-12/AC-55: temporary Aliyun limit becomes safe busy state."""
        case = require_case(cases, "temporary_then_probe_success")
        await configure_fake_provider(case)
        payload = await _trigger(client, admin_token, case)
        assert_provider_detail_is_hidden(payload)
        projection = await _model_projection(client, admin_token, int(case["model_id"]))
        assert projection["rateLimitState"] in {"busy", "recovering"}
        assert projection["availability"] == "normal"

    async def test_ac02_permanent_and_non_aliyun_errors_do_not_mark_busy(
        self,
        client,
        admin_token,
        cases,
    ):
        """AC-02/AC-03/AC-07: excluded errors keep their pre-F051 semantics."""
        for case_name in ("aliyun_permanent_error", "non_aliyun_429"):
            case = require_case(cases, case_name)
            await configure_fake_provider(case)
            payload = await _trigger(client, admin_token, case)
            assert_provider_detail_is_hidden(payload)
            projection = await _model_projection(client, admin_token, int(case["model_id"]))
            assert projection["rateLimitState"] == "normal"

    async def test_ac20_probe_success_only_restores_model_state(
        self,
        client,
        admin_token,
        cases,
    ):
        """AC-17/AC-28-AC-31: bounded probe restores state without replaying sessions."""
        case = require_case(cases, "temporary_then_probe_success")
        await configure_fake_provider(case)
        await _trigger(client, admin_token, case)
        projection = await _wait_for_state(client, admin_token, int(case["model_id"]), "normal")
        assert projection["availability"] == "normal"

        observation = await fake_provider_observation(case["provider_scenario"]["name"])
        assert observation["user_side_effect_delta"] == 0
        assert 1 <= observation["probe_count"] <= 3
        for probe in observation["probe_requests"]:
            rendered = str(probe).lower()
            assert "execution_id" not in rendered
            assert "session" not in rendered
            assert "chat_id" not in rendered
            assert "tools" not in probe
            assert probe.get("max_tokens") == 1

    async def test_ac23_exhausted_probe_stays_busy_and_is_bounded(
        self,
        client,
        admin_token,
        cases,
    ):
        """AC-29/AC-30/AC-32: three failed probes stop without a user execution replay."""
        case = require_case(cases, "temporary_then_probe_exhausted")
        await configure_fake_provider(case)
        await _trigger(client, admin_token, case)
        await asyncio.sleep(float(case.get("settle_seconds", 110)))
        projection = await _model_projection(client, admin_token, int(case["model_id"]))
        assert projection["rateLimitState"] == "busy"
        observation = await fake_provider_observation(case["provider_scenario"]["name"])
        assert observation["probe_count"] == 3
        assert observation["user_side_effect_delta"] == 0

    async def test_ac04_tenant_and_same_name_model_isolation(self, client, admin_token, cases):
        """AC-04/AC-05/AC-53: state is tenant + concrete-model scoped."""
        case = require_case(cases, "tenant_and_same_name_isolation")
        await configure_fake_provider(case)
        await _trigger(client, admin_token, case)
        busy = await _model_projection(client, admin_token, int(case["busy_model_id"]))
        peer = await _model_projection(client, admin_token, int(case["same_name_peer_model_id"]))
        assert busy["rateLimitState"] in {"busy", "recovering"}
        assert peer["rateLimitState"] == "normal"

"""E2E coverage for F051 recovery and the existing task continuation path."""

from __future__ import annotations

import os
import uuid
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
    not os.environ.get("E2E_F051_RECOVERY_CASES_JSON"),
    reason="E2E_F051_RECOVERY_CASES_JSON is required for the F051 external harness",
)


async def _recover(
    client: httpx.AsyncClient,
    token: str,
    case: dict[str, Any],
    *,
    attempt_id: str,
    action: str,
    target_model_id: int | None = None,
) -> Any:
    body: dict[str, Any] = {
        "attempt_id": attempt_id,
        "subject_id": str(case["subject_id"]),
        "action": action,
    }
    if target_model_id is not None:
        body["target_model_id"] = target_model_id
    response = await client.post(case["recover_path"], json=body, headers=auth_headers(token))
    response.raise_for_status()
    payload = decode_api_response(response)
    assert_provider_detail_is_hidden(payload)
    return payload


class TestE2EModelCallRecovery:
    """E2E: only an explicit user command may resume a rate-limited execution."""

    @pytest.fixture
    async def client(self):
        async with httpx.AsyncClient(base_url=API_BASE, timeout=60.0) as client:
            yield client

    @pytest.fixture
    async def admin_token(self, client):
        return await get_admin_token(client)

    @pytest.fixture
    def cases(self):
        return load_f051_cases("E2E_F051_RECOVERY_CASES_JSON")

    @pytest.mark.parametrize("entry", ["daily", "knowledge", "channel"])
    async def test_ac25_recovery_entries_require_an_explicit_command(
        self,
        entry,
        client,
        admin_token,
        cases,
    ):
        """AC-38/AC-39/AC-52: recovery entries resume only on command."""
        case = require_case(cases, entry)
        await configure_fake_provider(case)
        before = await fake_provider_observation(case["provider_scenario"]["name"])
        assert before["user_recovery_call_count"] == 0

        attempt_id = str(uuid.uuid4())
        payload = await _recover(
            client,
            admin_token,
            case,
            attempt_id=attempt_id,
            action="manual_retry",
        )
        rendered = str(payload)
        assert case["execution_id"] in rendered
        assert attempt_id in rendered

        after = await fake_provider_observation(case["provider_scenario"]["name"])
        assert after["user_recovery_call_count"] == 1

    async def test_ac26_near_simultaneous_duplicate_is_best_effort_suppressed(
        self,
        client,
        admin_token,
        cases,
    ):
        """AC-43: a short lock suppresses an immediate duplicate click."""
        case = require_case(cases, "duplicate_attempt")
        await configure_fake_provider(case)
        attempt_id = str(uuid.uuid4())
        await _recover(client, admin_token, case, attempt_id=attempt_id, action="manual_retry")
        duplicate = await _recover(
            client,
            admin_token,
            case,
            attempt_id=attempt_id,
            action="manual_retry",
        )
        assert "False" in str(duplicate) or '"accepted": false' in str(duplicate).lower()
        observation = await fake_provider_observation(case["provider_scenario"]["name"])
        assert observation["user_recovery_call_count"] == 1

    async def test_ac27_switch_success_does_not_require_backend_retry_count(
        self,
        client,
        admin_token,
        cases,
    ):
        """AC-40/AC-46: switch is authorized from the business record."""
        case = require_case(cases, "three_limits_then_switch")
        await configure_fake_provider(case)
        switched = await _recover(
            client,
            admin_token,
            case,
            attempt_id=str(uuid.uuid4()),
            action="switch_model",
            target_model_id=int(case["target_model_id"]),
        )
        assert case["execution_id"] in str(switched)

    @pytest.mark.parametrize("entry", ["daily", "knowledge", "channel"])
    async def test_ac46_history_keeps_only_user_fact_until_recovery_succeeds(
        self,
        entry,
        client,
        admin_token,
        cases,
    ):
        """AC-37/AC-39/AC-50: a throttle writes no answer; success writes one."""
        case = require_case(cases, f"{entry}_history")
        await configure_fake_provider(case)
        before = assert_resp_200(await client.get(case["history_path"], headers=auth_headers(admin_token)))
        await _recover(
            client,
            admin_token,
            case,
            attempt_id=str(uuid.uuid4()),
            action="manual_retry",
        )
        after = assert_resp_200(await client.get(case["history_path"], headers=auth_headers(admin_token)))
        assert len(after) == len(before) + 1
        observation = await fake_provider_observation(case["provider_scenario"]["name"])
        assert observation["duplicate_user_message_delta"] == 0
        assert observation["rate_limit_answer_message_delta"] == 0
        assert observation["successful_answer_message_delta"] == 1

    async def test_ac40_task_rate_limit_uses_existing_continue_endpoint(
        self,
        client,
        admin_token,
        cases,
    ):
        """AC-23/AC-24: task 429 retry follows the existing continue endpoint."""
        case = require_case(cases, "task_continue")
        await configure_fake_provider(case)
        response = await client.post(
            "/linsight/workbench/continue",
            json={
                "session_version_id": str(case["execution_id"]),
                "question": str(case["question"]),
            },
            headers=auth_headers(admin_token),
        )
        assert_resp_200(response)

    async def test_ac24_task_switch_updates_the_existing_session_version(
        self,
        client,
        admin_token,
        cases,
    ):
        """AC-24/AC-25/AC-27: task switch reuses continue and the same session version."""
        case = require_case(cases, "task_continue_switch")
        await configure_fake_provider(case)
        headers = auth_headers(admin_token)
        session_id = str(case["session_id"])
        session_version_id = str(case["execution_id"])
        target_model_id = str(case["target_model_id"])

        before = assert_resp_200(
            await client.get(
                "/linsight/workbench/session-version-list",
                params={"session_id": session_id},
                headers=headers,
            )
        )
        before_ids = [str(item["id"]) for item in before]

        response = await client.post(
            "/linsight/workbench/continue",
            json={
                "session_version_id": session_version_id,
                "question": str(case["question"]),
                "model_id": target_model_id,
            },
            headers=headers,
        )
        assert_resp_200(response)

        after = assert_resp_200(
            await client.get(
                "/linsight/workbench/session-version-list",
                params={"session_id": session_id},
                headers=headers,
            )
        )
        assert [str(item["id"]) for item in after] == before_ids
        switched = next(item for item in after if str(item["id"]) == session_version_id)
        assert str(switched["model"]) == target_model_id

"""Read-only E2E checks for an environment-provisioned E+ assistant.

Prerequisites:
- A running BiSheng backend selected by E2E_API_BASE.
- E2E_EPLUS_ASSISTANT_ID points to a disposable assistant the E2E admin may edit.
- E2E_ADMIN_TOKEN or E2E admin credentials are available.
"""

from __future__ import annotations

import os

import httpx
import pytest

from test.e2e.helpers.api import API_BASE, assert_resp_200
from test.e2e.helpers.auth import auth_headers, get_admin_token

ASSISTANT_ID = os.environ.get("E2E_EPLUS_ASSISTANT_ID", "").strip()

pytestmark = pytest.mark.skipif(
    not ASSISTANT_ID,
    reason="E2E_EPLUS_ASSISTANT_ID is required for read-only E+ environment checks",
)


class TestE2EEPlusRobotAssistant:
    async def test_ac11_configuration_is_safe_and_spaces_are_available(self) -> None:
        """AC-11: Admins can read safe config and bindable spaces without exposing secrets."""
        async with httpx.AsyncClient(timeout=30) as client:
            token = await get_admin_token(client)
            headers = auth_headers(token)
            config_response = await client.get(
                f"{API_BASE}/eplus/assistants/{ASSISTANT_ID}/bot",
                headers=headers,
            )
            config = assert_resp_200(config_response)
            if config is not None:
                assert "secret" not in config
                assert "secret_ciphertext" not in config
                assert "secret_configured" in config
                assert isinstance(config.get("space_ids"), list)

            spaces_response = await client.get(
                f"{API_BASE}/eplus/assistants/{ASSISTANT_ID}/bot/spaces",
                headers=headers,
            )
            spaces = assert_resp_200(spaces_response)
            assert isinstance(spaces, list)
            assert all({"id", "name"}.issubset(item) for item in spaces)

"""Live, read-only E2E coverage for the F052 public configuration contract.

Set ``F052_E2E=1`` only against a dedicated deployment containing the F052
backend and client build. Conversation behavior is covered by the feature's UI
checklist because it requires browser WebSocket observation and test workflows.
"""

from __future__ import annotations

import os

import httpx
import pytest

from test.e2e.helpers.api import API_BASE, assert_resp_200

pytestmark = pytest.mark.skipif(
    os.environ.get("F052_E2E") != "1",
    reason="set F052_E2E=1 only against a dedicated F052 test deployment",
)


@pytest.fixture(scope="module")
async def client():
    async with httpx.AsyncClient(timeout=30.0) as value:
        yield value


class TestE2EF052WorkflowSessionAutoRerun:
    """F052 anonymous system configuration contract."""

    async def test_ac01_ac02_env_exposes_normalized_global_switch(self, client: httpx.AsyncClient) -> None:
        """AC-01/02: /env exposes one global, normalized workflow switch."""
        payload = assert_resp_200(await client.get(f"{API_BASE}/env"))

        assert set(payload["workflow"]) == {"auto_rerun_on_open"}
        assert isinstance(payload["workflow"]["auto_rerun_on_open"], bool)

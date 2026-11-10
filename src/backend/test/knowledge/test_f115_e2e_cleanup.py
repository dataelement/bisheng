"""F115 test infrastructure must refuse cleanup outside the named fixture."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from test.e2e.helpers.cleanup import cleanup_exact_test_library


async def test_cleanup_rejects_a_nontest_name_before_any_http_call():
    client = SimpleNamespace(get=AsyncMock(), request=AsyncMock())
    with pytest.raises(ValueError):
        await cleanup_exact_test_library(client, {}, name="Production library", kind=0, tenant_id=60, owner_id=9)
    client.get.assert_not_called()
    client.request.assert_not_called()


async def test_cleanup_does_not_delete_a_foreign_tenant_fixture():
    name = "e2e-f115-kb-60-0"
    responses = [
        httpx.Response(200, json={"status_code": 200, "data": {"data": [{"id": 1, "name": name}], "has_more": False}}),
        httpx.Response(
            200, json={"status_code": 200, "data": [{"id": 1, "name": name, "tenant_id": 61, "user_id": 9}]}
        ),
    ]
    client = SimpleNamespace(get=AsyncMock(side_effect=responses), request=AsyncMock())
    with pytest.raises(ValueError, match="scope mismatch"):
        await cleanup_exact_test_library(client, {}, name=name, kind=0, tenant_id=60, owner_id=9)
    client.request.assert_not_called()

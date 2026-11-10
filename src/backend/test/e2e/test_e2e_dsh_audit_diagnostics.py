"""Isolated HTTP acceptance; identity, model, billing and storage are synthetic."""

import httpx
import pytest

from test.dsh.test_model_audit_flow import ADMIN, BASE, LOCAL_ADMIN, USER, call, fixture
from test.e2e.helpers.api import assert_resp_200


@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize("failure", [401, 429, 503, "timeout"])
async def test_model_diagnostics_survive_http_and_audit_readback(stream, failure):
    """AC-12, AC-13: keep diagnostic facts, protect metadata and retain existing quota accounting."""
    async with fixture() as (harness, client, _objects):

        async def fail(*_args, **_kwargs):
            if failure == "timeout":
                raise httpx.ReadTimeout("private-provider-body")
            raise httpx.HTTPStatusError(
                "private-provider-body",
                request=httpx.Request("POST", "https://fixture.invalid"),
                response=httpx.Response(failure),
            )

        async def fail_stream(*args, **kwargs):
            await fail(*args, **kwargs)
            yield  # pragma: no cover

        harness.ainvoke = fail
        harness.astream = fail_stream
        response = await call(client, stream=stream)
        assert response.status_code == (200 if stream else 502)
        assert "private-provider-body" not in response.text
        request_id = response.headers["x-request-id"]
        await harness.drain()
        metadata = assert_resp_200(await client.get(BASE + "/requests/" + request_id, headers=ADMIN))
        assert metadata["model_result"] == "FAILED"
        assert metadata["model_error_code"] == (
            "upstream_timeout" if failure == "timeout" else f"upstream_http_{failure}"
        )
        assert metadata["response_result"] == "ERROR"
        assert metadata["response_error_code"] == "error_response"
        assert metadata["usage_settlement"] == "USAGE_UNKNOWN"
        assert "private-provider-body" not in str(metadata)
        assert (await client.get(BASE + "/requests/" + request_id, headers=USER)).status_code == 403
        assert (
            await client.get(BASE + "/requests/" + request_id + "?tenant_id=3", headers=LOCAL_ADMIN)
        ).status_code == 403

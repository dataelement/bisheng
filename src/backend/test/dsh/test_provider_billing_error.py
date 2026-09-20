"""Known provider billing failures keep the DSH HTTP/SSE envelope actionable."""

import json

import httpx
import pytest
from loguru import logger
from openai import BadRequestError

from bisheng.common.errcode.dsh import DshUpstreamErrorError
from test.dsh.test_model_service import service_setup  # noqa: F401
from test.dsh.test_models_api import app_setup  # noqa: F401


@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize("nested", [False, True])
@pytest.mark.parametrize("billing", [False, True])
async def test_provider_billing_rejection_through_http_and_sse(app_setup, stream, nested, billing):  # noqa: F811
    app, _runtime, _model, llm, ledger = app_setup
    provider_id = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"
    sensitive = "private-provider-detail-with-credential"
    detail = {"code": "Arrearage" if billing else "OtherError", "message": sensitive}
    failure = BadRequestError(
        sensitive,
        response=httpx.Response(
            400,
            request=httpx.Request("POST", "https://provider.example/chat/completions"),
            headers={"x-request-id": provider_id},
        ),
        body={"error": detail} if nested else detail,
    )

    async def refuse(*args, **kwargs):
        raise failure

    async def refuse_stream(*args, **kwargs):
        raise failure
        yield  # Keep this fixture an async iterator.

    llm.ainvoke = refuse
    llm.astream = refuse_stream
    logs = []
    sink = logger.add(lambda message: logs.append(str(message)))
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="https://bisheng.example"
        ) as client:
            response = await client.post(
                "/api/v1/dsh/chat/completions",
                headers={"Authorization": "Bearer verified"},
                json={"model": "bisheng:42", "messages": [{"role": "user", "content": "hi"}], "stream": stream},
            )
    finally:
        logger.remove(sink)

    if stream:
        assert response.status_code == 200
        assert "event: error\n" in response.text
        payload = json.loads(next(line[6:] for line in response.text.splitlines() if line.startswith("data: ")))
        assert "[DONE]" not in response.text
    else:
        assert response.status_code == 502
        payload = response.json()
    assert payload["error"]["code"] == "upstream_error"
    assert payload["error"]["type"] == "upstream_error"
    assert payload["request_id"]
    if billing:
        assert "billing" in payload["error"]["message"]
        assert "administrator" in payload["error"]["message"]
        assert provider_id in "".join(logs)
    else:
        assert payload["error"]["message"] == DshUpstreamErrorError.Msg
    assert sensitive not in response.text
    assert sensitive not in "".join(logs)
    assert ledger.events[-1].status == "USAGE_UNKNOWN"
    assert ledger.events[-1].error_code == "upstream_error"
    assert ledger.used == 90
    assert not ledger.frozen

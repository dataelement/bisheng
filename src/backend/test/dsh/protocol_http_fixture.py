"""Opt-in loopback fixture for Desktop serializer/broker -> real DSH -> actual SDK tests.

Run as a module from src/backend. All identity, quota stores and supplier HTTP are
isolated substitutes; no application settings or production storage is loaded.
"""

import json
import socket
from types import SimpleNamespace

import httpx
import uvicorn
from fastapi import FastAPI
from langchain_openai import ChatOpenAI

from bisheng.dsh.api.dependencies import get_runtime
from bisheng.dsh.api.endpoints import models as endpoints
from bisheng.dsh.domain.schemas.chat import ChatCapabilities
from bisheng.dsh.domain.schemas.reasoning import reasoning_declaration
from bisheng.dsh.domain.schemas.responses import DshResponsesRequest
from test.dsh.test_enterprise_protocol import DECLARATION
from test.dsh.test_model_service import principal, service_setup

service, _, ledger, _, _ = service_setup.__wrapped__()
evidence = []
output = {
    "id": "msg_test",
    "type": "message",
    "role": "assistant",
    "status": "completed",
    "content": [{"type": "output_text", "text": "ok", "annotations": []}],
}


async def supplier(request):
    payload = json.loads(request.content)
    evidence.append({"path": request.url.path, "body": payload, "session_id": request.headers.get("session_id")})
    if request.url.path.endswith("/responses"):
        final = {
            "id": "resp_test",
            "object": "response",
            "created_at": 1,
            "status": "completed",
            "model": "supplier-model",
            "output": [output],
            "usage": {"input_tokens": 10, "output_tokens": 2, "total_tokens": 12},
        }
        events = [
            {"type": "response.output_item.added", "output_index": 0, "item": {**output, "content": []}},
            {"type": "response.output_item.done", "output_index": 0, "item": output},
            {"type": "response.completed", "response": final},
        ]
        frames = [
            f"event: {event['type']}\ndata: {json.dumps({**event, 'sequence_number': index})}\n\n"
            for index, event in enumerate(events)
        ]
    else:
        frames = [
            "data: "
            + json.dumps(
                {
                    "id": "chatcmpl_test",
                    "object": "chat.completion.chunk",
                    "created": 1,
                    "model": "supplier-model",
                    **piece,
                }
            )
            + "\n\n"
            for piece in [
                {"choices": [{"index": 0, "delta": {"role": "assistant", "content": "ok"}, "finish_reason": None}]},
                {"choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]},
                {"choices": [], "usage": {"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 12}},
            ]
        ]
        frames.append("data: [DONE]\n\n")
    return httpx.Response(200, text="".join(frames), headers={"content-type": "text/event-stream"})


http = httpx.AsyncClient(transport=httpx.MockTransport(supplier))
sdk = ChatOpenAI(
    model="supplier-model",
    api_key="test-only",
    base_url="https://supplier.invalid/v1",
    http_async_client=http,
    max_retries=0,
    stream_usage=True,
)
service.capabilities_for = lambda *_: ChatCapabilities(responses=True, reasoning=reasoning_declaration(DECLARATION))
service.llm_builder = lambda _model, _server, _principal, request: (
    SimpleNamespace(model_name="supplier-model", llm=sdk) if isinstance(request, DshResponsesRequest) else sdk
)


async def admit(event, **_kwargs):
    ledger.events.append(event)
    return event


ledger.check_and_start = admit


async def authenticate(_header):
    return principal()


runtime = SimpleNamespace(access=SimpleNamespace(authenticate=authenticate))
model_runtime = SimpleNamespace(model=service, complete=service.complete)


async def get_models(_runtime):
    return model_runtime


endpoints.get_model_runtime = get_models
app = FastAPI()
app.include_router(endpoints.router, prefix="/api/v1")
app.dependency_overrides[get_runtime] = lambda: runtime


@app.get("/__evidence")
async def inspect_evidence():
    return {
        "requests": evidence,
        "events": [{"status": event.status, "total_tokens": event.total_tokens} for event in ledger.events],
    }


if __name__ == "__main__":
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    print(json.dumps({"port": listener.getsockname()[1]}), flush=True)
    uvicorn.Server(uvicorn.Config(app, log_level="error", access_log=False)).run(sockets=[listener])

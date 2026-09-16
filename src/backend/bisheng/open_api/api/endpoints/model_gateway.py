"""The OpenAI-compatible model protocol face: ``/api/v2/model/v1`` (F051).

Three routes and nothing else. The two promised ones, plus one catch-all that
refuses every other path in the OpenAI protocol family with a readable answer
instead of a bare framework 404.

The catch-all carries the same ``@open_api_scope`` marker as the real routes on
purpose: credentials are judged before the path is, so a missing key still gets
401, a missing scope still 403, and a delegation-only key still 26051 — the
endpoint list is never enumerable by an unauthenticated caller.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse

from bisheng.common.errcode.model_face import (
    ModelFaceAnthropicNotSupportedError,
    ModelFaceEndpointNotSupportedError,
)
from bisheng.open_api.api.dependencies import get_open_api_execution
from bisheng.open_api.domain.context import OpenApiPrincipal
from bisheng.open_api.domain.schemas.model_gateway import (
    ChatCompletionRequest,
    ChatCompletionResponse,
    ModelList,
)
from bisheng.open_api.domain.scopes import open_api_scope
from bisheng.open_api.domain.services.model_gateway_service import ModelGatewayService

router = APIRouter(prefix="/model/v1", tags=["OpenAPI", "Model"])

# Anthropic's Messages API path. Claude Code and friends land here; they get a
# readable "OpenAI-compatible only" answer rather than a protocol mistranslation.
ANTHROPIC_MESSAGES_PATH = "messages"


@router.post(
    "/chat/completions",
    response_model=ChatCompletionResponse,
    responses={200: {"content": {"text/event-stream": {}}, "description": "Streamed when stream=true"}},
)
@open_api_scope("model:invoke", modes=("S",))
async def chat_completions(
    body: ChatCompletionRequest,
    request: Request,
    principal: OpenApiPrincipal = Depends(get_open_api_execution),
) -> ChatCompletionResponse | StreamingResponse:
    return await ModelGatewayService.complete(principal, request, body)


@router.get("/models", response_model=ModelList)
@open_api_scope("model:invoke", modes=("S",))
async def list_models(
    request: Request,
    principal: OpenApiPrincipal = Depends(get_open_api_execution),
) -> ModelList:
    return await ModelGatewayService.list_models(principal, request.headers)


@router.api_route("/{rest:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH"], include_in_schema=False)
@open_api_scope("model:invoke", modes=("S",))
async def unsupported_endpoint(
    rest: str,
    _principal: OpenApiPrincipal = Depends(get_open_api_execution),
) -> None:
    if rest.strip("/") == ANTHROPIC_MESSAGES_PATH:
        raise ModelFaceAnthropicNotSupportedError()
    raise ModelFaceEndpointNotSupportedError(path=rest)


__all__ = ["ANTHROPIC_MESSAGES_PATH", "router"]

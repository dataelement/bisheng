"""Orchestration for the OpenAI-compatible model protocol face (F051).

Range -> name resolution -> model instantiation -> call -> assemble -> record.
Nothing here builds a session, persists a message body, or injects a prompt:
this face is bare protocol pass-through, a different data plane from
``chat:invoke`` (AC-17 / AC-19).
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator, Mapping
from typing import Any

from fastapi import Request
from fastapi.responses import StreamingResponse
from loguru import logger

from bisheng.common.constants.enums.telemetry import ApplicationTypeEnum
from bisheng.common.errcode.model_face import (
    ModelFaceCapabilityUndeclaredError,
    ModelFaceError,
    ModelFaceModelNotFoundError,
    ModelFaceModelOfflineError,
    ModelFaceModelRevokedError,
    ModelFaceProviderLimitExceededError,
    ModelFaceRequestInvalidError,
    ModelFaceUpstreamError,
)
from bisheng.common.errcode.server import (
    InitLlmError,
    LlmModelConfigDeletedError,
    LlmModelOfflineError,
    LlmModelTypeError,
    LlmProviderDeletedError,
)
from bisheng.core.logger import trace_id_var
from bisheng.llm.domain.services.model_catalog import (
    ResolvedModel,
    list_callable_chat_models,
    resolve_model_name,
)
from bisheng.llm.domain.utils import LlmProviderDailyLimitExceededError
from bisheng.open_api.api.exception_handlers import mark_open_api_error
from bisheng.open_api.domain.context import OpenApiPrincipal
from bisheng.open_api.domain.models.model_call_record import (
    RESULT_CAPABILITY_UNDECLARED,
    RESULT_CLIENT_DISCONNECTED,
    RESULT_LIMIT_EXCEEDED,
    RESULT_MODEL_UNAVAILABLE,
    RESULT_SUCCESS,
    RESULT_UPSTREAM_FAILED,
    ModelCallRecord,
)
from bisheng.open_api.domain.schemas.model_gateway import (
    ChatCompletionRequest,
    ChatCompletionResponse,
    ModelList,
    ModelObject,
    new_request_id,
)
from bisheng.open_api.domain.services.model_call_record_writer import model_call_record_writer
from bisheng.open_api.domain.services.model_range_policy import (
    ResolvedSubject,
    resolve_range_and_subject,
)
from bisheng.open_api.domain.services.openai_codec import (
    SSE_DONE,
    ChunkAssembler,
    build_completion,
    classify_stream_error,
    classify_upstream_error,
    redact_secrets,
    to_langchain_messages,
    usage_from,
)

MODEL_GATEWAY_APP_ID = "model_gateway"

# BishengLLM raises the platform's own model error family before any provider is
# contacted. Translate it into this face's band so a caller can tell "the model
# was taken away" from "the provider misbehaved".
_LLM_ERROR_TRANSLATION: dict[int, type[ModelFaceError]] = {
    LlmModelConfigDeletedError.Code: ModelFaceModelRevokedError,
    LlmProviderDeletedError.Code: ModelFaceModelRevokedError,
    LlmModelTypeError.Code: ModelFaceModelNotFoundError,
    LlmModelOfflineError.Code: ModelFaceModelOfflineError,
    InitLlmError.Code: ModelFaceUpstreamError,
}

STREAM_HEADERS = {
    "Cache-Control": "no-cache",
    # The shipped nginx does not turn proxy buffering off on the /api location,
    # so without this header a stream is accumulated and delivered as one lump.
    "X-Accel-Buffering": "no",
}


class ModelGatewayService:
    @classmethod
    async def list_models(
        cls,
        principal: OpenApiPrincipal,
        headers: Mapping[str, str] | None = None,
    ) -> ModelList:
        model_range, _subject = await resolve_range_and_subject(principal, headers)
        catalog = await list_callable_chat_models(principal.tenant_id)
        created = int(time.time())
        return ModelList(
            data=[
                ModelObject(
                    # Ambiguous rows are offered only under their qualified
                    # name, so every id in this list is directly callable.
                    id=model.callable_name,
                    created=created,
                    owned_by=model.server_name,
                    bisheng_model_type="llm",
                    bisheng_qualified_name=model.qualified_name,
                )
                for model in catalog
                if model_range.allows(model)
            ]
        )

    @classmethod
    async def complete(
        cls,
        principal: OpenApiPrincipal,
        request: Request | None,
        req: ChatCompletionRequest,
    ) -> ChatCompletionResponse | StreamingResponse:
        if req.n is not None and req.n != 1:
            raise ModelFaceRequestInvalidError(
                msg="Only a single completion candidate is supported; set n=1 or omit it",
                param="n",
            )

        headers = request.headers if request is not None else None
        model_range, subject = await resolve_range_and_subject(principal, headers)

        record = cls._start_record(principal, subject, req)
        started = time.monotonic()

        try:
            resolved = await resolve_model_name(principal.tenant_id, req.model, range=model_range)
        except ModelFaceError as exc:
            cls._finish_record(
                record,
                started,
                result=(
                    RESULT_CAPABILITY_UNDECLARED
                    if isinstance(exc, ModelFaceCapabilityUndeclaredError)
                    else RESULT_MODEL_UNAVAILABLE
                ),
                error=exc,
            )
            raise
        cls._attach_model(record, resolved)

        try:
            llm = await cls._instantiate(principal, resolved, req)
        except ModelFaceError as exc:
            cls._finish_record(record, started, result=RESULT_MODEL_UNAVAILABLE, error=exc)
            raise

        messages = to_langchain_messages(req.messages)
        kwargs = req.forwarded_kwargs()
        runnable: Any = llm
        if req.tools:
            # Already OpenAI-shaped dicts: ``bind`` forwards them untouched,
            # while ``bind_tools`` would re-convert them.
            bind_kwargs: dict[str, Any] = {"tools": req.tools}
            if req.tool_choice is not None:
                bind_kwargs["tool_choice"] = req.tool_choice
            runnable = llm.bind(**bind_kwargs)

        if req.stream:
            return await cls._stream(record, started, runnable, messages, kwargs, req, request)
        return await cls._invoke(record, started, runnable, messages, kwargs, req)

    # --- call paths ----------------------------------------------------------

    @classmethod
    async def _invoke(
        cls,
        record: ModelCallRecord,
        started: float,
        runnable: Any,
        messages: list,
        kwargs: dict,
        req: ChatCompletionRequest,
    ) -> ChatCompletionResponse:
        try:
            message = await runnable.ainvoke(messages, **kwargs)
        except LlmProviderDailyLimitExceededError as exc:
            error = ModelFaceProviderLimitExceededError(msg=redact_secrets(str(exc)))
            cls._finish_record(record, started, result=RESULT_LIMIT_EXCEEDED, error=error)
            raise error from exc
        except Exception as exc:
            error = classify_upstream_error(exc)
            cls._finish_record(record, started, result=RESULT_UPSTREAM_FAILED, error=error)
            raise error from exc

        response = build_completion(message, model=req.model, request_id=record.request_id)
        cls._finish_record(record, started, result=RESULT_SUCCESS, usage=response.usage)
        return response

    @classmethod
    async def _stream(
        cls,
        record: ModelCallRecord,
        started: float,
        runnable: Any,
        messages: list,
        kwargs: dict,
        req: ChatCompletionRequest,
        request: Request | None,
    ) -> StreamingResponse:
        # Prefetch the first chunk **before** building the StreamingResponse.
        # The provider's daily-limit check and the whole upstream 4xx family
        # only fire on the first iteration, and once the response object exists
        # the 200 header is already on the wire — the caller would get half a
        # stream instead of a real status. The limit counter is incremented
        # inside that same first iteration, so it must not be probed separately.
        agen = runnable.astream(messages, **kwargs)
        try:
            first_chunk = await anext(agen)
        except StopAsyncIteration:
            first_chunk = None
        except LlmProviderDailyLimitExceededError as exc:
            error = ModelFaceProviderLimitExceededError(msg=redact_secrets(str(exc)))
            cls._finish_record(record, started, result=RESULT_LIMIT_EXCEEDED, error=error)
            raise error from exc
        except Exception as exc:
            error = classify_upstream_error(exc)
            cls._finish_record(record, started, result=RESULT_UPSTREAM_FAILED, error=error)
            raise error from exc

        ttft_ms = int((time.monotonic() - started) * 1000)
        assembler = ChunkAssembler(model=req.model, request_id=record.request_id)
        include_usage = bool(req.stream_options and req.stream_options.include_usage)

        async def generate() -> AsyncIterator[str]:
            yield assembler.role_prelude()
            result = RESULT_SUCCESS
            error: ModelFaceError | None = None
            usage = None
            try:
                if first_chunk is not None:
                    line = assembler.next(first_chunk)
                    if line:
                        yield line
                async for chunk in agen:
                    if request is not None and await request.is_disconnected():
                        result = RESULT_CLIENT_DISCONNECTED
                        break
                    line = assembler.next(chunk)
                    if line:
                        yield line
                if result == RESULT_SUCCESS:
                    yield assembler.finish()
                    # Metering never depends on the caller asking for usage
                    # (AC-23); only the extra usage chunk does.
                    usage = usage_from(assembler.last_chunk)
                    usage_line = assembler.usage(include_usage=include_usage)
                    if usage_line:
                        yield usage_line
            except asyncio.CancelledError:
                cls._finish_record(record, started, result=RESULT_CLIENT_DISCONNECTED, ttft_ms=ttft_ms)
                raise
            except Exception as exc:
                error = classify_stream_error(exc)
                logger.opt(exception=True).error(
                    "model_gateway.stream_failed | request_id={} error_code={}",
                    record.request_id,
                    error.code,
                )
                # The audit middleware only understands the platform's own SSE
                # envelope, so it would score this stream a success; stamping
                # the code keeps the audit row honest.
                if request is not None:
                    mark_open_api_error(request, error)
                yield ChunkAssembler.error(error)
                result = RESULT_UPSTREAM_FAILED
            cls._finish_record(record, started, result=result, error=error, usage=usage, ttft_ms=ttft_ms)
            yield SSE_DONE

        return StreamingResponse(generate(), media_type="text/event-stream", headers=dict(STREAM_HEADERS))

    # --- model instantiation -------------------------------------------------

    @classmethod
    async def _instantiate(
        cls,
        principal: OpenApiPrincipal,
        resolved: ResolvedModel,
        req: ChatCompletionRequest,
    ):
        from bisheng.llm.domain.services.llm import LLMService

        try:
            return await LLMService.get_bisheng_llm(
                model_id=resolved.model_id,
                app_id=MODEL_GATEWAY_APP_ID,
                app_type=ApplicationTypeEnum.MODEL_GATEWAY,
                app_name=f"{MODEL_GATEWAY_APP_ID}:{principal.actor_kind}:{principal.actor_id}",
                # Telemetry is per person; a service account borrows its
                # resource owner so the ledger stays traceable to a human.
                user_id=principal.effective_user_id or principal.resource_owner_user_id or 0,
                streaming=req.stream,
                temperature=req.temperature,
            )
        except ModelFaceError:
            raise
        except Exception as exc:
            translated = _LLM_ERROR_TRANSLATION.get(getattr(exc, "code", None))
            if translated is None:
                raise classify_upstream_error(exc) from exc
            if translated is ModelFaceUpstreamError:
                raise translated(msg=redact_secrets(str(exc))) from exc
            raise translated(model=req.model) from exc

    # --- record bookkeeping --------------------------------------------------

    @staticmethod
    def _start_record(
        principal: OpenApiPrincipal,
        subject: ResolvedSubject,
        req: ChatCompletionRequest,
    ) -> ModelCallRecord:
        return ModelCallRecord(
            # Written explicitly: the flush runs in a background task with no
            # request ContextVar, where the ORM auto-fill contributes nothing.
            tenant_id=principal.tenant_id,
            credential_id=principal.credential_id,
            actor_kind=principal.actor_kind,
            actor_id=principal.actor_id,
            actor_name=principal.actor_name,
            resource_owner_user_id=principal.resource_owner_user_id,
            app_id=subject.app_id,
            subject_kind=subject.subject_kind,
            subject_id=subject.subject_id,
            requested_model=req.model[:255],
            is_stream=req.stream,
            result=RESULT_SUCCESS,
            request_id=new_request_id(),
            trace_id=trace_id_var.get(),
        )

    @staticmethod
    def _attach_model(record: ModelCallRecord, resolved: ResolvedModel) -> None:
        record.model_id = resolved.model_id
        record.server_id = resolved.server_id
        record.model_name = resolved.model_name
        record.server_name = resolved.server_name
        record.server_type = resolved.server_type

    @staticmethod
    def _finish_record(
        record: ModelCallRecord,
        started: float,
        *,
        result: str,
        error: ModelFaceError | None = None,
        usage=None,
        ttft_ms: int | None = None,
    ) -> None:
        record.result = result
        record.latency_ms = max(int((time.monotonic() - started) * 1000), 0)
        record.ttft_ms = ttft_ms
        if error is not None:
            record.error_code = error.code
            record.http_status = error.http_status
        if usage is not None:
            record.prompt_tokens = usage.prompt_tokens
            record.completion_tokens = usage.completion_tokens
            record.total_tokens = usage.total_tokens
        logger.bind(event="model_gateway.call").info(
            "model_gateway.call | credential_id={} actor_kind={} tenant_id={} requested_model={} "
            "model_id={} server_id={} is_stream={} result={} error_code={} prompt_tokens={} "
            "completion_tokens={} latency_ms={} ttft_ms={} trace_id={}",
            record.credential_id,
            record.actor_kind,
            record.tenant_id,
            record.requested_model,
            record.model_id,
            record.server_id,
            record.is_stream,
            record.result,
            record.error_code,
            record.prompt_tokens,
            record.completion_tokens,
            record.latency_ms,
            record.ttft_ms,
            record.trace_id,
        )
        model_call_record_writer.enqueue(record)


__all__ = ["MODEL_GATEWAY_APP_ID", "STREAM_HEADERS", "ModelGatewayService"]

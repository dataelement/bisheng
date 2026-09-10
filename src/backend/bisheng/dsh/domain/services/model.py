"""DSH model calls: governed snapshots, actual-use admission and durable settlement."""

import asyncio
import json
from datetime import UTC, datetime
from uuid import uuid4
from zoneinfo import ZoneInfo

from loguru import logger

from bisheng.common.errcode.dsh import (
    DshContextLengthExceededError,
    DshModelNotAllowedError,
    DshMonthlyTokenLimitExceededError,
    DshQuotaUnavailableError,
    DshUnsupportedParameterError,
    DshUpstreamErrorError,
    DshUpstreamTimeoutError,
    DshUsageUnavailableError,
)
from bisheng.dsh.domain.schemas.chat import ChatCapabilities, DshChatRequest
from bisheng.dsh.domain.schemas.contracts import DshTokenUsage
from bisheng.dsh.domain.schemas.usage import UsageEvent
from bisheng.dsh.domain.services.access import DshPrincipal, principal_scope
from bisheng.dsh.infrastructure.chat_adapter import DshChatAdapter
from bisheng.dsh.infrastructure.quota_redis import QuotaRejected
from bisheng.dsh.infrastructure.telemetry import record_settlement, request_trace


def error_response(error, request_id: str) -> dict:
    return {
        "error": {"message": error.Msg, "type": error.ErrorType, "code": error.ClientCode},
        "request_id": request_id,
    }


def usage_response(usage: DshTokenUsage) -> dict:
    return {
        "prompt_tokens": usage.input_tokens,
        "completion_tokens": usage.output_tokens,
        "total_tokens": usage.total_tokens,
        "prompt_tokens_details": {
            "cached_tokens": usage.cache_read_tokens,
            "cache_creation_tokens": usage.cache_creation_tokens,
        },
    }


def sse(data: dict) -> str:
    return "data: " + json.dumps(data, ensure_ascii=False, separators=(",", ":")) + "\n\n"


class DshModelService:
    def __init__(
        self,
        *,
        policy_reader,
        model_loader,
        llm_builder,
        capabilities_for,
        usage,
        now,
        billing_timezone: str = "Asia/Shanghai",
    ):
        self.policy_reader, self.model_loader, self.llm_builder = policy_reader, model_loader, llm_builder
        self.capabilities_for, self.usage, self.now = capabilities_for, usage, now
        self.billing_timezone = billing_timezone
        self.timezone = ZoneInfo(billing_timezone)
        self.adapter = DshChatAdapter()

    async def list_models(self, principal: DshPrincipal) -> dict:
        with principal_scope(principal):
            policy = await self.policy_reader(int(principal.user_id))
            result = []
            for model_id in policy.allowed_model_ids if policy else []:
                try:
                    model, server = await self.model_loader(model_id)
                except DshModelNotAllowedError:
                    continue
                capabilities = self.capabilities_for(model, server)
                if capabilities is None:
                    continue
                created = model.create_time
                if isinstance(created, datetime):
                    created = created.replace(tzinfo=UTC) if created.tzinfo is None else created
                    created = int(created.timestamp())
                else:
                    created = 0
                result.append(
                    {
                        "id": f"bisheng:{model.id}",
                        "object": "model",
                        "created": created,
                        "owned_by": "bisheng",
                        "display_name": f"{server.name.strip() or server.type} / {model.model_name.strip() or model.name}",
                        "capabilities": capabilities.client_fields(),
                    }
                )
            return {"object": "list", "data": result}

    async def complete(self, principal: DshPrincipal, request: DshChatRequest):
        request_id = str(uuid4())
        with principal_scope(principal), request_trace(request_id):
            policy = await self.policy_reader(int(principal.user_id))
            if policy is None or request.model_id not in policy.allowed_model_ids:
                raise DshModelNotAllowedError()
            selected_policy = next(row for row in policy.rows if row.model_id == request.model_id)
            if selected_policy.quota_sync_state != "READY":
                raise DshQuotaUnavailableError()
            model, server = await self.model_loader(request.model_id)
            if model.id != request.model_id:
                raise DshModelNotAllowedError()
            capabilities: ChatCapabilities | None = self.capabilities_for(model, server)
            if capabilities is None:
                raise DshUnsupportedParameterError()
            llm = self.llm_builder(model, server, principal, request)
            execution = self.adapter.prepare(
                request, llm, capabilities, max_output_tokens=(model.config or {}).get("max_tokens")
            )
            started = self.now()
            started = started.replace(tzinfo=UTC) if started.tzinfo is None else started
            event = UsageEvent(
                request_id=request_id,
                trace_id=request_id,
                tenant_id=int(principal.tenant_id),
                user_id=int(principal.user_id),
                seat_id=principal.seat_id,
                session_id=principal.session_id,
                grant_version=principal.grant_version,
                model_id=request.model_id,
                usage_month=started.astimezone(self.timezone).strftime("%Y-%m"),
                billing_timezone=self.billing_timezone,
                policy_version=selected_policy.version,
                quota_epoch=policy.quota_epoch,
                event_version=1,
                status="RUNNING",
                started_at=started,
            )
            try:
                await self.usage.check_and_start(event)
            except QuotaRejected as error:
                if error.reason == "quota_exceeded":
                    raise DshMonthlyTokenLimitExceededError() from error
                if error.reason == "model_not_allowed":
                    raise DshModelNotAllowedError() from error
                raise DshQuotaUnavailableError() from error
            if request.stream:
                return PreparedStream(self, principal, request, execution, event)
            try:
                result = await execution.invoke()
            except asyncio.CancelledError:
                await asyncio.shield(self._settle(event, execution, "CANCELLED", "cancelled"))
                raise
            except Exception as error:
                await self._settle(event, execution, "FAILED", "upstream_error")
                raise self._public_error(error) from error
            await self._settle(event, execution, "SUCCEEDED")
            return {
                "id": "chatcmpl-" + event.request_id,
                "object": "chat.completion",
                "created": int(started.timestamp()),
                "model": request.model,
                "choices": [{"index": 0, **result}],
                "usage": usage_response(execution.usage),
            }

    @staticmethod
    def _public_error(error):
        if isinstance(
            error,
            (
                DshUsageUnavailableError,
                DshContextLengthExceededError,
                DshUnsupportedParameterError,
                DshUpstreamErrorError,
            ),
        ):
            return error
        if isinstance(error, TimeoutError):
            return DshUpstreamTimeoutError()
        if getattr(error, "code", None) == "context_length_exceeded":
            return DshContextLengthExceededError()
        return DshUpstreamErrorError()

    async def _settle(self, event, execution, status, error_code=None):
        usage = execution.usage
        now = self.now()
        now = now.replace(tzinfo=UTC) if now.tzinfo is None else now
        terminal = UsageEvent.model_validate(
            event.model_copy(
                update={
                    **usage.model_dump(),
                    "event_version": event.event_version + 1,
                    "status": status if usage.total_tokens is not None else "USAGE_UNKNOWN",
                    "usage_source": "PROVIDER" if usage.total_tokens is not None else None,
                    "ended_at": now,
                    "settled_at": now if usage.total_tokens is not None else None,
                    "provider_request_id": execution.provider_request_id,
                    "error_code": error_code or ("usage_missing" if usage.total_tokens is None else None),
                    "latency_ms": max(0, int((now - event.started_at).total_seconds() * 1000)),
                }
            ).model_dump()
        )
        try:
            await self.usage.record_usage(terminal, event.event_version)
        except Exception as error:
            logger.exception("DSH settlement uncertain for request {}", event.request_id)
            try:
                current = await self.usage.get_request(event)
            except Exception:
                logger.exception("DSH settlement could not be confirmed for request {}", event.request_id)
                raise DshUsageUnavailableError() from error
            if current is None or current.model_dump() != terminal.model_dump():
                raise DshUsageUnavailableError() from error
        record_settlement(terminal)

    async def _stream(self, principal, request, execution, event):
        source = execution.stream()
        common = {
            "id": "chatcmpl-" + event.request_id,
            "object": "chat.completion.chunk",
            "created": int(event.started_at.timestamp()),
            "model": request.model,
        }
        first = True
        try:
            async for delta in source:
                if first:
                    delta = {"role": "assistant", **delta}
                    first = False
                yield sse({**common, "choices": [{"index": 0, "delta": delta, "finish_reason": None}]})
        except (asyncio.CancelledError, GeneratorExit):
            await source.aclose()
            await asyncio.shield(self._settle(event, execution, "CANCELLED", "cancelled"))
            raise
        except Exception as error:
            try:
                await self._settle(event, execution, "FAILED", "upstream_error")
                public = self._public_error(error)
            except DshUsageUnavailableError as settlement_error:
                public = settlement_error
            yield "event: error\n" + sse(error_response(public, event.request_id))
            return
        finally:
            await source.aclose()
        try:
            await self._settle(event, execution, "SUCCEEDED")
        except DshUsageUnavailableError as error:
            yield "event: error\n" + sse(error_response(error, event.request_id))
            return
        yield sse({**common, "choices": [{"index": 0, "delta": {}, "finish_reason": execution.finish_reason}]})
        if request.stream_options is not None:
            yield sse({**common, "choices": [], "usage": usage_response(execution.usage)})
        yield "data: [DONE]\n\n"


class PreparedStream:
    """API must close this stream even if the HTTP peer leaves before first read."""

    def __init__(self, service, principal, request, execution, event):
        self.service, self.principal, self.execution, self.event = service, principal, execution, event
        self.source = service._stream(principal, request, execution, event)
        self.started = False
        self.closed = False

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self.closed:
            raise StopAsyncIteration
        self.started = True
        with principal_scope(self.principal), request_trace(self.event.request_id):
            return await anext(self.source)

    async def aclose(self):
        if self.closed:
            return
        self.closed = True
        with principal_scope(self.principal), request_trace(self.event.request_id):
            if not self.started:
                self.execution.usage = DshTokenUsage(input_tokens=0, output_tokens=0, total_tokens=0)
                await self.service._settle(self.event, self.execution, "CANCELLED", "cancelled_before_upstream")
            await self.source.aclose()

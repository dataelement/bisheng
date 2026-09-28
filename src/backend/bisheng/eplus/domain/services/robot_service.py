"""Orchestrate admitted E+ callbacks through the existing assistant runtime."""

from __future__ import annotations

import asyncio
import hashlib
from collections.abc import AsyncIterator
from typing import Any, Protocol

from loguru import logger

from bisheng.assistant.domain.schemas.execution import AssistantRobotScope
from bisheng.eplus.domain.schemas.execution import (
    EPlusAssistantHistoryItem,
    EPlusAssistantRequest,
    EPlusBotRuntimeContext,
    EPlusTurnDelivery,
)
from bisheng.eplus.domain.schemas.protocol import EPlusCallback
from bisheng.eplus.domain.services.conversation_scheduler import ReadyEPlusTurn
from bisheng.eplus.domain.services.media_service import EPlusMediaRef, EPlusPreparedBlock
from bisheng.eplus.domain.services.message_service import (
    AdmissionDisposition,
    AdmissionResult,
    EPlusAdmissionReservation,
)
from bisheng.eplus.domain.services.reply_stream import (
    TIMEOUT_REPLY,
    EPlusReplyDeadlineExceeded,
)
from bisheng.eplus.infrastructure.protocol import stable_stream_id


class EPlusTurnLoader(Protocol):
    async def load(self, ready: ReadyEPlusTurn) -> EPlusTurnDelivery: ...


class EPlusAssistantRuntime(Protocol):
    supports_vision: bool

    def astream(self, request: EPlusAssistantRequest) -> AsyncIterator[str]: ...


class EPlusAssistantFactory(Protocol):
    async def create(self, delivery: EPlusTurnDelivery) -> EPlusAssistantRuntime: ...


class EPlusReplyFactory(Protocol):
    def create(self, *, req_id: str, **kwargs: Any) -> Any: ...


class EPlusRobotService:
    """Keep one sequential consumer per E+ conversation."""

    def __init__(
        self,
        *,
        admission_service: Any,
        scheduler: Any,
        turn_loader: EPlusTurnLoader,
        media_service: Any,
        assistant_factory: EPlusAssistantFactory,
        reply_factory: EPlusReplyFactory,
        execution_timeout_seconds: float = 300,
    ) -> None:
        if execution_timeout_seconds <= 0:
            raise ValueError("E+ assistant execution timeout must be positive")
        self._admission = admission_service
        self._scheduler = scheduler
        self._turn_loader = turn_loader
        self._media = media_service
        self._assistant_factory = assistant_factory
        self._reply_factory = reply_factory
        self._execution_timeout_seconds = float(execution_timeout_seconds)
        self._tasks: dict[tuple[int, str], asyncio.Task[None]] = {}
        self._contexts: dict[tuple[int, str], EPlusBotRuntimeContext] = {}
        self._pending: set[tuple[int, str]] = set()

    async def handle_message(self, context: EPlusBotRuntimeContext, callback: EPlusCallback) -> None:
        result = await self._admission.admit(context.admission, callback)
        await self._handle_admission_result(context, callback, result)

    async def reserve_message(
        self,
        context: EPlusBotRuntimeContext,
        callback: EPlusCallback,
    ) -> AdmissionResult | EPlusAdmissionReservation:
        """Persist idempotency, identity and turn order before slow media I/O."""
        return await self._admission.reserve(context.admission, callback)

    async def handle_reserved_message(
        self,
        context: EPlusBotRuntimeContext,
        callback: EPlusCallback,
        reservation: AdmissionResult | EPlusAdmissionReservation,
    ) -> None:
        result = reservation
        if isinstance(reservation, EPlusAdmissionReservation):
            result = await self._admission.finalize(context.admission, callback, reservation)
        await self._handle_admission_result(context, callback, result)

    async def _handle_admission_result(
        self,
        context: EPlusBotRuntimeContext,
        callback: EPlusCallback,
        result: AdmissionResult,
    ) -> None:
        if result.disposition == AdmissionDisposition.DUPLICATE:
            return
        if result.disposition != AdmissionDisposition.QUEUED:
            stream = self._reply_factory.create(
                sender=context.sender,
                tenant_id=context.admission.tenant_id,
                conversation_id=result.conversation_id or _rejection_quota_key(callback),
                inbound_message_id=result.inbound_message_id,
                req_id=callback.req_id,
                stream_id=stable_stream_id(context.admission.bot_id, callback.msg_id),
            )
            await stream.send_terminal(
                result.reply_text or "处理失败，请稍后重试",  # noqa: RUF001
                error_code=result.disposition.value.upper(),
            )
            return

        if not result.conversation_id:
            raise RuntimeError("queued E+ message has no conversation")
        key = (int(context.admission.tenant_id), result.conversation_id)
        self._contexts[key] = context
        self._pending.add(key)
        wake = getattr(self._scheduler, "wake", None)
        if wake is not None:
            wake(*key)
        self._start_consumer(key)

    async def run_turn(self, context: EPlusBotRuntimeContext, conversation_id: str) -> None:
        """Resume a durable conversation queue after worker recovery."""
        key = (int(context.admission.tenant_id), str(conversation_id))
        self._contexts[key] = context
        self._pending.add(key)
        self._start_consumer(key)

    async def wait_idle(self) -> None:
        while self._tasks:
            await asyncio.gather(*tuple(self._tasks.values()), return_exceptions=True)

    async def close(self) -> None:
        tasks = tuple(self._tasks.values())
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._tasks.clear()
        self._contexts.clear()
        self._pending.clear()

    async def cancel_bot(self, *, tenant_id: int, bot_config_id: int) -> None:
        """Cancel in-process work after this worker loses bot ownership."""
        keys = tuple(
            key
            for key, context in self._contexts.items()
            if key[0] == int(tenant_id) and context.admission.bot_config_id == int(bot_config_id)
        )
        tasks = []
        for key in keys:
            self._pending.discard(key)
            task = self._tasks.get(key)
            if task is not None and not task.done():
                task.cancel()
                tasks.append(task)
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        for key in keys:
            self._contexts.pop(key, None)

    def _start_consumer(self, key: tuple[int, str]) -> None:
        task = self._tasks.get(key)
        if task is not None and not task.done():
            return
        task = asyncio.create_task(self._consume(key), name=f"eplus-turn-{key[0]}-{key[1]}")
        self._tasks[key] = task
        task.add_done_callback(lambda completed, item=key: self._consumer_done(item, completed))

    def _consumer_done(self, key: tuple[int, str], task: asyncio.Task[None]) -> None:
        if self._tasks.get(key) is task:
            self._tasks.pop(key, None)
        if task.cancelled():
            return
        error = task.exception()
        if error is not None:
            logger.opt(exception=error).error(
                "E+ conversation consumer stopped tenant_id={} conversation_hash={}",
                key[0],
                _short_hash(key[1]),
            )
        if key in self._pending and key in self._contexts:
            self._start_consumer(key)
        elif key not in self._tasks:
            self._contexts.pop(key, None)

    async def _consume(self, key: tuple[int, str]) -> None:
        tenant_id, conversation_id = key
        ready: ReadyEPlusTurn | None = None
        while True:
            self._pending.discard(key)
            if ready is None:
                ready = await self._scheduler.next_ready_turn(tenant_id, conversation_id)
            if ready is None:
                if key in self._pending:
                    continue
                return
            context = self._contexts[key]
            current = ready
            try:
                ready = await self._execute_turn(context, current)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.opt(exception=True).error(
                    "E+ turn orchestration failed tenant_id={} turn_hash={}",
                    tenant_id,
                    _short_hash(current.turn.id),
                )
                ready = await self._scheduler.complete_and_wake_next(
                    tenant_id=tenant_id,
                    turn_id=current.turn.id,
                    succeeded=False,
                    error_code="ORCHESTRATION_ERROR",
                    execution_token=current.turn.assistant_run_id or "",
                )

    async def _execute_turn(
        self,
        context: EPlusBotRuntimeContext,
        ready: ReadyEPlusTurn,
    ) -> ReadyEPlusTurn | None:
        delivery = await self._turn_loader.load(ready)
        stream = self._reply_factory.create(
            sender=context.sender,
            tenant_id=delivery.tenant_id,
            conversation_id=delivery.conversation_id,
            inbound_message_id=delivery.inbound_message_id,
            req_id=delivery.req_id,
            stream_id=delivery.stream_id,
        )
        try:
            await stream.start()
        except Exception:
            logger.opt(exception=True).warning(
                "E+ initial reply failed tenant_id={} turn_hash={}",
                delivery.tenant_id,
                _short_hash(delivery.turn_id),
            )
            return await self._complete(delivery, succeeded=False, error_code="REPLY_START_FAILED")

        try:
            async with asyncio.timeout(self._execution_timeout_seconds):
                runtime = await self._assistant_factory.create(delivery)
                request = await self._build_request(context, delivery, runtime.supports_vision)
                async for fragment in runtime.astream(request):
                    await stream.append(fragment)
                    if stream.finished:
                        break
                await stream.finish()
        except asyncio.CancelledError:
            raise
        except (TimeoutError, EPlusReplyDeadlineExceeded):
            logger.warning(
                "E+ assistant execution timed out tenant_id={} turn_hash={}",
                delivery.tenant_id,
                _short_hash(delivery.turn_id),
            )
            try:
                await stream.fail(TIMEOUT_REPLY, error_code="ASSISTANT_TIMEOUT")
            except Exception:
                logger.opt(exception=True).warning(
                    "E+ timeout reply could not be delivered tenant_id={} turn_hash={}",
                    delivery.tenant_id,
                    _short_hash(delivery.turn_id),
                )
            return await self._complete(delivery, succeeded=False, error_code="ASSISTANT_TIMEOUT")
        except Exception:
            logger.opt(exception=True).warning(
                "E+ assistant execution failed tenant_id={} turn_hash={}",
                delivery.tenant_id,
                _short_hash(delivery.turn_id),
            )
            try:
                await stream.fail(
                    "处理失败，请稍后重试",  # noqa: RUF001
                    error_code="ASSISTANT_ERROR",
                )
            except Exception:
                logger.opt(exception=True).warning(
                    "E+ failure reply could not be delivered tenant_id={} turn_hash={}",
                    delivery.tenant_id,
                    _short_hash(delivery.turn_id),
                )
            return await self._complete(delivery, succeeded=False, error_code="ASSISTANT_ERROR")

        return await self._complete(
            delivery,
            succeeded=True,
            answer_text=stream.answer,
        )

    async def _complete(
        self,
        delivery: EPlusTurnDelivery,
        *,
        succeeded: bool,
        answer_text: str | None = None,
        error_code: str | None = None,
    ) -> ReadyEPlusTurn | None:
        return await self._scheduler.complete_and_wake_next(
            tenant_id=delivery.tenant_id,
            turn_id=delivery.turn_id,
            succeeded=succeeded,
            answer_text=answer_text,
            error_code=error_code,
            execution_token=delivery.execution_token,
        )

    async def _build_request(
        self,
        context: EPlusBotRuntimeContext,
        delivery: EPlusTurnDelivery,
        supports_vision: bool,
    ) -> EPlusAssistantRequest:
        content = await self._media.materialize(
            _prepared_blocks(delivery.content_manifest),
            supports_vision=supports_vision,
            user_id=delivery.sender_user_id,
        )
        history: list[EPlusAssistantHistoryItem] = []
        for item in delivery.history:
            manifest = item.content_manifest
            if not manifest and item.user_text is not None:
                manifest = ({"kind": "text", "text": item.user_text, "media": None},)
            prior_content = await self._media.materialize(
                _prepared_blocks(manifest),
                supports_vision=supports_vision,
                user_id=item.sender_user_id,
            )
            history.append(EPlusAssistantHistoryItem(content=prior_content, answer=item.answer_text))

        # The turn owns an immutable scope snapshot. Configuration changes do
        # not cancel it; the next admitted turn receives the newer snapshot.
        scope = AssistantRobotScope(
            bot_config_id=context.admission.bot_config_id,
            space_ids=delivery.space_ids,
            scope_version=delivery.scope_version,
        )
        return EPlusAssistantRequest(
            assistant_id=delivery.assistant_id,
            conversation_id=delivery.conversation_id,
            user_id=delivery.sender_user_id,
            external_user_id=delivery.sender_external_id,
            content=content,
            history=tuple(history),
            robot_scope=scope,
            cancellation_check=context.cancellation_check,
        )


def _prepared_blocks(manifest: tuple[dict[str, Any], ...]) -> tuple[EPlusPreparedBlock, ...]:
    result: list[EPlusPreparedBlock] = []
    for item in manifest:
        media_value = item.get("media")
        media = EPlusMediaRef(**media_value) if isinstance(media_value, dict) else None
        result.append(
            EPlusPreparedBlock(
                kind=str(item.get("kind") or "error"),
                text=item.get("text"),
                media=media,
            )
        )
    return tuple(result)


def _short_hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()[:12]


def _rejection_quota_key(callback: EPlusCallback) -> str:
    conversation_key = callback.chat_id if callback.chat_type == "group" else callback.sender_external_id
    raw = f"{callback.bot_id}\0{callback.chat_type}\0{conversation_key or ''}"
    return f"rejected:{hashlib.sha256(raw.encode()).hexdigest()[:24]}"

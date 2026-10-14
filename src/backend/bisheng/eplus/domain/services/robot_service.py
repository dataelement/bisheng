"""Orchestrate admitted E+ callbacks through the existing assistant runtime."""

from __future__ import annotations

import asyncio
import hashlib
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import datetime
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


@dataclass(slots=True)
class _WaitingReply:
    stream: Any
    bot_config_id: int
    conversation_id: str
    started_at: float
    context: EPlusBotRuntimeContext
    expiry_task: asyncio.Task[None] | None = None
    error_code: str | None = None


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
        self._waiting_replies: dict[tuple[int, str], _WaitingReply] = {}

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
            try:
                await self._start_waiting_reply(context, callback, reservation)
                result = await self._admission.finalize(context.admission, callback, reservation)
            except asyncio.CancelledError:
                # Lease loss/shutdown must never send another frame from the old owner.
                waiting = self._waiting_replies.pop((int(context.admission.tenant_id), reservation.turn_id), None)
                if waiting is not None and waiting.expiry_task is not None:
                    waiting.expiry_task.cancel()
                    await asyncio.gather(waiting.expiry_task, return_exceptions=True)
                raise
            except Exception:
                waiting = await self._pop_waiting_reply(context.admission.tenant_id, reservation.turn_id)
                if waiting is not None and not waiting.stream.finished:
                    try:
                        await waiting.stream.fail("处理失败，请稍后重试", error_code="ADMISSION_ERROR")  # noqa: RUF001
                    except Exception:
                        logger.opt(exception=True).warning(
                            "E+ admission failure reply failed tenant_id={} turn_hash={}",
                            context.admission.tenant_id,
                            _short_hash(reservation.turn_id),
                        )
                raise
            if result.disposition != AdmissionDisposition.QUEUED:
                waiting = await self._pop_waiting_reply(context.admission.tenant_id, reservation.turn_id)
                if waiting is not None and not waiting.stream.finished:
                    await waiting.stream.fail("处理失败，请稍后重试", error_code="ADMISSION_ERROR")  # noqa: RUF001
        await self._handle_admission_result(context, callback, result)

    async def _start_waiting_reply(self, context, callback, reservation) -> None:
        tenant_id = int(context.admission.tenant_id)
        key = (tenant_id, reservation.turn_id)
        queued = (tenant_id, reservation.conversation_id) in self._tasks or any(
            item.conversation_id == reservation.conversation_id and item_key[0] == tenant_id
            for item_key, item in self._waiting_replies.items()
        )
        stream = self._reply_factory.create(
            sender=context.sender,
            tenant_id=tenant_id,
            conversation_id=reservation.conversation_id,
            inbound_message_id=reservation.inbound_message_id,
            req_id=callback.req_id,
            stream_id=stable_stream_id(context.admission.bot_id, callback.msg_id),
        )
        waiting = _WaitingReply(
            stream, context.admission.bot_config_id, reservation.conversation_id, time.monotonic(), context
        )
        self._waiting_replies[key] = waiting
        try:
            await stream.start("排队中" if queued else "处理中")
        except Exception:
            waiting.error_code = "REPLY_START_FAILED"
            logger.opt(exception=True).warning(
                "E+ waiting reply failed tenant_id={} turn_hash={}", tenant_id, _short_hash(reservation.turn_id)
            )
        else:
            waiting.expiry_task = asyncio.create_task(self._expire_waiting_reply(key, waiting))
            logger.info(
                "E+ waiting reply acknowledged tenant_id={} turn_hash={} queued={} elapsed_ms={:.1f}",
                tenant_id,
                _short_hash(reservation.turn_id),
                queued,
                (time.monotonic() - waiting.started_at) * 1000,
            )

    async def _expire_waiting_reply(self, key, waiting: _WaitingReply) -> None:
        await asyncio.sleep(max(0, self._execution_timeout_seconds - (time.monotonic() - waiting.started_at)))
        if self._waiting_replies.get(key) is not waiting:
            return
        waiting.error_code = "ASSISTANT_TIMEOUT"
        expired = False
        try:
            expired = await self._scheduler.expire_waiting_turn(tenant_id=key[0], turn_id=key[1])
            await waiting.stream.fail(TIMEOUT_REPLY, error_code="ASSISTANT_TIMEOUT")
        except Exception:
            logger.opt(exception=True).warning(
                "E+ queued timeout reply failed tenant_id={} turn_hash={}", key[0], _short_hash(key[1])
            )
        finally:
            if expired:
                # Failed SQL turns will never be claimed, so this timer owns cleanup.
                if self._waiting_replies.get(key) is waiting:
                    self._waiting_replies.pop(key, None)
                conversation_key = (key[0], waiting.conversation_id)
                self._contexts[conversation_key] = waiting.context
                self._pending.add(conversation_key)
                self._start_consumer(conversation_key)

    async def _pop_waiting_reply(self, tenant_id: int, turn_id: str) -> _WaitingReply | None:
        waiting = self._waiting_replies.pop((int(tenant_id), str(turn_id)), None)
        if waiting is not None and waiting.expiry_task is not None:
            if waiting.error_code == "ASSISTANT_TIMEOUT":
                # A terminal send already in flight must complete its ACK/SQL recording.
                await waiting.expiry_task
            else:
                waiting.expiry_task.cancel()
                await asyncio.gather(waiting.expiry_task, return_exceptions=True)
        return waiting

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
        expiry_tasks = tuple(
            item.expiry_task for item in self._waiting_replies.values() if item.expiry_task is not None
        )
        for task in expiry_tasks:
            task.cancel()
        if expiry_tasks:
            await asyncio.gather(*expiry_tasks, return_exceptions=True)
        self._waiting_replies.clear()
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
        for key, waiting in tuple(self._waiting_replies.items()):
            if key[0] == int(tenant_id) and waiting.bot_config_id == int(bot_config_id):
                if waiting.expiry_task is not None:
                    waiting.expiry_task.cancel()
                    await asyncio.gather(waiting.expiry_task, return_exceptions=True)
                self._waiting_replies.pop(key, None)
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
                waiting = await self._pop_waiting_reply(tenant_id, current.turn.id)
                if waiting is not None and not waiting.stream.finished:
                    try:
                        await waiting.stream.fail("处理失败，请稍后重试", error_code="ORCHESTRATION_ERROR")  # noqa: RUF001
                    except Exception:
                        logger.opt(exception=True).warning(
                            "E+ orchestration failure reply failed tenant_id={} turn_hash={}",
                            tenant_id,
                            _short_hash(current.turn.id),
                        )
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
        execution_started = time.monotonic()
        delivery = await self._turn_loader.load(ready)
        waiting = await self._pop_waiting_reply(delivery.tenant_id, delivery.turn_id)
        stream = (
            waiting.stream
            if waiting is not None
            else self._reply_factory.create(
                sender=context.sender,
                tenant_id=delivery.tenant_id,
                conversation_id=delivery.conversation_id,
                inbound_message_id=delivery.inbound_message_id,
                req_id=delivery.req_id,
                stream_id=delivery.stream_id,
            )
        )
        if waiting is not None and waiting.error_code is not None:
            return await self._complete(delivery, succeeded=False, error_code=waiting.error_code)
        if delivery.reply_status == "SEND_FAILED":
            return await self._complete(
                delivery, succeeded=False, error_code=delivery.reply_error_code or "REPLY_START_FAILED"
            )
        remaining_seconds = self._execution_timeout_seconds
        if waiting is not None:
            remaining_seconds -= time.monotonic() - waiting.started_at
        elif delivery.reply_started_at is not None:
            remaining_seconds -= max(0, (datetime.now() - delivery.reply_started_at).total_seconds())
        try:
            if waiting is None:
                if remaining_seconds <= 0:
                    await stream.send_terminal(TIMEOUT_REPLY, error_code="ASSISTANT_TIMEOUT")
                    return await self._complete(delivery, succeeded=False, error_code="ASSISTANT_TIMEOUT")
                if delivery.reply_status == "STREAMING":
                    await stream.resume(elapsed_seconds=self._execution_timeout_seconds - remaining_seconds)
                else:
                    await stream.start()
        except Exception:
            logger.opt(exception=True).warning(
                "E+ initial reply failed tenant_id={} turn_hash={}",
                delivery.tenant_id,
                _short_hash(delivery.turn_id),
            )
            return await self._complete(delivery, succeeded=False, error_code="REPLY_START_FAILED")

        try:
            if remaining_seconds <= 0:
                raise TimeoutError("E+ reply window expired while waiting")
            async with asyncio.timeout(remaining_seconds):
                stage_started = time.monotonic()
                runtime = await self._assistant_factory.create(delivery)
                logger.info(
                    "E+ assistant initialized tenant_id={} turn_hash={} elapsed_ms={:.1f}",
                    delivery.tenant_id,
                    _short_hash(delivery.turn_id),
                    (time.monotonic() - stage_started) * 1000,
                )
                stage_started = time.monotonic()
                request = await self._build_request(
                    context, delivery, runtime.supports_vision, history_budget=getattr(runtime, "history_budget", 64000)
                )
                logger.info(
                    "E+ input prepared tenant_id={} turn_hash={} elapsed_ms={:.1f}",
                    delivery.tenant_id,
                    _short_hash(delivery.turn_id),
                    (time.monotonic() - stage_started) * 1000,
                )
                stage_started = time.monotonic()
                first_fragment = True
                async for fragment in runtime.astream(request):
                    if fragment and first_fragment:
                        first_fragment = False
                        logger.info(
                            "E+ assistant first text tenant_id={} turn_hash={} elapsed_ms={:.1f}",
                            delivery.tenant_id,
                            _short_hash(delivery.turn_id),
                            (time.monotonic() - stage_started) * 1000,
                        )
                    await stream.append(fragment)
                    if stream.finished:
                        break
                await stream.finish()
                logger.info(
                    "E+ reply completed tenant_id={} turn_hash={} elapsed_ms={:.1f}",
                    delivery.tenant_id,
                    _short_hash(delivery.turn_id),
                    (time.monotonic() - execution_started) * 1000,
                )
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
            extracted_text="\n".join(str(part.get("text") or "") for part in request.content)
            if not runtime.supports_vision
            else None,
        )

    async def _complete(
        self,
        delivery: EPlusTurnDelivery,
        *,
        succeeded: bool,
        answer_text: str | None = None,
        error_code: str | None = None,
        extracted_text: str | None = None,
    ) -> ReadyEPlusTurn | None:
        extra = {"extracted_text": extracted_text} if extracted_text is not None else {}
        return await self._scheduler.complete_and_wake_next(
            tenant_id=delivery.tenant_id,
            turn_id=delivery.turn_id,
            succeeded=succeeded,
            answer_text=answer_text,
            error_code=error_code,
            execution_token=delivery.execution_token,
            **extra,
        )

    async def _build_request(
        self,
        context: EPlusBotRuntimeContext,
        delivery: EPlusTurnDelivery,
        supports_vision: bool,
        *,
        history_budget: int = 64000,
    ) -> EPlusAssistantRequest:
        content = await self._media.materialize(
            _prepared_blocks(delivery.content_manifest),
            supports_vision=supports_vision,
            user_id=delivery.sender_user_id,
        )
        history: list[EPlusAssistantHistoryItem] = []
        remaining = max(0, min(int(history_budget), 64000) - _content_cost(content))
        for item in reversed(delivery.history[-20:]):
            manifest = item.content_manifest
            if item.extracted_text is not None and not supports_vision:
                manifest = ({"kind": "text", "text": item.extracted_text, "media": None},)
            if not manifest and item.user_text is not None:
                manifest = ({"kind": "text", "text": item.user_text, "media": None},)
            estimated_cost = (
                len(item.answer_text.encode("utf-8"))
                + sum(
                    4096 if block.get("kind") == "image" else len(str(block.get("text") or "").encode("utf-8"))
                    for block in manifest
                )
                + 8
            )
            if estimated_cost > remaining:
                break
            prior_content = await self._media.materialize(
                _prepared_blocks(manifest),
                supports_vision=supports_vision,
                user_id=item.sender_user_id,
            )
            actual_cost = _content_cost(prior_content) + len(item.answer_text.encode("utf-8")) + 8
            if actual_cost > remaining:
                break
            remaining -= actual_cost
            history.append(EPlusAssistantHistoryItem(content=prior_content, answer=item.answer_text))
        history.reverse()
        logger.info(
            "E+ history prepared tenant_id={} turn_hash={} loaded_turns={} retained_turns={}",
            delivery.tenant_id,
            _short_hash(delivery.turn_id),
            len(delivery.history),
            len(history),
        )

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


def _content_cost(content: Any) -> int:
    """UTF-8 bytes conservatively bound text tokens without blocking tokenization."""
    if isinstance(content, str):
        return len(content.encode("utf-8")) + 4
    return (
        sum(
            4096 if block.get("type") == "image_url" else len(str(block.get("text") or "").encode("utf-8"))
            for block in content
        )
        + 4
    )


def _short_hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()[:12]


def _rejection_quota_key(callback: EPlusCallback) -> str:
    conversation_key = callback.chat_id if callback.chat_type == "group" else callback.sender_external_id
    raw = f"{callback.bot_id}\0{callback.chat_type}\0{conversation_key or ''}"
    return f"rejected:{hashlib.sha256(raw.encode()).hexdigest()[:24]}"

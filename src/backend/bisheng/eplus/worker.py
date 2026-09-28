"""Dedicated long-lived worker for COFCO E+ robot connections."""

from __future__ import annotations

import asyncio
import contextlib
import signal
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage
from loguru import logger
from sqlalchemy import update
from sqlalchemy.ext.asyncio import async_sessionmaker
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.api.services.assistant_agent import AssistantAgent
from bisheng.assistant.domain.schemas.execution import AssistantEntryPoint, AssistantExecutionContext
from bisheng.common.services.config_service import settings
from bisheng.core.cache.redis_manager import get_redis_client
from bisheng.core.context.manager import close_app_context, initialize_app_context
from bisheng.core.context.tenant import (
    bypass_tenant_filter,
    current_tenant_id,
    set_current_tenant_id,
)
from bisheng.core.database.manager import get_database_connection
from bisheng.core.storage.minio.minio_manager import get_minio_storage
from bisheng.database.models.assistant import Assistant, AssistantDao, AssistantStatus
from bisheng.eplus.domain.models.eplus import (
    EPlusBotConfig,
    EPlusConnectionStatus,
    EPlusConversation,
    EPlusInboundMessage,
    EPlusReplyStatus,
)
from bisheng.eplus.domain.repositories.eplus_repository import EPlusConfigRepository
from bisheng.eplus.domain.schemas.config import EPlusConnectionTarget
from bisheng.eplus.domain.schemas.execution import (
    EPlusAssistantRequest,
    EPlusBotRuntimeContext,
    EPlusTurnDelivery,
)
from bisheng.eplus.domain.services.conversation_scheduler import EPlusConversationScheduler, ReadyEPlusTurn
from bisheng.eplus.domain.services.identity_service import EPlusIdentityService
from bisheng.eplus.domain.services.media_service import EPlusMediaService
from bisheng.eplus.domain.services.message_service import EPlusAdmissionContext, EPlusMessageAdmissionService
from bisheng.eplus.domain.services.reply_stream import EPlusReplyStream, RedisReplyQuota
from bisheng.eplus.domain.services.robot_service import EPlusRobotService
from bisheng.eplus.infrastructure.connection_client import EPlusConnectionClient, EPlusConnectionConfig
from bisheng.eplus.infrastructure.connection_supervisor import (
    BotConnectionRef,
    EPlusConnectionSupervisor,
    RedisConfigNotificationSource,
)
from bisheng.eplus.infrastructure.credential_store import PlatformCredentialStore
from bisheng.eplus.infrastructure.media_store import (
    DailyChatImageTextExtractor,
    MinioEPlusMediaStore,
    SecureEPlusMediaDownloader,
)
from bisheng.eplus.infrastructure.protocol import parse_message_callback


class WorkerSupervisor(Protocol):
    async def start(self) -> None: ...

    async def stop(self) -> None: ...


class ClosableRobotService(Protocol):
    async def close(self) -> None: ...


class CallbackTaskRegistry:
    """Keep durable admission work alive across a WebSocket reconnect."""

    def __init__(self) -> None:
        self._tasks: set[asyncio.Task[None]] = set()

    def spawn(self, awaitable: Awaitable[None]) -> None:
        task = asyncio.create_task(awaitable)
        self._tasks.add(task)
        task.add_done_callback(self._done)

    async def close(self) -> None:
        if self._tasks:
            await asyncio.gather(*tuple(self._tasks), return_exceptions=True)

    def _done(self, task: asyncio.Task[None]) -> None:
        self._tasks.discard(task)
        if task.cancelled():
            return
        error = task.exception()
        if error is not None:
            logger.opt(exception=error).error("E+ callback admission task failed")


@dataclass(frozen=True, slots=True)
class EPlusWorkerRuntime:
    supervisor: WorkerSupervisor
    robot_service: ClosableRobotService
    callback_registry: CallbackTaskRegistry | None = None

    async def close(self) -> None:
        try:
            await self.supervisor.stop()
        finally:
            try:
                if self.callback_registry is not None:
                    await self.callback_registry.close()
            finally:
                await self.robot_service.close()


class EPlusWorker:
    """Initialize the platform runtime, then own E+ connections until stopped."""

    def __init__(
        self,
        *,
        settings: Any,
        initialize_context: Callable[..., Awaitable[None]] = initialize_app_context,
        build_runtime: Callable[[], Awaitable[EPlusWorkerRuntime]] | None = None,
        close_context: Callable[[], Awaitable[None]] = close_app_context,
        shutdown_timeout_seconds: float = 30,
    ) -> None:
        self._settings = settings
        self._initialize_context = initialize_context
        self._build_runtime = build_runtime or build_worker_runtime
        self._close_context = close_context
        self._shutdown_timeout = float(shutdown_timeout_seconds)
        self._stop_event = asyncio.Event()

    def request_stop(self) -> None:
        self._stop_event.set()

    async def run(self) -> None:
        initialized = False
        runtime: EPlusWorkerRuntime | None = None
        try:
            await self._initialize_context(self._settings, instance_role="eplus_worker")
            initialized = True
            runtime = await self._build_runtime()
            await runtime.supervisor.start()
            logger.info("E+ connection worker started")
            await self._stop_event.wait()
        finally:
            if runtime is not None:
                try:
                    async with asyncio.timeout(self._shutdown_timeout):
                        await runtime.close()
                except TimeoutError:
                    logger.error("E+ worker runtime shutdown timed out")
                except Exception:
                    logger.exception("E+ worker runtime shutdown failed")
            if initialized:
                try:
                    async with asyncio.timeout(self._shutdown_timeout):
                        await self._close_context()
                except TimeoutError:
                    logger.error("E+ application context shutdown timed out")
                except Exception:
                    logger.exception("E+ application context shutdown failed")
            logger.info("E+ connection worker stopped")


class SqlEPlusTargetProvider:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory
        self._credentials = PlatformCredentialStore()

    async def list_bot_refs(self) -> tuple[BotConnectionRef, ...]:
        with bypass_tenant_filter():
            async with self._session_factory() as session:
                rows = await session.exec(
                    select(EPlusBotConfig.tenant_id, EPlusBotConfig.id).where(
                        EPlusBotConfig.is_deleted.is_(False),
                    )
                )
                return tuple(
                    BotConnectionRef(tenant_id=int(tenant_id), bot_config_id=int(config_id))
                    for tenant_id, config_id in rows.all()
                )

    async def resolve_target(self, ref: BotConnectionRef) -> EPlusConnectionTarget | None:
        with _tenant_scope(ref.tenant_id):
            async with self._session_factory() as session:
                row = await EPlusConfigRepository(session).get_by_id(
                    tenant_id=ref.tenant_id,
                    bot_config_id=ref.bot_config_id,
                )
                if row is None or row.is_deleted or not row.enabled or not row.secret_ciphertext:
                    return None
                assistant = (
                    await session.exec(
                        select(Assistant).where(
                            Assistant.id == row.assistant_id,
                            Assistant.tenant_id == ref.tenant_id,
                        )
                    )
                ).first()
                if assistant is None or assistant.is_delete or assistant.status != AssistantStatus.ONLINE.value:
                    return None
                return EPlusConnectionTarget(
                    tenant_id=ref.tenant_id,
                    bot_config_id=int(row.id),
                    assistant_id=row.assistant_id,
                    bot_id=row.bot_id,
                    connection_url=row.connection_url,
                    secret=self._credentials.decrypt(row.secret_ciphertext),
                    ca_object_key=row.ca_object_key,
                    media_hosts=tuple(row.media_host_allowlist),
                    credential_version=int(row.credential_version),
                    scope_version=int(row.scope_version),
                )

    async def read_ca(self, target: EPlusConnectionTarget) -> bytes | None:
        if not target.ca_object_key:
            return None
        minio = await get_minio_storage()
        return await minio.get_object(object_name=target.ca_object_key)

    async def set_status(self, ref: BotConnectionRef, status: EPlusConnectionStatus) -> None:
        values: dict[str, Any] = {"connection_status": status.value}
        now = datetime.now()
        if status is EPlusConnectionStatus.AUTHENTICATED:
            values.update(last_connected_at=now, last_error_code=None)
        elif status in {EPlusConnectionStatus.ERROR, EPlusConnectionStatus.TAKEN_OVER}:
            values["last_error_at"] = now
        with _tenant_scope(ref.tenant_id):
            async with self._session_factory() as session, session.begin():
                await session.exec(
                    update(EPlusBotConfig)
                    .where(
                        EPlusBotConfig.tenant_id == ref.tenant_id,
                        EPlusBotConfig.id == ref.bot_config_id,
                    )
                    .values(**values)
                    .execution_options(synchronize_session=False)
                )

    async def runtime_context(
        self,
        ref: BotConnectionRef,
        sender: Any,
    ) -> EPlusBotRuntimeContext | None:
        target = await self.resolve_target(ref)
        if target is None:
            return None
        with _tenant_scope(ref.tenant_id):
            async with self._session_factory() as session:
                space_ids = await EPlusConfigRepository(session).list_space_ids(
                    tenant_id=ref.tenant_id,
                    bot_config_id=ref.bot_config_id,
                )
        return EPlusBotRuntimeContext(
            admission=EPlusAdmissionContext(
                tenant_id=ref.tenant_id,
                bot_config_id=ref.bot_config_id,
                assistant_id=target.assistant_id,
                bot_id=target.bot_id,
                scope_version=target.scope_version,
                space_ids=tuple(space_ids),
                media_hosts=target.media_hosts,
                ca_pem=await self.read_ca(target),
            ),
            sender=sender,
        )


class SqlEPlusTurnLoader:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def load(self, ready: ReadyEPlusTurn) -> EPlusTurnDelivery:
        turn = ready.turn
        async with self._session_factory() as session:
            inbound = (
                await session.exec(
                    select(EPlusInboundMessage).where(
                        EPlusInboundMessage.tenant_id == turn.tenant_id,
                        EPlusInboundMessage.id == turn.inbound_message_id,
                    )
                )
            ).first()
            conversation = (
                await session.exec(
                    select(EPlusConversation).where(
                        EPlusConversation.tenant_id == turn.tenant_id,
                        EPlusConversation.id == turn.conversation_id,
                    )
                )
            ).first()
        if inbound is None or conversation is None:
            raise LookupError("E+ turn delivery records are missing")
        return EPlusTurnDelivery(
            tenant_id=int(turn.tenant_id),
            assistant_id=conversation.assistant_id,
            conversation_id=turn.conversation_id,
            turn_id=turn.id,
            inbound_message_id=turn.inbound_message_id,
            req_id=inbound.req_id,
            stream_id=inbound.stream_id,
            sender_user_id=turn.sender_user_id,
            sender_external_id=turn.sender_external_id,
            content_manifest=tuple(turn.content_manifest),
            scope_version=turn.scope_version,
            space_ids=tuple(turn.scope_space_ids),
            history=ready.history,
        )


class SqlReplyStateRecorder:
    def __init__(self, session_factory, *, tenant_id: int, inbound_message_id: int) -> None:
        self._session_factory = session_factory
        self._tenant_id = tenant_id
        self._inbound_message_id = inbound_message_id

    async def record(self, status: EPlusReplyStatus, *, error_code: str | None = None) -> None:
        values: dict[str, Any] = {"reply_status": status.value}
        if error_code is not None:
            values["error_code"] = error_code
        async with self._session_factory() as session, session.begin():
            await session.exec(
                update(EPlusInboundMessage)
                .where(
                    EPlusInboundMessage.tenant_id == self._tenant_id,
                    EPlusInboundMessage.id == self._inbound_message_id,
                )
                .values(**values)
                .execution_options(synchronize_session=False)
            )


class ProductionReplyFactory:
    def __init__(self, session_factory, redis_client: Any) -> None:
        self._session_factory = session_factory
        self._redis = redis_client

    def create(self, **values: Any) -> EPlusReplyStream:
        tenant_id = int(values["tenant_id"])
        conversation_id = str(values["conversation_id"])
        return EPlusReplyStream(
            sender=values["sender"],
            quota=RedisReplyQuota(
                redis_client=self._redis,
                tenant_id=tenant_id,
                conversation_id=conversation_id,
            ),
            recorder=SqlReplyStateRecorder(
                self._session_factory,
                tenant_id=tenant_id,
                inbound_message_id=int(values["inbound_message_id"]),
            ),
            req_id=str(values["req_id"]),
            stream_id=str(values["stream_id"]),
        )


class BiShengAssistantRuntime:
    def __init__(self, agent: AssistantAgent) -> None:
        self._agent = agent
        self.supports_vision = agent.supports_vision

    async def astream(self, request: EPlusAssistantRequest) -> AsyncIterator[str]:
        context = AssistantExecutionContext(
            entry_point=AssistantEntryPoint.EPLUS,
            user_id=request.user_id,
            external_user_id=request.external_user_id,
            content=request.content,
            robot_scope=request.robot_scope,
        )
        self._agent.execution_context = context
        await self._agent.init_tools(context=context)
        await self._agent.init_agent()
        history = []
        for item in request.history:
            history.extend((HumanMessage(content=item.content), AIMessage(content=item.answer)))
        async for messages in self._agent.astream("", history, context=context):
            latest = messages[-1] if isinstance(messages, list) and messages else messages
            if not isinstance(latest, (AIMessage, AIMessageChunk)):
                continue
            text = _text_content(latest.content)
            if text:
                yield text


class BiShengAssistantFactory:
    async def create(self, delivery: EPlusTurnDelivery) -> BiShengAssistantRuntime:
        assistant = await AssistantDao.aget_one_assistant(delivery.assistant_id)
        if (
            assistant is None
            or int(assistant.tenant_id) != delivery.tenant_id
            or assistant.is_delete
            or assistant.status != AssistantStatus.ONLINE.value
        ):
            raise LookupError("E+ bound assistant is unavailable")
        agent = AssistantAgent(assistant, delivery.conversation_id, delivery.sender_user_id)
        await agent.init_llm()
        return BiShengAssistantRuntime(agent)


class WorkerConnection:
    def __init__(
        self,
        *,
        ref: BotConnectionRef,
        target: EPlusConnectionTarget,
        ca_pem: bytes | None,
        provider: SqlEPlusTargetProvider,
        robot_service: EPlusRobotService,
        callback_registry: CallbackTaskRegistry,
        recover_once: Callable[[BotConnectionRef, EPlusBotRuntimeContext], Awaitable[None]],
    ) -> None:
        self._ref = ref
        self._provider = provider
        self._robot = robot_service
        self._callback_registry = callback_registry
        self._recover_once = recover_once
        self._client = EPlusConnectionClient(
            EPlusConnectionConfig(
                url=target.connection_url,
                bot_id=target.bot_id,
                secret=target.secret,
                ca_pem=ca_pem,
            ),
            on_message=self._on_message,
        )

    async def wait_authenticated(self) -> None:
        await self._client.wait_authenticated()
        context = await self._provider.runtime_context(self._ref, self)
        if context is not None:
            await self._recover_once(self._ref, context)

    async def run_connection_once(self):
        return await self._client.run_connection_once()

    async def close(self) -> None:
        await self._client.close()

    async def send_with_ack(self, frame: dict[str, Any]):
        return await self._client.send_with_ack(frame)

    async def _on_message(self, frame: dict[str, Any]) -> None:
        self._callback_registry.spawn(self._handle_message(frame))

    async def _handle_message(self, frame: dict[str, Any]) -> None:
        context = await self._provider.runtime_context(self._ref, self)
        if context is None:
            return
        callback = parse_message_callback(frame)
        with _tenant_scope(self._ref.tenant_id):
            await self._robot.handle_message(context, callback)


async def build_worker_runtime() -> EPlusWorkerRuntime:
    database = await get_database_connection()
    session_factory = async_sessionmaker(
        bind=database.async_engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=True,
        autocommit=False,
    )
    redis = await get_redis_client()
    media_service = EPlusMediaService(
        downloader=SecureEPlusMediaDownloader(),
        store=MinioEPlusMediaStore(),
        text_extractor=DailyChatImageTextExtractor(),
    )
    scheduler = EPlusConversationScheduler(session_factory=session_factory)
    robot = EPlusRobotService(
        admission_service=EPlusMessageAdmissionService(
            session_factory=session_factory,
            identity_service=EPlusIdentityService(),
            media_service=media_service,
        ),
        scheduler=scheduler,
        turn_loader=SqlEPlusTurnLoader(session_factory),
        media_service=media_service,
        assistant_factory=BiShengAssistantFactory(),
        reply_factory=ProductionReplyFactory(session_factory, redis),
    )
    provider = SqlEPlusTargetProvider(session_factory)
    callback_registry = CallbackTaskRegistry()
    recovered: set[BotConnectionRef] = set()
    recovery_lock = asyncio.Lock()

    async def recover_once(ref: BotConnectionRef, context: EPlusBotRuntimeContext) -> None:
        async with recovery_lock:
            if ref in recovered:
                return
            with _tenant_scope(ref.tenant_id):
                conversations = await scheduler.recover_queued(
                    tenant_id=ref.tenant_id,
                    bot_config_id=ref.bot_config_id,
                )
                for conversation_id in conversations:
                    await robot.run_turn(context, conversation_id)
            recovered.add(ref)

    def client_factory(target: EPlusConnectionTarget, ca_pem: bytes | None) -> WorkerConnection:
        ref = BotConnectionRef(target.tenant_id, target.bot_config_id)
        return WorkerConnection(
            ref=ref,
            target=target,
            ca_pem=ca_pem,
            provider=provider,
            robot_service=robot,
            callback_registry=callback_registry,
            recover_once=recover_once,
        )

    supervisor = EPlusConnectionSupervisor(
        target_provider=provider,
        client_factory=client_factory,
        redis_client=redis,
        notification_source=RedisConfigNotificationSource(redis),
    )
    return EPlusWorkerRuntime(
        supervisor=supervisor,
        robot_service=robot,
        callback_registry=callback_registry,
    )


@contextlib.contextmanager
def _tenant_scope(tenant_id: int):
    token = set_current_tenant_id(int(tenant_id))
    try:
        yield
    finally:
        current_tenant_id.reset(token)


def _text_content(content: Any) -> str:
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    parts: list[str] = []
    for item in content:
        if isinstance(item, str):
            parts.append(item)
        elif isinstance(item, dict) and item.get("type") == "text" and isinstance(item.get("text"), str):
            parts.append(item["text"])
    return "".join(parts)


async def _run_main() -> None:
    worker = EPlusWorker(settings=settings)
    loop = asyncio.get_running_loop()
    for signum in (signal.SIGTERM, signal.SIGINT):
        with contextlib.suppress(NotImplementedError):
            loop.add_signal_handler(signum, worker.request_stop)
    await worker.run()


def main() -> None:
    asyncio.run(_run_main())


if __name__ == "__main__":
    main()

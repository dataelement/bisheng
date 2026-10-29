import asyncio
from time import monotonic

from loguru import logger
from starlette.websockets import WebSocket, WebSocketDisconnect, WebSocketState

from bisheng.linsight.domain.models.linsight_session_version import (
    LinsightSessionVersionDao,
    SessionVersionStatusEnum,
)
from bisheng.linsight.domain.services.state_message_manager import (
    LinsightStateMessageManager,
    MessageData,
    MessageEventType,
)


class MessageStreamHandle:
    TERMINAL_CHECK_INTERVAL = 15
    TERMINAL_EVENTS = {
        MessageEventType.ERROR_MESSAGE,
        MessageEventType.TASK_TERMINATED,
        MessageEventType.FINAL_RESULT,
    }

    def __init__(self, websocket: WebSocket, session_version_id: str):
        self._websocket = websocket
        self.session_version_id = session_version_id
        self._state_message_manager = LinsightStateMessageManager(session_version_id=session_version_id)

    async def send_message(self, message_data: str) -> None:
        await self._websocket.send_text(message_data)

    async def receive_message(self) -> str:
        return await self._websocket.receive_text()

    async def send_json(self, json_data: dict) -> None:
        await self._websocket.send_json(json_data)

    async def receive_json(self) -> dict:
        return await self._websocket.receive_json()

    async def _terminal_message(self) -> MessageData | None:
        """Persisted completion remains authoritative after a missed notification."""
        info = await LinsightSessionVersionDao.get_by_id(self.session_version_id)
        if info is None:
            return None
        if info.status == SessionVersionStatusEnum.COMPLETED:
            return MessageData(
                event_type=MessageEventType.FINAL_RESULT, data={"output_result": info.output_result or {}}
            )
        if info.status == SessionVersionStatusEnum.TERMINATED:
            return MessageData(event_type=MessageEventType.TASK_TERMINATED, data={})
        if info.status in {SessionVersionStatusEnum.FAILED, SessionVersionStatusEnum.SOP_GENERATION_FAILED}:
            result = info.output_result or {}
            return MessageData(
                event_type=MessageEventType.ERROR_MESSAGE,
                data={
                    "error": result.get("error_message", "Task failed"),
                    "error_code": result.get("error_code"),
                    "error_type": result.get("error_type"),
                },
            )
        return None

    async def _send_stream(self) -> None:
        async with self._state_message_manager.message_stream() as messages:
            next_check = 0.0
            async for payload in messages:
                message = MessageData.model_validate(payload) if payload else None
                if message is None and monotonic() >= next_check:
                    # Checking throughout the connection also repairs a socket
                    # whose final event was consumed before this release.
                    terminal = await self._terminal_message()
                    next_check = monotonic() + self.TERMINAL_CHECK_INTERVAL
                    if terminal:
                        message = terminal
                if message:
                    await self.send_json(message.model_dump())
                    if message.event_type in self.TERMINAL_EVENTS:
                        await self._websocket.close(code=1000, reason="Session finished")
                        return

    async def _watch_disconnect(self) -> None:
        while True:
            await self._websocket.receive_text()

    async def connect(self) -> None:
        await self._websocket.accept()
        try:
            async with asyncio.TaskGroup() as group:
                tasks = {group.create_task(self._send_stream()), group.create_task(self._watch_disconnect())}
                await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                # A departed viewer releases its subscription while the worker
                # is quiet. TaskGroup joins both tasks and reports every failure.
                for task in tasks:
                    task.cancel()
        except* WebSocketDisconnect:
            logger.debug("Task viewer disconnected for {}", self.session_version_id)
        except* Exception:
            logger.exception("Task stream failed for {}", self.session_version_id)
            if (
                self._websocket.client_state == WebSocketState.CONNECTED
                and self._websocket.application_state == WebSocketState.CONNECTED
            ):
                await self._websocket.close(code=1011, reason="Task stream unavailable")

    async def disconnect(self) -> None:
        await self._websocket.close(code=1000, reason="Client disconnected")

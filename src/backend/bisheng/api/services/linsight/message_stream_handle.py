from starlette.websockets import WebSocket

from bisheng.linsight.state_message_manager import LinsightStateMessageManager, MessageData, MessageEventType


class MessageStreamHandle(object):
    def __init__(self, websocket: 'WebSocket', session_version_id: str):
        """
        Inisialisasi MessageStreamHandle
        :param websocket:
        """
        self._websocket = websocket
        self.session_version_id = session_version_id
        self._state_message_manager: LinsightStateMessageManager = LinsightStateMessageManager(
            session_version_id=session_version_id)

    async def send_message(self, message_data: str) -> None:
        """
        Send Message To WebSocket
        :param message_data: Message to send
        """
        await self._websocket.send_text(message_data)

    async def receive_message(self) -> str:
        """
        Received from WebSocket Message
        :return:
        """
        return await self._websocket.receive_text()

    async def send_json(self, json_data: dict) -> None:
        """
        Send JSON Data to WebSocket
        :param json_data: To be sent JSON DATA
        """
        await self._websocket.send_json(json_data)

    async def receive_json(self) -> dict:
        """
        Received from WebSocket right of privacy JSON DATA
        :return:
        """
        return await self._websocket.receive_json()

    # <g id="Bold">Medical Treatment:</g> WebSocket Connected Lifecycle Events
    async def connect(self) -> None:
        """
        Connecting to devices WebSocket
        """
        await self._websocket.accept()

        while True:
            try:
                message = await self._state_message_manager.pop_message()
                if message:
                    await self.send_json(message.model_dump())

                    if message.event_type in [MessageEventType.ERROR_MESSAGE, MessageEventType.TASK_TERMINATED,
                                              MessageEventType.FINAL_RESULT]:
                        await self._websocket.close(code=1000, reason="Session finished or error occurred")
                        break

            except Exception as e:
                await self.send_json(
                    MessageData(event_type=MessageEventType.ERROR_MESSAGE, data={"error": str(e)}).model_dump())
                await self._websocket.close(code=1000, reason=f"Error: {str(e)}")
                break

    async def disconnect(self) -> None:
        """
        detach WebSocket CONNECT
        """
        await self._websocket.close(code=1000, reason="Client disconnected")

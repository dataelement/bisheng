from starlette.websockets import WebSocket

from bisheng.linsight.state_message_manager import LinsightStateMessageManager, MessageData, MessageEventType


class MessageStreamHandle(object):
    def __init__(self, websocket: 'WebSocket', session_version_id: str):
        """
        初始化 MessageStreamHandle
        :param websocket:
        """
        self._websocket = websocket
        self.session_version_id = session_version_id
        self._state_message_manager: LinsightStateMessageManager = LinsightStateMessageManager(
            session_version_id=session_version_id)

    async def send_message(self, message_data: str) -> None:
        """
        发送消息到 WebSocket
        :param message_data: 要发送的消息内容
        """
        await self._websocket.send_text(message_data)

    async def receive_message(self) -> str:
        """
        接收来自 WebSocket 的消息
        :return:
        """
        return await self._websocket.receive_text()

    async def send_json(self, json_data: dict) -> None:
        """
        发送 JSON 数据到 WebSocket
        :param json_data: 要发送的 JSON 数据
        """
        await self._websocket.send_json(json_data)

    async def receive_json(self) -> dict:
        """
        接收来自 WebSocket 的 JSON 数据
        :return:
        """
        return await self._websocket.receive_json()

    # 处理 WebSocket 连接的生命周期事件
    async def connect(self) -> None:
        """
        连接到 WebSocket
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
        断开 WebSocket 连接
        """
        await self._websocket.close(code=1000, reason="Client disconnected")

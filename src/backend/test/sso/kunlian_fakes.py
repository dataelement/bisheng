"""昆联契约测试辅助。没有真实网络或数据库锁保证。"""

from collections import deque
from datetime import datetime, timedelta


class FrozenClock:
    def __init__(self, now: datetime):
        self.now = now

    def __call__(self) -> datetime:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += timedelta(seconds=seconds)


class ScriptedResponses:
    """消费预设分页或异常。额外调用直接失败而非默认为成功。"""

    def __init__(self, *responses):
        self.responses = deque(responses)
        self.requests = []
        self.pause = None

    async def __call__(self, request):
        self.requests.append(request)
        if self.pause is not None:
            await self.pause.wait()
        if not self.responses:
            raise AssertionError("Unexpected extra upstream request")
        response = self.responses.popleft()
        if isinstance(response, Exception):
            raise response
        return response

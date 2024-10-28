import asyncio
import json
# 设置 websockets 的日志级别为 NONE
import logging
from collections import defaultdict
from datetime import datetime, timedelta

from bisheng.api.v1.schemas import resp_500
from bisheng.database.base import session_getter
from bisheng.database.models.message import ChatMessage
from pydantic import BaseModel
from websockets import connect

# 维护一个连接池
connection_pool = defaultdict(asyncio.Queue)
logging.getLogger('websockets').setLevel(logging.ERROR)

expire = 600  # reids 60s 过期


class TimedQueue:

    def __init__(self):
        self.queue = asyncio.Queue()
        self.last_active = datetime.now()

    async def put_nowait(self, item):
        self.last_active = datetime.now()
        await self.queue.put(item)

    async def get_nowait(self):
        self.last_active = datetime.now()
        return await self.queue.get()

    def empty(self):
        return self.queue.empty()

    def qsize(self):
        return self.queue.qsize()


async def clean_inactive_queues(queue: defaultdict, timeout_threshold: timedelta):
    while True:
        current_time = datetime.now()
        for key, timed_queue in list(queue.items()):
            # 如果队列超过设定的阈值时间没有活跃，则清理队列
            if current_time - timed_queue.last_active > timeout_threshold:
                while not timed_queue.empty():
                    timed_queue.get_nowait()  # 从队列中移除任务
                del queue[key]  # 删除队列
        await asyncio.sleep(timeout_threshold.total_seconds())


# 维护一个连接池
connection_pool = defaultdict(TimedQueue)
clean_inactive_queues(connection_pool, timedelta(minutes=5))


async def get_connection(uri, identifier):
    """
    获取WebSocket连接。如果连接池中有可用的连接，则直接返回；
    否则，创建新的连接并添加到连接池。
    """
    if connection_pool[identifier].empty():
        # 建立新的WebSocket连接
        websocket = await connect(uri)

        await connection_pool[identifier].put_nowait(websocket)

    # 从连接池中获取连接
    websocket = await connection_pool[identifier].get_nowait()
    return websocket


async def release_connection(identifier, websocket):
    """
    释放WebSocket连接，将其放回连接池。
    """
    await connection_pool[identifier].put_nowait(websocket)


def comment_answer(message_id: int, comment: str):
    with session_getter() as session:
        message = session.get(ChatMessage, message_id)
        if message:
            message.remark = comment[:4096]
            session.add(message)
            session.commit()


class ContentStreamResp(BaseModel):
    role: str
    content: str


class ChoiceStreamResp(BaseModel):
    index: int = 0
    delta: ContentStreamResp = 0
    session_id: str

    def __str__(self) -> str:
        jsonData = '{"index": "%s", "delta": %s, "session_id": "%s"}' % (
            self.index, json.dumps(self.delta.dict(), ensure_ascii=False), self.session_id)
        return '{"choices":[%s]}\n\n' % (jsonData)


async def event_stream(
    webosocket: connect,
    message: str,
    session_id: str,
    model: str,
    streaming: bool,
):

    payload = {'inputs': message, 'flow_id': model, 'chat_id': session_id}
    try:
        await webosocket.send(json.dumps(payload, ensure_ascii=False))
    except Exception as e:
        yield json.dumps(resp_500(message=str(e)).__dict__)
        return
    sync = ''
    while True:
        try:
            msg = await webosocket.recv()
        except Exception as e:
            yield json.dumps(resp_500(message=str(e)).__dict__)
            break
        if msg is None:
            continue
        # 判断msg 的类型
        res = json.loads(msg)
        if streaming:
            if res.get('type') != 'end' and res.get('message'):
                delta = ContentStreamResp(role='assistant', content=res.get('message'))
                yield str(ChoiceStreamResp(index=0, session_id=session_id, delta=delta))
        else:
            # 通过此处控制下面的close是否发送消息
            if res.get('type') == 'end':
                sync = res.get('message')

        if res.get('type') == 'close':
            if not streaming and sync:
                delta = ContentStreamResp(role='assistant', content=sync)
                msg = ChoiceStreamResp(index=0,
                                       session_id=session_id,
                                       delta=delta,
                                       finish_reason='stop')
                yield '{"choices":[%s]}' % (json.dumps(msg.dict()))
            # 释放连接
            elif streaming:
                yield 'data: [DONE]'
            await release_connection(session_id, webosocket)
            break

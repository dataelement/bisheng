import asyncio
import json
# Pengaturan websockets Log level is NONE
import logging
from collections import defaultdict
from datetime import datetime, timedelta

from pydantic import BaseModel
from websockets import connect

from bisheng.common.errcode.http_error import ServerError
from bisheng.core.database import get_sync_db_session
from bisheng.database.models.message import ChatMessage

# Maintain a connection pool
connection_pool = defaultdict(asyncio.Queue)
logging.getLogger('websockets').setLevel(logging.ERROR)

expire = 600  # reids 60s Overdue


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
            # If the queue is not active beyond the set threshold time, clear the queue
            if current_time - timed_queue.last_active > timeout_threshold:
                while not timed_queue.empty():
                    timed_queue.get_nowait()  # Remove task from queue
                del queue[key]  # Delete queue
        await asyncio.sleep(timeout_threshold.total_seconds())


# Maintain a connection pool
connection_pool = defaultdict(TimedQueue)


# clean_inactive_queues(connection_pool, timedelta(minutes=5))


async def get_connection(uri, identifier):
    """
    DapatkanWebSocketConnections. Returns directly if there are connections available in the connection pool;
    Otherwise, create a new connection and add it to the connection pool.
    """
    if connection_pool[identifier].empty():
        # build newWebSocketCONNECT
        websocket = await connect(uri)

        await connection_pool[identifier].put_nowait(websocket)

    # Get Connection from Connection Pool
    websocket = await connection_pool[identifier].get_nowait()
    return websocket


async def release_connection(identifier, websocket):
    """
    releaseWebSocketConnect and put it back into the connection pool.
    """
    await connection_pool[identifier].put_nowait(websocket)


def comment_answer(message_id: int, comment: str):
    with get_sync_db_session() as session:
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
        yield ServerError(exception=e).to_sse_event_instance_str()
        return
    sync = ''
    while True:
        try:
            msg = await webosocket.recv()
        except Exception as e:
            yield ServerError(exception=e).to_sse_event_instance_str()
            break
        if msg is None:
            continue
        # Judgingmsg of income they generate.
        res = json.loads(msg)
        if streaming:
            if res.get('type') != 'end' and res.get('message'):
                delta = ContentStreamResp(role='assistant', content=res.get('message'))
                yield str(ChoiceStreamResp(index=0, session_id=session_id, delta=delta))
        else:
            # Control the following via thecloseWhether to send a message
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
            # Release Connection
            elif streaming:
                yield 'data: [DONE]'
            await release_connection(session_id, webosocket)
            break

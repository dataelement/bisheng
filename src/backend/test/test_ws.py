import json
import time
import asyncio

from multiprocessing import Process, Queue, Pool
from websockets import connect

host = "192.168.106.120"
port = 3003


async def test_websocket(assistant_id: str, token: str, chat_id: str):
    ws_url = f'ws://{host}:{port}/api/v1/assistant/chat/{assistant_id}?t={token}&chat_id={chat_id}'
    st = time.time()
    async with connect(uri=ws_url) as websocket:
        st2 = time.time()
        await websocket.send(json.dumps({
            "inputs": {"input": "你好"}
        }))
        st3 = time.time()
        first_cost = 0
        stream_cost = 0
        over_cost = 0
        while True:
            msg = await websocket.recv()
            if msg is None:
                continue
            msg = json.loads(msg)
            if first_cost == 0:
                first_cost = time.time() - st3
            print("------------client receive msg ----------", msg)
            if msg['type'] == 'stream':
                if stream_cost == 0:
                    stream_cost = time.time() - st3
            elif msg['type'] == 'close':
                if over_cost == 0:
                    over_cost = time.time() - st3
                break
    # 建立连接耗时，客户端发送消息耗时，从发送消息到收到首条回复的耗时，接受到模型流失输出的耗时，全部返回完毕的耗时
    return st2 - st, st3 - st2, first_cost, stream_cost, over_cost


def test_one(queue: Queue, *args):
    res = asyncio.run(test_websocket(*args))
    queue.put(res)


def test_more_ws():
    # 纯模型对话，无其他任何的技能和工具
    assistant_id = "aa7f588c-e8a3-41a7-9316-80b30bc0ec22"
    # 产品提供的业务股票场景问答
    # assistant_id = "0359764d-db4d-440b-ae16-7bbd80e0a005"

    token = "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJ7XCJ1c2VyX25hbWVcIjogXCJhZG1pblwiLCBcInVzZXJfaWRcIjogMywgXCJyb2xlXCI6IFwiYWRtaW5cIn0iLCJpYXQiOjE3MTI2NjA2ODMsIm5iZiI6MTcxMjY2MDY4MywianRpIjoiMWE0YzZlM2MtYTIwNi00MzQxLTg4ZmYtMWRlNjNkYjFkYjg0IiwiZXhwIjoxNzEyNzQ3MDgzLCJ0eXBlIjoiYWNjZXNzIiwiZnJlc2giOmZhbHNlfQ.A4-BOXZl7m4UPhRFCdNfo7TCHpoDY1B-YYDvkN5bqh4"
    chat_id = "zgqtest_"
    max_num = 100
    p_list = []
    queue = Queue(maxsize=max_num)
    st = time.time()
    for i in range(max_num):
        tmp_chat_id = chat_id + str(i)
        p = Process(target=test_one,
                    args=(queue, assistant_id, token, tmp_chat_id),
                    name='test_ws_' + str(i))
        p_list.append(p)
        p.start()

    for one in p_list:
        one.join()

    all_over_time = time.time() - st
    total_connect_time = 0
    total_client_send_time = 0
    total_first_reply_time = 0
    total_llm_stream_time = 0
    total_over_time = 0
    i = 0
    while not queue.empty():
        i += 1
        res = queue.get()
        total_connect_time += res[0]
        total_client_send_time += res[1]
        total_first_reply_time += res[2]
        total_llm_stream_time += res[3]
        total_over_time += res[4]
        print(f'========== client res\n'
              f'connect_time: {res[0]}\n'
              f'send_time: {res[1]}\n'
              f'reply_time: {res[2]}\n'
              f'stream_time: {res[3]}\n'
              f'over_time: {res[4]}\n')

    print(f'****** suc_client: {i}\n'
          f'avg_connect_time: {total_connect_time / i}\n'
          f'avg_client_send_time: {total_client_send_time / i}\n'
          f'avg_first_reply_time: {total_first_reply_time / i}\n'
          f'avg_llm_stream_time: {total_llm_stream_time / i}\n'
          f'avg_over_time: {total_over_time / i}\n'
          f'all_over_time: {all_over_time}\n'
          )


if __name__ == "__main__":
    test_more_ws()

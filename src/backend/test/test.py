import asyncio
import json
import os
import sys
import time

from aiohttp import web

parent_dir = os.path.dirname(os.path.abspath(__file__)).replace('test', '')
sys.path.append(parent_dir)
os.environ['config'] = os.path.join(parent_dir, 'bisheng/config.dev.yaml')

from bisheng.database.base import session_getter
from bisheng.database.models.user import User
from sqlalchemy import select


async def handle(request):

    await asyncio.sleep(2)
    response = {
        'id':
        'chatcmpl-1016',
        'created':
        time.time(),
        'model':
        'Qwen-14B-Chat',
        'choices': [{
            'index': 0,
            'message': {
                'role': 'assistant',
                'content': 'ok'
            },
            'finish_reason': 'stop'
        }],
        'usage': {
            'prompt_tokens': 34,
            'total_tokens': 59,
            'completion_tokens': 25
        }
    }
    return web.Response(text=json.dumps(response))


app = web.Application()
app.router.add_post('/', handle)


def mysql_session():
    with session_getter() as session:
        print(session.exec(select(User).where(User.user_id == 1)).first())

    print(session.exec(select(User).where(User.user_id == 2)).first())


mysql_session()

# if __name__ == '__main__':
#     web.run_app(app, host='127.0.0.1', port=8080)

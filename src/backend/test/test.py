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

from bisheng import CustomComponent
from langchain.chains.base import Chain
from typing import List, Optional, Dict, Any
from langchain.callbacks.manager import (
    AsyncCallbackManagerForChainRun,
    CallbackManagerForChainRun,
)


class InputChain(CustomComponent):
    documentation: str = 'http://docs.bisheng.org/components/custom'

    class Input(Chain):
        output_key: str = "text"  #: :meta private:

        @property
        def input_keys(self) -> List[str]:
            """需要接受的key
            """
            return ['question', 'dept']

        def _call(
            self,
            inputs: Dict[str, Any],
            run_manager: Optional[CallbackManagerForChainRun] = None,
        ) -> Dict[str, str]:
            print(inputs)
            return {"text": "ok"}

        async def _acall(
            self,
            inputs: Dict[str, Any],
            run_manager: Optional[AsyncCallbackManagerForChainRun] = None,
        ) -> Dict[str, str]:
            print(inputs)
            return {"text": "ok"}

    def build_config(self):
        return {'noNeed': {'display_name': 'Parameter'}}

    def build(self, noNeed: str) -> Input:
        return InputChain().Input()

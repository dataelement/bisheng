import json

import requests

from .types import ChatInput, ChatOutput, Choice, Message, Usage
from .utils import get_ts


class ChatCompletion(object):

    def __init__(self, group_id, api_key, **kwargs):
        ep_url = 'https://api.minimax.chat/v1/text/chatcompletion'
        self.endpoint = f'{ep_url}?GroupId={group_id}'
        self.headers = {
            'Authorization': f'Bearer {api_key}',
            'Content-Type': 'application/json'
        }

    def parseChunkDelta(self, chunk):
        decoded_data = chunk.decode('utf-8')
        parsed_data = json.loads(decoded_data[6:])
        delta_content = parsed_data['choices'][0]['delta']
        return delta_content

    def __call__(self, inp: ChatInput, verbose=False):
        messages = inp.messages
        model = inp.model
        top_p = 0.95 if inp.top_p is None else inp.top_p
        temperature = 0.9 if inp.temperature is None else inp.temperature
        stream = False if inp.stream is None else inp.stream
        max_tokens = 1024 if inp.max_tokens is None else inp.max_tokens
        if abs(temperature) <= 1e-6:
            temperature = 1e-6

        chat_messages = messages
        system_prompt = ('MM智能助理是一款由MinMax自研的，没有调用其他产品接口的大型语言'
                         '模型。MiniMax是一家中国科技公司，一直致力于进行大模型相关的研究。\n----\n')

        if messages[0].role == 'system':
            system_prompt = messages[0].content
            chat_messages = messages[1:]

        new_messages = []
        for m in chat_messages:
            role = 'USER'
            if m.role == 'system' or m.role == 'assistant':
                role = 'BOT'

            new_messages.append({'sender_type': role, 'text': m.content})

        #  role_meta is given, prompt must is not empty
        system_info = {}
        if system_prompt:
            system_info = {
                'prompt': system_prompt,
                'role_meta': {
                    'user_name': '用户',
                    'bot_name': 'MM智能助理'
                }
            }

        payload = {
            'model': model,
            'stream': stream,
            'use_standard_sse': True,
            'messages': new_messages,
            'temperature': temperature,
            'top_p': top_p,
            'tokens_to_generate': max_tokens
        }
        payload.update(system_info)

        if verbose:
            print('payload', payload)

        response = requests.post(self.endpoint,
                                 headers=self.headers,
                                 json=payload)

        req_type = 'chat.completion'
        status_message = 'success'
        status_code = response.status_code
        created = get_ts()
        choices = []
        usage = Usage()
        if status_code == 200:
            try:
                info = json.loads(response.text)
                if info['base_resp']['status_code'] == 0:
                    created = info['created']
                    # reply = info['reply']
                    choices = []
                    for s in info['choices']:
                        index = s['index']
                        finish_reason = s['finish_reason']
                        msg = Message(role='assistant', content=s['text'])
                        cho = Choice(index=index,
                                     message=msg,
                                     finish_reason=finish_reason)
                        choices.append(cho)
                    total_tokens = info['usage']['total_tokens']
                    usage = Usage(total_tokens=total_tokens)
                else:
                    status_code = info['base_resp']['status_code']
                    status_message = info['base_resp']['status_msg']

            except Exception as e:
                status_code = 401
                status_message = str(e)
        else:
            status_code = 400
            status_message = 'requests error'

        if status_code != 200:
            raise Exception(status_message)

        return ChatOutput(status_code=status_code,
                          status_message=status_message,
                          model=model,
                          object=req_type,
                          created=created,
                          choices=choices,
                          usage=usage)

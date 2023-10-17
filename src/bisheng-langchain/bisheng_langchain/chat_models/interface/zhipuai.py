# import json

import zhipuai

from .types import ChatInput, ChatOutput, Choice, Message, Usage
from .utils import get_ts


class ChatCompletion(object):

    def __init__(self, api_key, **kwargs):
        zhipuai.api_key = api_key

    def __call__(self, inp: ChatInput, verbose=False):
        messages = inp.messages
        model = inp.model
        top_p = 0.7 if inp.top_p is None else inp.top_p
        temperature = 0.95 if inp.temperature is None else inp.temperature
        # stream = False if inp.stream is None else inp.stream
        # max_tokens = 1024 if inp.max_tokens is None else inp.max_tokens

        new_messages = []
        system_content = ''
        for m in messages:
            content = m.content
            role = m.role
            if role == 'system':
                system_content += content
                continue
            new_messages.append({'role': role, 'content': content})

        if system_content:
            new_messages[-1]['content'] = (system_content +
                                           new_messages[-1]['content'])

        created = get_ts()
        payload = {
            'model': model,
            'prompt': new_messages,
            'temperature': temperature,
            'top_p': top_p,
            'request_id': str(created),
            'incremental': False
        }

        if verbose:
            print('payload', payload)

        req_type = 'chat.completion'
        status_message = 'success'
        choices = []
        usage = Usage()
        try:
            resp = zhipuai.model_api.invoke(**payload)
            status_code = resp['code']
            status_message = resp['msg']
            if status_code == 200:
                choices = []
                for index, choice in enumerate(resp['data']['choices']):
                    finish_reason = 'default'
                    msg = Message(**choice)
                    cho = Choice(index=index,
                                 message=msg,
                                 finish_reason=finish_reason)
                    choices.append(cho)
                usage = Usage(**resp['data']['usage'])

        except Exception as e:
            status_code = 400
            status_message = str(e)

        if status_code != 200:
            raise Exception(status_message)

        return ChatOutput(status_code=status_code,
                          status_message=status_message,
                          model=model,
                          object=req_type,
                          created=created,
                          choices=choices,
                          usage=usage)

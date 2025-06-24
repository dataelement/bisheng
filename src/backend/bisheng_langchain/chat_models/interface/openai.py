# import json

import openai

from .types import ChatInput, ChatOutput, Choice, Usage
from .utils import get_ts


class ChatCompletion(object):

    def __init__(self, api_key, proxy=None, **kwargs):
        openai.api_key = api_key
        openai.proxy = proxy

    def __call__(self, inp: ChatInput, verbose=False):
        messages = inp.messages
        model = inp.model
        top_p = 0.7 if inp.top_p is None else inp.top_p
        temperature = 0.97 if inp.temperature is None else inp.temperature
        # stream = False if inp.stream is None else inp.stream
        max_tokens = 1024 if inp.max_tokens is None else inp.max_tokens
        stop = None
        if inp.stop is not None:
            stop = inp.stop.split('||')

        new_messages = [m.dict() for m in messages]
        created = get_ts()
        payload = {
            'model': model,
            'messages': new_messages,
            'temperature': temperature,
            'top_p': top_p,
            'stop': stop,
            'max_tokens': max_tokens,
        }
        if inp.functions:
            payload.update({'functions': inp.functions})

        if verbose:
            print('payload', payload)

        req_type = 'chat.completion'
        status_message = 'success'
        choices = []
        usage = Usage()
        try:
            resp = openai.ChatCompletion.create(**payload)
            status_code = 200
            choices = []
            for choice in resp['choices']:
                cho = Choice(**choice)
                choices.append(cho)
            usage = Usage(**resp['usage'])

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

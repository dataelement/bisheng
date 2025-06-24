import json

import requests

from .types import ChatInput, ChatOutput, Choice, Message, Usage
from .utils import get_ts


def get_access_token(api_key, sec_key):
    url = (f'https://aip.baidubce.com/oauth/2.0/token?'
           f'grant_type=client_credentials'
           f'&client_id={api_key}&client_secret={sec_key}')

    payload = json.dumps('')
    headers = {
        'Content-Type': 'application/json',
        'Accept': 'application/json'
    }

    response = requests.request('POST', url, headers=headers, data=payload)
    return response.json().get('access_token')


class ChatCompletion(object):

    def __init__(self, api_key, sec_key, **kwargs):
        self.api_key = api_key
        self.sec_key = sec_key
        self.ep_url = ('https://aip.baidubce.com/rpc/2.0/ai_custom/v1/'
                       'wenxinworkshop/chat/completions')
        self.ep_url_pro = ('https://aip.baidubce.com/rpc/2.0/ai_custom/v1/'
                           'wenxinworkshop/chat/completions_pro')

        self.ep_url_turbo = ('https://aip.baidubce.com/rpc/2.0/ai_custom/v1/'
                             'wenxinworkshop/chat/eb-instant')

        # token = get_access_token(api_key, sec_key)
        # self.endpoint = f"{self.ep_url}?access_token={token}"
        self.headers = {'Content-Type': 'application/json'}

    def __call__(self, inp: ChatInput, verbose=False):
        messages = inp.messages
        model = inp.model
        top_p = 0.8 if inp.top_p is None else inp.top_p
        temperature = 0.95 if inp.temperature is None else inp.temperature
        stream = False if inp.stream is None else inp.stream
        # max_tokens = 1024 if inp.max_tokens is None else inp.max_tokens

        system_content = ''
        new_messages = []
        for m in messages:
            role = m.role
            if role == 'system':
                system_content = m.content
                continue
            new_messages.append({'role': role, 'content': m.content})

        if system_content:
            new_messages[-1]['content'] = system_content + '\n' + new_messages[
                -1]['content']

        payload = {
            'stream': stream,
            'messages': new_messages,
            'temperature': temperature,
            'top_p': top_p
        }

        if verbose:
            print('payload', payload)

        token = get_access_token(self.api_key, self.sec_key)
        endpoint = f'{self.ep_url}?access_token={token}'
        if model == 'ernie-bot-turbo':
            endpoint = f'{self.ep_url_turbo}?access_token={token}'
        elif model == 'ernie-bot-4':
            endpoint = f'{self.ep_url_pro}?access_token={token}'

        response = requests.post(endpoint, headers=self.headers, json=payload)

        req_type = 'chat.completion'
        status_message = 'success'
        status_code = response.status_code
        created = get_ts()
        choices = []
        usage = Usage()
        if status_code == 200:
            try:
                info = json.loads(response.text)
                status_code = info.get('error_code', 200)
                status_message = info.get('error_msg', status_message)
                if status_code == 200:
                    created = info['created']
                    result = info['result']
                    finish_reason = 'default'
                    msg = Message(role='assistant', content=result)
                    choices = [
                        Choice(index=0,
                               message=msg,
                               finish_reason=finish_reason)
                    ]
                    usage = Usage(**info['usage'])
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

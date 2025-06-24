import json

import numpy as np
import requests
from requests.exceptions import HTTPError


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


class EmbeddingClient(object):

    def __init__(self, api_key, sec_key, **kwargs):
        self.api_key = api_key
        self.sec_key = sec_key
        self.ep_url = ('https://aip.baidubce.com/rpc/2.0/ai_custom/v1/'
                       'wenxinworkshop/embeddings')
        self.headers = {'Content-Type': 'application/json'}
        self.max_text_tokens = 384
        self.max_text_num = 16
        self.drop_exceed_token = kwargs.get('drop_exceed_token', True)

    def create(self, model, input, verbose=False, **kwargs):
        texts = input
        if isinstance(texts, str):
            texts = [texts]

        if self.drop_exceed_token:
            texts = [t[:self.max_text_tokens] for t in texts]

        cond = np.all([len(text) <= self.max_text_tokens for text in texts])
        if not cond:
            raise HTTPError('text exceed max token size 384')

        token = get_access_token(self.api_key, self.sec_key)
        endpoint = f'{self.ep_url}/{model}?access_token={token}'

        def _call(sub_texts):
            payload = json.dumps({'input': sub_texts})
            response = requests.post(endpoint,
                                     headers=self.headers,
                                     data=payload)
            status_message = 'success'
            status_code = response.status_code
            usage = {'prompt_tokens': 0, 'total_tokens': 0}
            data = []
            if status_code == 200:
                try:
                    info = json.loads(response.text)
                    status_code = info.get('error_code', 200)
                    status_message = info.get('error_msg', status_message)
                    if status_code == 200:
                        data = info['data']
                        usage = info['usage']
                    else:
                        raise HTTPError(status_message)
                except Exception as e:
                    raise HTTPError(str(e))
            else:
                raise HTTPError('requests error')
            return data, usage

        data = []
        usage = {'prompt_tokens': 0, 'total_tokens': 0}

        for i in range(0, len(texts), self.max_text_num):
            sub_texts = texts[i:(i + self.max_text_num)]
            sub_data, sub_usage = _call(sub_texts)
            data.extend(sub_data)
            usage['prompt_tokens'] += sub_usage['prompt_tokens']
            usage['total_tokens'] += sub_usage['total_tokens']

        outp = dict(status_code=200, model=model, data=data, usage=usage)
        return outp

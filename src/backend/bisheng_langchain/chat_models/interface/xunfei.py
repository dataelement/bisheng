import base64
import hashlib
import hmac
import json
# import ssl
# import threading
from datetime import datetime
from time import mktime
from urllib.parse import urlencode, urlparse
from wsgiref.handlers import format_date_time

import websocket
from websocket import create_connection

import _thread as thread

from .types import ChatInput, ChatOutput, Choice, Message, Usage
from .utils import get_ts


class Ws_Param(object):
    # 初始化
    def __init__(self, APPID, APIKey, APISecret, gpt_url):
        self.APPID = APPID
        self.APIKey = APIKey
        self.APISecret = APISecret
        self.host = urlparse(gpt_url).netloc
        self.path = urlparse(gpt_url).path
        self.gpt_url = gpt_url

    # 生成url
    def create_url(self):
        # 生成RFC1123格式的时间戳
        now = datetime.now()
        date = format_date_time(mktime(now.timetuple()))

        # 拼接字符串
        signature_origin = 'host: ' + self.host + '\n'
        signature_origin += 'date: ' + date + '\n'
        signature_origin += 'GET ' + self.path + ' HTTP/1.1'

        # 进行hmac-sha256进行加密
        signature_sha = hmac.new(
            self.APISecret.encode('utf-8'),
            signature_origin.encode('utf-8'),
            digestmod=hashlib.sha256).digest()

        signature_sha_base64 = base64.b64encode(
            signature_sha).decode(encoding='utf-8')

        authorization_origin = (
          f'api_key="{self.APIKey}", '
          f'algorithm="hmac-sha256", headers="host date request-line",'
          f' signature="{signature_sha_base64}"')

        authorization = base64.b64encode(
            authorization_origin.encode('utf-8')).decode(encoding='utf-8')

        # 将请求的鉴权参数组合为字典
        v = {
            'authorization': authorization,
            'date': date,
            'host': self.host
        }
        # 拼接鉴权参数，生成url
        url = self.gpt_url + '?' + urlencode(v)
        # 此处打印出建立连接时候的url,参考本demo的时候可取消上方打印的注释，
        # 比对相同参数时生成的url与自己代码生成的url是否一致
        return url


# 收到websocket错误的处理
def on_error(ws, error):
    print('### error:', error)


# 收到websocket关闭的处理
def on_close(ws):
    print('### closed ###')


# 收到websocket连接建立的处理
def on_open(ws):
    thread.start_new_thread(run, (ws,))


def run(ws, *args):
    data = json.dumps(gen_params(appid=ws.appid, question=ws.question))
    ws.send(data)


# 收到websocket消息的处理
def on_message(ws, message):
    print(message)
    data = json.loads(message)
    code = data['header']['code']
    if code != 0:
        print(f'请求错误: {code}, {data}')
        ws.close()
    else:
        choices = data['payload']['choices']
        status = choices['status']
        content = choices['text'][0]['content']
        print(content, end='')
        if status == 2:
            ws.close()


def gen_params(appid, question):
    data = {
        'header': {
            'app_id': appid,
            'uid': '1234'
        },
        'parameter': {
            'chat': {
                'domain': 'general',
                'random_threshold': 0.5,
                'max_tokens': 2048,
                'auditing': 'default'
            }
        },
        'payload': {
            'message': {
                'text': [
                    {'role': 'user', 'content': question}
                ]
            }
        }
    }
    return data


class ChatCompletion(object):
    def __init__(self, appid, api_key, api_secret, **kwargs):
        gpt_url1 = 'ws://spark-api.xf-yun.com/v1.1/chat'
        gpt_url2 = 'ws://spark-api.xf-yun.com/v2.1/chat'
        gpt_url3 = 'ws://spark-api.xf-yun.com/v3.1/chat'
        self.wsParam1 = Ws_Param(appid, api_key, api_secret, gpt_url1)
        self.wsParam2 = Ws_Param(appid, api_key, api_secret, gpt_url2)
        self.wsParam3 = Ws_Param(appid, api_key, api_secret, gpt_url3)

        websocket.enableTrace(False)

        # todo: modify to the ws pool
        # self.ws = websocket.WebSocket()
        # self.ws.connect(self.wsUrl)

        # self.mutex = threading.Lock()
        self.header = {'app_id': appid, 'uid': 'elem'}

    def __del__(self):
        pass
        # self.ws.close()

    def __call__(self, inp: ChatInput, verbose=False):
        messages = inp.messages
        model = inp.model
        # top_p = 0.7 if inp.top_p is None else inp.top_p
        temperature = 0.5 if inp.temperature is None else inp.temperature
        # stream = False if inp.stream is None else inp.stream
        max_tokens = 1024 if inp.max_tokens is None else inp.max_tokens
        # stop = None
        # if inp.stop is not None:
        #     stop = inp.stop.split('||')

        new_messages = []
        for m in messages:
            role = m.role
            if role == 'system':
                role = 'user'
            new_messages.append({'role': role, 'content': m.content})

        domain = 'general'
        if model == 'spark-v2.0':
            domain = 'generalv2'
        elif model == 'spark-v3.0':
            domain = 'generalv3'

        created = get_ts()
        payload = {
            'header': self.header,
            'payload': {'message': {'text': new_messages}},
            'parameter': {
              'chat': {
                'domain': domain,
                'temperature': temperature,
                'max_tokens': max_tokens,
                'auditing': 'default'
              }
            }
        }

        if verbose:
            print('payload', payload)

        req_type = 'chat.completion'
        status_code = 200
        status_message = 'success'
        choices = []
        usage = Usage()
        texts = []
        ws = None
        try:
            # self.mutex.acquire()
            if model == 'spark-v2.0':
                wsUrl = self.wsParam2.create_url()
            elif model == 'spark-v3.0':
                wsUrl = self.wsParam3.create_url()
            else:
                wsUrl = self.wsParam1.create_url()

            ws = create_connection(wsUrl)
            ws.send(json.dumps(payload))
            texts = []
            while True:
                raw_data = ws.recv()
                if not raw_data:
                    break
                resp = json.loads(raw_data)
                if resp['header']['code'] == 0:
                    texts.append(
                        resp['payload']['choices']['text'][0]['content'])
                if resp['header']['code'] == 0 and resp['header']['status'] == 2:
                    usage_dict = resp['payload']['usage']['text']
                    usage_dict.pop('question_tokens')
                    usage = Usage(**usage_dict)
        except Exception as e:
            print('exception', e)
            status_code = 401
            status_message = str(e)
        finally:
            if ws:
                ws.close()
            # self.mutex.release()

        if texts:
            finish_reason = 'default'
            msg = Message(role='assistant', content=''.join(texts))
            cho = Choice(index=0, message=msg,
                         finish_reason=finish_reason)
            choices.append(cho)

        return ChatOutput(
            status_code=status_code,
            status_message=status_message,
            model=model, object=req_type, created=created,
            choices=choices, usage=usage)

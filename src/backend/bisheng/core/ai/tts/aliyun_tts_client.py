import aiohttp
import json
import uuid
import time
import hmac
import hashlib
import base64
from urllib.parse import quote
from typing import Optional
from ..base import BaseTTSClient


class AliyunTTSClient(BaseTTSClient):
    """阿里云TTS客户端"""

    def __init__(self, api_key: str, access_key_secret: str, app_key: str, **kwargs):
        super().__init__(api_key, **kwargs)
        self.access_key_secret = access_key_secret
        self.app_key = app_key
        self.endpoint = "https://nls-gateway-cn-shanghai.aliyuncs.com/stream/v1/tts"

    def _generate_signature(self, method: str, uri: str, params: dict, headers: dict):
        """生成阿里云API签名"""
        # 构造签名字符串
        canonicalized_query_string = "&".join([f"{k}={quote(str(v))}" for k, v in sorted(params.items())])
        canonicalized_headers = ""

        string_to_sign = f"{method}\n{uri}\n{canonicalized_query_string}\n{canonicalized_headers}"

        # 使用HMAC-SHA1生成签名
        signature = base64.b64encode(
            hmac.new(
                self.access_key_secret.encode('utf-8'),
                string_to_sign.encode('utf-8'),
                hashlib.sha1
            ).digest()
        ).decode('utf-8')

        return signature

    async def synthesize(
        self,
        text: str,
        voice: Optional[str] = None,
        language: Optional[str] = None,
        format: str = "mp3"
    ) -> bytes:
        """
        使用阿里云TTS API进行语音合成

        Args:
            text: 要合成的文本
            voice: 发音人，如 'xiaogang', 'xiaoli', 'xiaomei'
            language: 语言代码，暂不使用
            format: 音频格式，支持 mp3, wav

        Returns:
            音频字节数据
        """
        # 生成请求参数
        timestamp = str(int(time.time() * 1000))
        nonce = str(uuid.uuid4())

        params = {
            'AccessKeyId': self.api_key,
            'Action': 'RunPreTrainedServiceNew',
            'Algorithm': 'tts',
            'Version': '2019-02-14',
            'SignatureMethod': 'HMAC-SHA1',
            'SignatureVersion': '1.0',
            'SignatureNonce': nonce,
            'Timestamp': timestamp,
            'Format': 'JSON',
            'ServiceVersion': '1.0',
            'AppKey': self.app_key,
            'ModelId': 'sambert-zhijia-v1',
            'Input': json.dumps({
                'text': text,
                'voice': voice or 'zhiyan',
                'format': format,
                'sample_rate': 16000
            }, ensure_ascii=False)
        }

        headers = {
            'Content-Type': 'application/x-www-form-urlencoded',
            'Accept': 'application/json'
        }

        # 生成签名
        signature = self._generate_signature('POST', '/stream/v1/tts', params, headers)
        params['Signature'] = signature

        # 发送请求
        async with aiohttp.ClientSession() as session:
            async with session.post(
                self.endpoint,
                data=params,
                headers=headers
            ) as response:
                if response.status == 200:
                    result = await response.json()
                    if result.get('Code') == 200:
                        data = result.get('Data', {})
                        audio_data = data.get('Result')
                        if audio_data:
                            return base64.b64decode(audio_data)
                        else:
                            raise Exception("TTS合成失败: 未返回音频数据")
                    else:
                        raise Exception(f"TTS合成失败: {result.get('Message')}")
                else:
                    raise Exception(f"请求失败: {response.status}")
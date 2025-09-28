import aiohttp
import json
from typing import Optional
from ..base import BaseTTSClient


class QianfanTTSClient(BaseTTSClient):
    """百度千帆TTS客户端"""

    def __init__(self, api_key: str, secret_key: str, **kwargs):
        super().__init__(api_key, **kwargs)
        self.secret_key = secret_key
        self.access_token = None
        self.token_url = "https://aip.baidubce.com/oauth/2.0/token"
        self.tts_url = "https://tsn.baidu.com/text2audio"

    async def _get_access_token(self):
        """获取访问令牌"""
        if self.access_token:
            return self.access_token

        params = {
            "grant_type": "client_credentials",
            "client_id": self.api_key,
            "client_secret": self.secret_key
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(self.token_url, params=params) as response:
                if response.status == 200:
                    result = await response.json()
                    self.access_token = result.get("access_token")
                    return self.access_token
                else:
                    raise Exception(f"获取访问令牌失败: {response.status}")

    async def synthesize(
        self,
        text: str,
        voice: Optional[str] = None,
        language: Optional[str] = None,
        format: str = "mp3"
    ) -> bytes:
        """
        使用百度千帆API进行语音合成

        Args:
            text: 要合成的文本
            voice: 发音人选择，0-普通女声，1-普通男声，3-情感男声，4-情感女声
            language: 语言代码，暂不使用
            format: 音频格式，支持 mp3, wav

        Returns:
            音频字节数据
        """
        access_token = await self._get_access_token()

        # 设置发音人
        per = voice if voice is not None else "0"

        # 设置音频格式
        aue = "3" if format == "mp3" else "6"  # 3-mp3, 6-wav

        params = {
            "tex": text,
            "tok": access_token,
            "cuid": "python_client",
            "ctp": "1",  # 客户端类型
            "lan": "zh",  # 语言
            "per": per,   # 发音人选择
            "spd": "5",   # 语速，取值0-15，默认为5中语速
            "pit": "5",   # 音调，取值0-15，默认为5中语调
            "vol": "5",   # 音量，取值0-15，默认为5中音量
            "aue": aue    # 音频编码
        }

        async with aiohttp.ClientSession() as session:
            async with session.get(self.tts_url, params=params) as response:
                if response.status == 200:
                    content_type = response.headers.get('Content-Type', '')

                    if 'audio' in content_type:
                        return await response.read()
                    else:
                        # 返回的是JSON错误信息
                        result = await response.json()
                        raise Exception(f"TTS合成失败: {result}")
                else:
                    raise Exception(f"请求失败: {response.status}")
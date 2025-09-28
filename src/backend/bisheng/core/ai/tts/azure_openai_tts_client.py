import openai
from typing import Optional, Literal
from ..base import BaseTTSClient


class AzureOpenAITTSClient(BaseTTSClient):
    """OpenAI TTS客户端"""

    def __init__(self, api_key: str, **kwargs):
        """
        初始化OpenAI TTS客户端
        :param api_key:
        :param kwargs:
        """
        self.model = kwargs.pop("model", "tts-1")
        self.voice = kwargs.pop("voice", "alloy")
        self.client = openai.AsyncAzureOpenAI(api_key=api_key, **kwargs)

    async def synthesize(
            self,
            text: str,
            voice: Optional[str] = None,
            language: Optional[str] = None,
            format: Literal["mp3", "opus", "aac", "flac", "wav", "pcm"] = "mp3"
    ) -> bytes:
        """
        使用OpenAI TTS API进行文本到语音的合成
        :param text:
        :param voice:
        :param language:
        :param format:
        :return:
        """

        response = await self.client.audio.speech.create(
            model=self.model,
            voice=voice or self.voice,
            input=text,
            response_format=format
        )

        if response.response.status_code != 200:
            raise Exception(
                f"OpenAI TTS API请求失败，状态码：{response.response.status_code}，错误信息：{response.response.text}")

        return response.content

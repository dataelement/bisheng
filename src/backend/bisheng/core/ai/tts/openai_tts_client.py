import openai
from typing import Optional
from ..base import BaseTTSClient


class OpenAITTSClient(BaseTTSClient):
    """OpenAI TTS客户端"""
    def __init__(self, api_key: str, **kwargs):
        super().__init__(api_key, **kwargs)
        self.client = openai.AsyncOpenAI(api_key=api_key)

    async def synthesize(
        self,
        text: str,
        voice: Optional[str] = None,
        language: Optional[str] = None,
        format: str = "mp3"
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
            model="tts-1",
            voice=voice or "alloy",
            input=text,
            response_format=format
        )

        return response.content
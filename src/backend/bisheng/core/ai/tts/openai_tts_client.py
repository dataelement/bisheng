from typing import Optional, Literal

import openai

from ..base import BaseTTSClient


class OpenAITTSClient(BaseTTSClient):
    """OpenAI TTSClient"""

    def __init__(self, api_key: str, **kwargs):
        """
        InisialisasiOpenAI TTSClient
        :param api_key:
        :param kwargs:
        """
        self.model = kwargs.pop("model", "tts-1")
        self.voice = kwargs.pop("voice", "alloy")
        self.client = openai.AsyncOpenAI(api_key=api_key, **kwargs)

    async def synthesize(
            self,
            text: str,
            voice: Optional[str] = None,
            language: Optional[str] = None,
            format: Literal["mp3", "opus", "aac", "flac", "wav", "pcm"] = "mp3"
    ) -> bytes:
        """
        UseOpenAI TTS APIText-to-speech synthesis
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
                f"OpenAI TTS API ERROR，Code：{response.response.status_code}，Message：{response.response.text}")

        return response.content

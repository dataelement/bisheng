import asyncio
from typing import Optional

from dashscope.audio.tts_v2 import SpeechSynthesizer

from ..base import BaseTTSClient


class AliyunTTSClient(BaseTTSClient):
    """Alibaba CloudTTSClient"""

    def __init__(self, api_key: str, **kwargs):
        """
        Initialize Alibaba CloudTTSClient
        """
        self.model = kwargs.get("model", "cosyvoice-v2")
        self.voice = kwargs.get("voice", "longxiaochun_v2")
        self.app_key = api_key
        self.synthesizer = SpeechSynthesizer(model=self.model, voice=self.voice)
        self.synthesizer.request.apikey = self.app_key

    def sync_func(self, text: str):
        audio = self.synthesizer.call(text=text)
        return audio

    async def synthesize(
            self,
            text: str,
            voice: Optional[str] = None,
            language: Optional[str] = None,
            format: str = "mp3"
    ) -> bytes:
        """
        Convert text to audio
        :param text:
        :param voice:
        :param language:
        :param format:
        :return:
        """

        audio = await asyncio.to_thread(self.sync_func, text=text)

        if audio is None:
            raise ValueError("TTS synthesis failed, no audio data returned.")

        return audio

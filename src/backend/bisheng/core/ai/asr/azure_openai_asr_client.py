import asyncio
import io
from typing import Union, BinaryIO, Optional

import librosa
import soundfile as sf
import openai

from bisheng.core.ai import BaseASRClient


class AzureOpenAIASRClient(BaseASRClient):
    """微软Azure OpenAI ASR客户端"""

    def __init__(self, api_key: str, **kwargs):
        self.model = kwargs.pop("model", "whisper-1")
        self.client = openai.AsyncAzureOpenAI(api_key=api_key, **kwargs)

    def sync_func(self, audio_bytes):
        speech, sr = librosa.load(audio_bytes, sr=16000)

        # sr 转成 bytes
        audio_file = io.BytesIO()
        sf.write(audio_file, speech, sr, format='WAV')

        audio_file.seek(0)

        return audio_file

    async def transcribe(
            self,
            audio: Union[str, bytes, BinaryIO],
            language: str = "auto",
            model: Optional[str] = None
    ) -> str:
        """
        使用Azure OpenAI Whisper API进行语音识别
        :param audio:
        :param language:
        :param model:
        :return:
        """

        if not audio:
            raise ValueError("Audio input is required")

        if isinstance(audio, str):
            with open(audio, 'rb') as audio_file:
                audio_bytes = audio_file.read()

        elif isinstance(audio, bytes):
            audio_bytes = audio

        elif hasattr(audio, 'read'):
            audio_bytes = audio.read()

        else:
            raise ValueError("Invalid audio input type")

        audio_file = await asyncio.to_thread(self.sync_func, audio_bytes)

        if not audio_file:
            raise ValueError("Failed to process audio input")

        response = await self.client.audio.transcriptions.create(
            file=audio_file,
            model=model or self.model,
            language=language if language != "auto" else None
        )
        return response.text

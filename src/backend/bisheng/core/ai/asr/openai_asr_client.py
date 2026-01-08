from typing import Optional, Union, BinaryIO

import openai

from ..base import BaseASRClient


class OpenAIASRClient(BaseASRClient):
    """OpenAI ASRClient"""

    def __init__(self, api_key: str, **kwargs):
        self.model = kwargs.pop("model", "whisper-1")
        self.client = openai.AsyncOpenAI(api_key=api_key, **kwargs)

    async def _transcribe(
            self,
            audio: Union[str, bytes, BinaryIO],
            language: str = "auto",
            model: Optional[str] = None,
            **kwargs
    ) -> str:
        """
        UseOpenAI Whisper APISpeech Recognition

        Args:
            audio: Audio File Host
            language: Language code, e.g. 'zh', 'en'
            model: Model name, defaults to 'whisper-1'

        Returns:
            Recognized text content
        """

        with open(audio, "rb") as f:
            transcript = await self.client.audio.transcriptions.create(
                model=model or self.model,
                file=f,
                language=language,
                **kwargs
            )

        return transcript.text

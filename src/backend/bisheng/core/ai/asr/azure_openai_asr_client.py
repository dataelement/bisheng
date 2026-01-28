from typing import Optional

import openai

from ..base import BaseASRClient


class AzureOpenAIASRClient(BaseASRClient):
    """MicrosoftAzure OpenAI ASRClient"""

    def __init__(self, api_key: str, **kwargs):
        self.model = kwargs.pop("model", "whisper-1")
        self.client = openai.AsyncAzureOpenAI(api_key=api_key, **kwargs)

    async def _transcribe(
            self,
            audio: str,
            language: str = "auto",
            model: Optional[str] = None,
            **kwargs
    ) -> str:
        """
        UseAzure OpenAI Whisper APISpeech Recognition
        :param audio:
        :param language:
        :param model:
        :return:
        """
        with open(audio, "rb") as f:
            response = await self.client.audio.transcriptions.create(
                file=f,
                model=model or self.model,
                language=language if language != "auto" else None,
                **kwargs
            )
            return response.text

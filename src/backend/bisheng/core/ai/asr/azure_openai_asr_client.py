from typing import Optional

import openai

from ..base import BaseASRClient


class AzureOpenAIASRClient(BaseASRClient):
    """微软Azure OpenAI ASR客户端"""

    def __init__(self, api_key: str, **kwargs):
        self.model = kwargs.pop("model", "whisper-1")
        self.client = openai.AsyncAzureOpenAI(api_key=api_key, **kwargs)

    async def transcribe(
            self,
            audio: str,
            language: str = "auto",
            model: Optional[str] = None,
            **kwargs
    ) -> str:
        """
        使用Azure OpenAI Whisper API进行语音识别
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

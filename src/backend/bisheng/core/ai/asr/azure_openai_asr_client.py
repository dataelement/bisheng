import openai

from ..base import ASRTranscript, BaseASRClient
from .openai_asr_client import transcribe_with_openai_sdk


class AzureOpenAIASRClient(BaseASRClient):
    """Microsoft Azure OpenAI ASR client"""

    def __init__(self, api_key: str, **kwargs):
        self.model = kwargs.pop("model", "whisper-1")
        self.client = openai.AsyncAzureOpenAI(api_key=api_key, **kwargs)

    async def transcribe_file(
        self,
        wav_path: str,
        language: str | None = None,
        model: str | None = None,
    ) -> ASRTranscript:
        return await transcribe_with_openai_sdk(
            self.client,
            wav_path,
            model=model or self.model,
            language=language,
        )

    async def aclose(self) -> None:
        await self.client.close()

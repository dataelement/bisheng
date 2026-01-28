import asyncio
from typing import Optional

from dashscope.audio.asr import Recognition, RecognitionResult

from ..base import BaseASRClient


class AliyunASRClient(BaseASRClient):
    """Alibaba CloudASRClient"""

    def __init__(self, api_key: str, model: str, **kwargs):
        """
        Initialize Alibaba CloudASRClient
        """

        self.api_key = api_key
        self.recognition = Recognition(
            model=model,
            format="wav",
            sample_rate=16000,
            callback=None,
            **kwargs
        )

    # Time-consuming operation, asynchronous execution
    def sync_func(self, temp_file, language=None, model=None):
        result: RecognitionResult = self.recognition.call(temp_file, api_key=self.api_key, language=language,
                                                          model=model)
        return result

    async def _transcribe(
            self,
            audio: str,
            language: Optional[str] = None,
            model: Optional[str] = None,
            **kwargs
    ) -> str:
        result: RecognitionResult = await asyncio.to_thread(self.sync_func, audio, language, model)
        if result.status_code != 200:
            raise RuntimeError(
                f"ASR request failed with status code {result.code} and message {result.message}"
            )

        sentence = result.get_sentence()
        if sentence and sentence[0]:
            return sentence[0]["text"]
        return ""

from typing import Optional, Union, BinaryIO

import openai

from ..base import BaseASRClient


class OpenAIASRClient(BaseASRClient):
    """OpenAI ASR客户端"""

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
        使用OpenAI Whisper API进行语音识别

        Args:
            audio: 音频文件路径、
            language: 语言代码，如 'zh', 'en'
            model: 模型名称，默认为 'whisper-1'

        Returns:
            识别的文本内容
        """

        with open(audio, "rb") as f:
            transcript = await self.client.audio.transcriptions.create(
                model=model or self.model,
                file=f,
                language=language,
                **kwargs
            )

        return transcript.text

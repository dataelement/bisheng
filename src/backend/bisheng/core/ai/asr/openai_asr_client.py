import openai
from typing import Optional, Union, BinaryIO
from bisheng.core.ai.base import BaseASRClient

class OpenAIASRClient(BaseASRClient):
    """OpenAI ASR客户端"""

    def __init__(self, api_key: str, **kwargs):
        self.client = openai.AsyncOpenAI(api_key=api_key, **kwargs)

    async def transcribe(
            self,
            audio: Union[str, bytes, BinaryIO],
            language: str = "auto",
            model: Optional[str] = None
    ) -> str:
        """
        使用OpenAI Whisper API进行语音识别

        Args:
            audio: 音频文件路径、音频字节数据或文件对象
            language: 语言代码，如 'zh', 'en'
            model: 模型名称，默认为 'whisper-1'

        Returns:
            识别的文本内容
        """
        # 处理音频数据
        if isinstance(audio, str):
            with open(audio, 'rb') as audio_file:
                transcript = await self.client.audio.transcriptions.create(
                    model=model or "whisper-1",
                    file=audio_file,
                    language=language
                )
        elif isinstance(audio, bytes):
            import io
            audio_file = io.BytesIO(audio)
            audio_file.name = "audio.wav"  # OpenAI需要文件名来推断格式
            transcript = await self.client.audio.transcriptions.create(
                model=model or "whisper-1",
                file=audio_file,
                language=language
            )
        else:
            transcript = await self.client.audio.transcriptions.create(
                model=model or "whisper-1",
                file=audio,
                language=language
            )

        return transcript.text

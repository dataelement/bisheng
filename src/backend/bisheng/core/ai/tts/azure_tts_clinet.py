from typing import Optional, Literal
from ..base import BaseTTSClient


class AzureAITTSClient(BaseTTSClient):
    """微软Azure TTS客户端"""

    def __init__(self, api_key: str, **kwargs):
        """
        初始化微软Azure TTS客户端
        :param api_key:
        :param kwargs:
        """
        # TODO: 实现Azure TTS客户端初始化
        pass

    async def synthesize(
            self,
            text: str,
            voice: Optional[str] = None,
            language: Optional[str] = None,
            format: Literal["mp3", "opus", "aac", "flac", "wav", "pcm"] = "mp3"
    ) -> bytes:
        """
        使用微软Azure TTS API进行文本到语音的合成
        :param text:
        :param voice:
        :param language:
        :param format:
        :return:
        """
        # TODO: 实现Azure TTS合成功能
        pass

from typing import Union, BinaryIO, Optional

from bisheng.core.ai import BaseASRClient


class AzureASRClient(BaseASRClient):
    """微软Azure ASR客户端"""

    def __init__(self, api_key: str, region: str, **kwargs):
        # TODO: 实现Azure ASR客户端初始化
        pass

    async def transcribe(
            self,
            audio: Union[str, bytes, BinaryIO],
            language: str = "auto",
            model: Optional[str] = None
    ) -> str:
        """
        使用微软Azure Speech API进行语音识别
        :param audio:
        :param language:
        :param model:
        :return:
        """
        # TODO: 实现Azure ASR转录功能
        pass

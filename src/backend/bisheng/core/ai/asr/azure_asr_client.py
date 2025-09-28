from bisheng.core.ai import BaseASRClient


class AzureASRClient(BaseASRClient):
    """微软Azure ASR客户端"""

    def __init__(self, api_key: str, region: str, **kwargs):
        super().__init__(api_key, **kwargs)
        self.region = region
        self.endpoint = f"https://{region}.stt.speech.microsoft.com/speech/recognition/conversation/cognitiveservices/v3.0"

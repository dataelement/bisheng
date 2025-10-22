import asyncio
import os

import pytest

from bisheng.core.ai import AzureOpenAIASRClient


@pytest.mark.asyncio
async def test_aliyun_asr():
    from ..asr import AliyunASRClient
    api_key = os.environ.get('ALIYUN_API_KEY')
    client = AliyunASRClient(api_key=api_key, model="paraformer-realtime-v2")
    with open("./data/asr_example.wav", "rb") as f:
        audio = f.read()
    text = await client.transcribe(audio)
    assert text == "Hello word, 这里是阿里巴巴语音实验室。"


@pytest.mark.asyncio
async def test_aliyun_tts():
    from ..tts import AliyunTTSClient
    api_key = os.environ.get('ALIYUN_API_KEY')
    client = AliyunTTSClient(api_key=api_key)
    audio_bytes = await client.synthesize("你好，世界！")
    with open("./data/aliyun_result.mp3", "wb") as f:
        f.write(audio_bytes)

    assert os.path.exists("./data/aliyun_result.mp3")


@pytest.mark.asyncio
async def test_azure_openai_asr():
    api_key = os.environ.get('AZURE_OPENAI_API_KEY')
    api_version = os.environ.get('AZURE_OPENAI_API_VERSION')
    azure_endpoint = os.environ.get('AZURE_OPENAI_ENDPOINT')
    client = AzureOpenAIASRClient(api_key=api_key, model="gpt-4o-transcribe", azure_endpoint=azure_endpoint,
                                  api_version=api_version)
    text = await client.transcribe("./data/asr_example.wav")
    assert text == "Hello word, 这里是阿里巴巴语音实验室。"


@pytest.mark.asyncio
async def test_azure_openai_tts():
    from ..tts import AzureOpenAITTSClient
    api_key = os.environ.get('AZURE_OPENAI_API_KEY')
    api_version = os.environ.get('AZURE_OPENAI_API_VERSION')
    azure_endpoint = os.environ.get('AZURE_OPENAI_ENDPOINT')
    client = AzureOpenAITTSClient(api_key=api_key, model="gpt-4o-transcribe", azure_endpoint=azure_endpoint,
                                  api_version=api_version)
    audio_bytes = await client.synthesize("Hello, world!")
    with open("./data/azure_openai_result.mp3", "wb") as f:
        f.write(audio_bytes)

    assert os.path.exists("./data/azure_openai_result.mp3")


def test_xinference_rerank():
    from ..rerank.xinference_rerank import XinferenceRerank
    api_key = os.environ.get('XINFERENCE_API_KEY')
    base_url = os.environ.get('XINFERENCE_BASE_URL')
    model_uid = os.environ.get('XINFERENCE_RERANK_MODEL_UID')

    reranker = XinferenceRerank(base_url=base_url, api_key=api_key, model_uid=model_uid)


async def main():
    await test_aliyun_asr()
    # await test_aliyun_tts()


if __name__ == "__main__":
    asyncio.run(main())

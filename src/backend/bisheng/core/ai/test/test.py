import asyncio
import os

import pytest


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


async def test_azure_openai_tts():
    from ..tts import AzureOpenAITTSClient
    api_key = os.environ.get('AZURE_OPENAI_API_KEY')
    client = AzureOpenAITTSClient(api_key=api_key, model="tts-1", voice="alloy")
    audio_bytes = await client.synthesize("Hello, world!")
    with open("./data/azure_openai_result.mp3", "wb") as f:
        f.write(audio_bytes)


async def main():
    await test_aliyun_asr()
    # await test_aliyun_tts()


if __name__ == "__main__":
    asyncio.run(main())

import asyncio
import os
import tempfile
import time
from typing import Optional, Union, BinaryIO

import dashscope
import librosa
import soundfile as sf
from dashscope.audio.asr import Recognition, RecognitionResult

from ..base import BaseASRClient

temp_dir = tempfile.gettempdir()


class AliyunASRClient(BaseASRClient):
    """阿里云ASR客户端"""

    def __init__(self, api_key: str, model: str, **kwargs):
        """
        初始化阿里云ASR客户端

        Args:
            access_key_id (str): 阿里云访问密钥ID
            access_key_secret (str): 阿里云访问密钥Secret
            region_id (str): 阿里云区域ID，默认值为"cn-shanghai"
        """
        dashscope.api_key = api_key

        self.recognition = Recognition(
            model=model,
            format="wav",
            sample_rate=16000,
            callback=None
        )

    # 耗时操作，异步执行
    def sync_func(self, audio, temp_file, language=None, model=None):
        speech, sr = librosa.load(audio, sr=16000)

        sf.write(temp_file, speech, sr, format='WAV')

        result: RecognitionResult = self.recognition.call(temp_file)

        return result

    async def transcribe(
            self,
            audio: Union[str, bytes, BinaryIO],
            language: Optional[str] = None,
            model: Optional[str] = None):
        """
        将音频转换为文本
        :param audio:
        :param language:
        :param model:
        :return:
        """

        temp_file = os.path.join(temp_dir, str(time.time_ns()) + ".wav")

        try:

            result: RecognitionResult = await asyncio.to_thread(self.sync_func, audio, temp_file, language, model)
            if result.status_code != 200:
                raise RuntimeError(
                    f"ASR request failed with status code {result.code} and message {result.message}"
                )

            sentence = result.get_sentence()
            return sentence[0]["text"]
        except Exception as e:
            raise e
        finally:
            if os.path.exists(temp_file):
                os.remove(temp_file)

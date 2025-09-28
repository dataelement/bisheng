import asyncio
import os
import tempfile
import time
from typing import Optional, Union, BinaryIO

import librosa
import soundfile as sf
from aip import AipSpeech
from ..base import BaseASRClient

temp_dir = tempfile.gettempdir()


class QianfanASRClient(BaseASRClient):
    """百度千帆ASR客户端"""

    def __init__(self, app_id: str, api_key: str, secret_key: str, **kwargs):
        """
        初始化百度千帆ASR客户端
        :param app_id:
        :param api_key:
        :param secret_key:
        :param kwargs:
        """
        self.client = AipSpeech(app_id, api_key, secret_key)

    # 耗时操作，异步执行
    def sync_func(self, audio, temp_file, language=None, model=None):
        speech, sr = librosa.load(audio, sr=16000)

        sf.write(temp_file, speech, sr, format='WAV')

        with open(temp_file, 'rb') as f:
            data = f.read()

        result = self.client.asr(
            data,
            'wav',
            16000,
            {
                'dev_pid': 1537 if language == 'zh' else 1737,
            }
        )

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
            result = await asyncio.to_thread(self.sync_func, audio, temp_file, language, model)

            if 'result' in result:
                return result['result'][0]
            else:
                raise Exception("ASR Error: {}".format(result))
        finally:
            if os.path.exists(temp_file):
                os.remove(temp_file)

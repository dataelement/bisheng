from http import HTTPStatus
import dashscope
import json
import requests
import os
from dashscope.audio.asr import Recognition
from http import HTTPStatus
import dashscope
import json
import requests
from dashscope.audio.asr import Recognition
import soundfile as sf


class QwenSTT:
    def __init__(self, **kwargs):
        """
        初始化 STT 类
        :param api_key: 用于调用 API 的密钥
        """
        self.api_key = kwargs.get('api_key')
        self.model = kwargs.get('model')

    def get_format(self, file_path):
        """
        :param file_path: 音频文件 路径
        :return: pcm、wav、mp3、opus、speex、aac、amr 或 None
        """
        # 定义支持的音频格式及其对应的扩展名
        format_mapping = {
            '.pcm': 'pcm',
            '.wav': 'wav',
            '.mp3': 'mp3',
            '.opus': 'opus',
            '.speex': 'speex',
            '.aac': 'aac',
            '.amr': 'amr'
        }
        # 从文件路径中提取扩展名并转换为小写

        file_extension = os.path.splitext(file_path)[1].lower()
        # 根据扩展名查找对应的音频格式
        return format_mapping.get(file_extension)

    def get_sample_rate(self, file_path):
        """
        :param file_path: 音频文件 路径
        :return: 8000,16000 或 None
        """
        try:
            # 读取音频文件的采样率
            _, sample_rate = sf.read(file_path, dtype='float32', always_2d=True)
            return sample_rate
        except Exception as e:
            print(f"读取音频文件 {file_path} 失败: {e}")
            return None

    def transcribe(self, file_path):
        """
        执行语音转录
        :param file_path: 要转录的音频文件 路径
        :return: 转录结果或错误信息
        """
        try:
            dashscope.api_key = self.api_key
            recognition = Recognition(model=self.model,
                                      format=self.get_format(file_path),
                                      sample_rate=self.get_sample_rate(file_path),
                                      language_hints=['zh', 'en'],
                                      callback=None)
            result = recognition.call(file_path)  # 修改为 audio 参数
            if result.status_code == HTTPStatus.OK:
                data = result.get_sentence()
                result = ""
                for t in data:
                    result += t["text"]
                return result
        except Exception as e:
            raise Exception(f"An error occurred during transcription {e}")

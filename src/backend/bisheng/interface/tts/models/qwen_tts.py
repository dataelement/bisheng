import traceback

import dashscope
from dashscope.audio.tts_v2 import SpeechSynthesizer
from loguru import logger


class QwenTTS:
    def __init__(self, **kwargs):
        """
        初始化 TextToSpeechConverter 类
        :param api_key: DashScope 的 API Key
        :param model: 语音合成模型
        :param voice: 语音合成音色
        """
        self.api_key = kwargs.get('api_key')
        self.model = kwargs.get('model')
        self.voice = kwargs.get('voice')
        self.synthesizer = SpeechSynthesizer(model=self.model, voice=self.voice)
        self.synthesizer.request.apikey = self.api_key

    def synthesize_and_save(self, text, file_path):
        """
        合成文本并将音频保存到指定文件路径
        :param text: 待合成的文本
        :param file_path: 保存音频的文件路径
        """
        try:
            # 发送待合成文本，获取二进制音频
            #dashscope.api_key = self.api_key
            audio = self.synthesizer.call(text)
            print('[Metric] requestId: {}, first package delay ms: {}'.format(
                self.synthesizer.get_last_request_id(),
                self.synthesizer.get_first_package_delay()))

            # 将音频保存至本地
            with open(file_path, 'wb') as f:
                f.write(audio)
            print(f"音频已成功保存到 {file_path}")
        except Exception as e:
            logger.exception('init bisheng llm error')
            raise Exception(f'初始化llm失败，请检查配置或联系管理员。错误信息：{e}')